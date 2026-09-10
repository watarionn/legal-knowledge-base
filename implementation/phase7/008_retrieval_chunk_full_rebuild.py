from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

HERE = Path(__file__).resolve().parent
PHASE5_DIR = HERE.parent / "phase5"
CHUNK_BUILDER_PATH = PHASE5_DIR / "024_retrieval_chunk_builder.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CHUNK = _load("legal_kb_phase7_full_chunk_builder", CHUNK_BUILDER_PATH)

INSERT_SQL = """
INSERT INTO legal_kb.retrieval_chunk (
    chunk_id, chunking_version, chunking_config_sha256, soft_max_chars,
    document_pk, law_id, law_revision_id, source_xml_sha256,
    anchor_document_order, start_document_order,
    end_document_order, source_document_orders, anchor_node_id,
    start_node_id, end_node_id, anchor_tag_name,
    anchor_structural_num, anchor_display_label, context_prefix,
    retrieval_text, retrieval_text_sha256, char_count,
    source_unit_count, is_oversize
) VALUES (
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s,
    %s, %s, decode(%s, 'hex'),
    decode(%s, 'hex'), decode(%s, 'hex'), %s,
    %s, %s, %s,
    %s, %s, %s,
    %s, %s
)
"""


def _chunk_params(chunk: Any) -> tuple[Any, ...]:
    return (
        chunk.chunk_id,
        chunk.chunking_version,
        chunk.chunking_config_sha256,
        chunk.soft_max_chars,
        chunk.document_pk,
        chunk.law_id,
        chunk.law_revision_id,
        chunk.source_xml_sha256,
        chunk.anchor_document_order,
        chunk.start_document_order,
        chunk.end_document_order,
        list(chunk.source_document_orders),
        chunk.anchor_node_id_hex,
        chunk.start_node_id_hex,
        chunk.end_node_id_hex,
        chunk.anchor_tag_name,
        chunk.anchor_structural_num,
        chunk.anchor_display_label,
        chunk.context_prefix,
        chunk.retrieval_text,
        chunk.retrieval_text_sha256,
        chunk.char_count,
        chunk.source_unit_count,
        chunk.is_oversize,
    )


def eligible_document_pks(conn: Any) -> list[int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.document_pk
            FROM legal_kb.law_document d
            WHERE d.parse_status IN ('succeeded', 'succeeded-with-warnings')
              AND EXISTS (
                  SELECT 1
                  FROM legal_kb.provision_node n
                  WHERE n.document_pk=d.document_pk
                    AND n.text_original IS NOT NULL
                    AND btrim(n.text_original) <> ''
              )
            ORDER BY d.document_pk
            """
        )
        return [int(row[0]) for row in cur.fetchall()]


def completed_document_pks(conn: Any, config_sha: str) -> set[int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT document_pk
            FROM legal_kb.retrieval_chunk
            WHERE chunking_config_sha256=%s
            """,
            (config_sha,),
        )
        return {int(row[0]) for row in cur.fetchall()}


def _write_result(path: Path | None, value: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def rebuild_all(
    database_url: str,
    *,
    chunking_version: str = CHUNK.CHUNKING_VERSION,
    max_chars: int = CHUNK.DEFAULT_MAX_CHARS,
    resume: bool = True,
    progress_every: int = 25,
    result_path: Path | None = None,
    max_documents: int | None = None,
) -> dict[str, Any]:
    if progress_every < 1:
        raise ValueError("progress_every must be >= 1")
    if max_documents is not None and max_documents < 1:
        raise ValueError("max_documents must be >= 1")
    config_sha = CHUNK.chunking_config_sha256(chunking_version, max_chars)
    started = time.monotonic()

    import psycopg

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "runner": "008_retrieval_chunk_full_rebuild.py",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "chunking_version": chunking_version,
        "chunking_config_sha256": config_sha,
        "soft_max_chars": max_chars,
        "resume": resume,
        "database_url_recorded": False,
        "eligible_document_count": 0,
        "processed_document_count": 0,
        "skipped_existing_document_count": 0,
        "built_document_count": 0,
        "inserted_chunk_count": 0,
        "oversize_chunk_count": 0,
        "failed_document_count": 0,
        "failures": [],
        "status": "running",
    }

    with psycopg.connect(database_url, autocommit=True) as conn:
        documents = eligible_document_pks(conn)
        if max_documents is not None:
            documents = documents[:max_documents]
        result["eligible_document_count"] = len(documents)

        if resume:
            completed = completed_document_pks(conn, config_sha)
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM legal_kb.retrieval_chunk WHERE chunking_config_sha256=%s",
                    (config_sha,),
                )
            completed = set()

        for index, document_pk in enumerate(documents, 1):
            result["processed_document_count"] = index
            if document_pk in completed:
                result["skipped_existing_document_count"] += 1
            else:
                try:
                    meta = CHUNK.load_document_meta(conn, document_pk)
                    nodes = CHUNK.load_document_nodes(conn, document_pk)
                    chunks = CHUNK.build_document_chunks(
                        meta,
                        nodes,
                        chunking_version=chunking_version,
                        max_chars=max_chars,
                    )
                    if not chunks:
                        raise AssertionError(
                            "eligible document produced no retrieval chunks"
                        )
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute(
                                "DELETE FROM legal_kb.retrieval_chunk "
                                "WHERE document_pk=%s AND chunking_config_sha256=%s",
                                (document_pk, config_sha),
                            )
                            cur.executemany(
                                INSERT_SQL,
                                [_chunk_params(chunk) for chunk in chunks],
                            )
                    result["built_document_count"] += 1
                    result["inserted_chunk_count"] += len(chunks)
                    result["oversize_chunk_count"] += sum(
                        1 for chunk in chunks if chunk.is_oversize
                    )
                except Exception as exc:
                    result["failed_document_count"] += 1
                    result["failures"].append(
                        {
                            "document_pk": document_pk,
                            "error_type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )

            if index % progress_every == 0 or index == len(documents):
                result["elapsed_seconds"] = round(time.monotonic() - started, 3)
                _write_result(result_path, result)
                print(
                    json.dumps(
                        {
                            "progress": f"{index}/{len(documents)}",
                            "built": result["built_document_count"],
                            "skipped": result["skipped_existing_document_count"],
                            "chunks": result["inserted_chunk_count"],
                            "failed": result["failed_document_count"],
                            "elapsed_seconds": result["elapsed_seconds"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

        with conn.cursor() as cur:
            cur.execute("ANALYZE legal_kb.retrieval_chunk")
            cur.execute(
                """
                SELECT count(*), count(DISTINCT document_pk),
                       count(*) FILTER (WHERE is_oversize)
                FROM legal_kb.retrieval_chunk
                WHERE chunking_config_sha256=%s
                """,
                (config_sha,),
            )
            chunk_count, document_count, oversize_count = cur.fetchone()

    result["database_chunk_count"] = int(chunk_count)
    result["database_document_count"] = int(document_count)
    result["database_oversize_chunk_count"] = int(oversize_count)
    result["status"] = (
        "succeeded" if result["failed_document_count"] == 0 else "partial"
    )
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write_result(result_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild Phase 5.3 retrieval chunks for every eligible Phase 4 document"
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("LEGAL_KB_DATABASE_URL")
        or os.environ.get("LEGAL_KB_DSN")
        or os.environ.get("DATABASE_URL"),
    )
    parser.add_argument("--chunking-version", default=CHUNK.CHUNKING_VERSION)
    parser.add_argument("--max-chars", type=int, default=CHUNK.DEFAULT_MAX_CHARS)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--max-documents", type=int)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit(
            "LEGAL_KB_DATABASE_URL, LEGAL_KB_DSN, DATABASE_URL, or --database-url is required"
        )
    result = rebuild_all(
        args.database_url,
        chunking_version=args.chunking_version,
        max_chars=args.max_chars,
        resume=not args.no_resume,
        progress_every=args.progress_every,
        result_path=args.result,
        max_documents=args.max_documents,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "succeeded":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
