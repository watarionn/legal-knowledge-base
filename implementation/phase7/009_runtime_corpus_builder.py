from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
PHASE3_DIR = HERE.parent / "phase3"
PHASE4_DIR = HERE.parent / "phase4"
PHASE5_DIR = HERE.parent / "phase5"

PRE_CHUNK_DDL = (
    PHASE3_DIR / "001_law_history_schema.sql",
    PHASE4_DIR / "001_xml_structure_schema.sql",
    PHASE5_DIR / "001_temporal_resolution_schema.sql",
    PHASE5_DIR / "006_lexical_structural_search_schema.sql",
    PHASE5_DIR / "012_search_literal_hardening.sql",
    PHASE5_DIR / "022_retrieval_chunk_schema.sql",
)
POST_CHUNK_DDL = (PHASE5_DIR / "033_hybrid_retrieval_schema.sql",)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SNAPSHOT = _load(
    "legal_kb_phase7_official_bulk_snapshot",
    HERE / "007_official_bulk_snapshot.py",
)
FULL_CHUNKS = _load(
    "legal_kb_phase7_retrieval_chunk_full_rebuild",
    HERE / "008_retrieval_chunk_full_rebuild.py",
)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def apply_ddl(database_url: str, paths: tuple[Path, ...]) -> str:
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW server_version_num")
            version_num = int(cur.fetchone()[0])
            if version_num < 160000:
                raise RuntimeError(
                    f"PostgreSQL 16+ required; server_version_num={version_num}"
                )
            cur.execute("SELECT version()")
            version = str(cur.fetchone()[0])
        for path in paths:
            with conn.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
    return version


def run_phase3(
    database_url: str,
    work_dir: Path,
    *,
    workers: int,
    history_request_interval: float,
) -> dict[str, Any]:
    module = _load(
        "legal_kb_phase7_phase3_bootstrap",
        PHASE3_DIR / "007_parallel_full_bootstrap.py",
    )
    raw_dir = work_dir / "phase3-raw"
    report_path = work_dir / "phase3-full.json"
    argv = [
        "--dsn",
        database_url,
        "--raw-dir",
        str(raw_dir),
        "--report",
        str(report_path),
        "--workers",
        str(workers),
        "--history-request-interval",
        str(history_request_interval),
        "--progress-every",
        "100",
    ]
    return_code = int(module.main(argv))
    if return_code != 0:
        raise RuntimeError(f"Phase 3 bootstrap returned {return_code}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def run_phase4(
    database_url: str,
    archive: Path,
    manifest_path: Path,
    work_dir: Path,
) -> dict[str, Any]:
    module = _load(
        "legal_kb_phase7_phase4_full_import",
        PHASE4_DIR / "011_full_relational_import.py",
    )
    report_path = work_dir / "phase4-full-relational-import.json"
    run_id = "phase7-runtime-phase4-" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    result = module.run(
        archive_dir=archive.parent,
        manifest_path=manifest_path,
        database_url=database_url,
        result_path=report_path,
        run_id=run_id,
        batch_size=25000,
        progress_every=100,
        preflight_only=False,
        max_documents=None,
        fail_fast=False,
    )
    if int(result.get("failed_document_count", 0)) != 0:
        raise RuntimeError("Phase 4 runtime import reported failed documents")
    return result


def database_counts(database_url: str, config_sha: str) -> dict[str, int]:
    import psycopg

    queries = {
        "law": "SELECT count(*) FROM legal_kb.law",
        "law_revision": "SELECT count(*) FROM legal_kb.law_revision",
        "law_document": "SELECT count(*) FROM legal_kb.law_document",
        "provision_node": "SELECT count(*) FROM legal_kb.provision_node",
        "retrieval_chunk": (
            "SELECT count(*) FROM legal_kb.retrieval_chunk "
            "WHERE chunking_config_sha256=%s"
        ),
        "retrieval_chunk_document": (
            "SELECT count(DISTINCT document_pk) FROM legal_kb.retrieval_chunk "
            "WHERE chunking_config_sha256=%s"
        ),
    }
    output: dict[str, int] = {}
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for name, sql in queries.items():
                if name.startswith("retrieval_chunk"):
                    cur.execute(sql, (config_sha,))
                else:
                    cur.execute(sql)
                output[name] = int(cur.fetchone()[0])
    return output


def run_pipeline(
    *,
    archive: Path,
    manifest_path: Path,
    captured_on: date,
    database_url: str,
    work_dir: Path,
    workers: int,
    history_request_interval: float,
    max_chars: int,
    skip_ddl: bool,
    skip_phase3: bool,
    skip_phase4: bool,
    skip_chunks: bool,
) -> dict[str, Any]:
    if workers < 1 or workers > 8:
        raise ValueError("workers must be between 1 and 8")
    if history_request_interval < 0:
        raise ValueError("history_request_interval must be >= 0")
    work_dir.mkdir(parents=True, exist_ok=True)
    pipeline_path = work_dir / "phase7-runtime-corpus.json"
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "runner": "009_runtime_corpus_builder.py",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_captured_on": captured_on.isoformat(),
        "database_url_recorded": False,
        "runtime_materialization": (
            "phase3 history + phase4 structure + phase5.3 retrieval chunks"
        ),
        "search_unit_population_required": False,
        "embedding_population_required": False,
        "steps": {},
        "status": "running",
    }

    try:
        manifest = SNAPSHOT.inspect_archive(archive, captured_on)
        SNAPSHOT.write_manifest(manifest_path, manifest)
        result["steps"]["snapshot"] = {
            "status": "succeeded",
            "archive_name": archive.name,
            "archive_sha256": manifest["parts"][0]["sha256"],
            "xml_count": manifest["totals"]["xml_count"],
            "unique_law_id_count": manifest["totals"]["unique_law_id_count"],
        }

        if skip_ddl:
            result["steps"]["pre_chunk_ddl"] = {"status": "skipped"}
        else:
            version = apply_ddl(database_url, PRE_CHUNK_DDL)
            result["steps"]["pre_chunk_ddl"] = {
                "status": "succeeded",
                "postgres_version": version,
            }

        if skip_phase3:
            result["steps"]["phase3"] = {"status": "skipped"}
        else:
            phase3 = run_phase3(
                database_url,
                work_dir,
                workers=workers,
                history_request_interval=history_request_interval,
            )
            result["steps"]["phase3"] = {
                "status": phase3.get("result_status"),
                "database_counts": phase3.get("database_counts"),
                "resume_skipped_law_count": phase3.get(
                    "resume_skipped_law_count"
                ),
                "residual_failed_law_count": len(phase3.get("failed_laws", {})),
            }
            if phase3.get("result_status") != "succeeded":
                raise RuntimeError("Phase 3 runtime bootstrap did not succeed")

        if skip_phase4:
            result["steps"]["phase4"] = {"status": "skipped"}
        else:
            phase4 = run_phase4(
                database_url,
                archive,
                manifest_path,
                work_dir,
            )
            result["steps"]["phase4"] = {
                "status": phase4.get("status"),
                "inserted_document_count": phase4.get(
                    "inserted_document_count"
                ),
                "skipped_existing_document_count": phase4.get(
                    "skipped_existing_document_count"
                ),
                "deferred_unreconciled_document_count": phase4.get(
                    "deferred_unreconciled_document_count"
                ),
                "failed_document_count": phase4.get("failed_document_count"),
                "inserted_node_count": phase4.get("inserted_node_count"),
            }

        config_sha = FULL_CHUNKS.CHUNK.chunking_config_sha256(
            FULL_CHUNKS.CHUNK.CHUNKING_VERSION,
            max_chars,
        )
        if skip_chunks:
            result["steps"]["retrieval_chunks"] = {"status": "skipped"}
        else:
            chunks = FULL_CHUNKS.rebuild_all(
                database_url,
                max_chars=max_chars,
                resume=True,
                progress_every=25,
                result_path=work_dir / "phase7-retrieval-chunks.json",
            )
            result["steps"]["retrieval_chunks"] = {
                "status": chunks.get("status"),
                "chunking_config_sha256": chunks.get(
                    "chunking_config_sha256"
                ),
                "eligible_document_count": chunks.get(
                    "eligible_document_count"
                ),
                "database_document_count": chunks.get(
                    "database_document_count"
                ),
                "database_chunk_count": chunks.get("database_chunk_count"),
                "failed_document_count": chunks.get("failed_document_count"),
            }
            if chunks.get("status") != "succeeded":
                raise RuntimeError("retrieval chunk full rebuild did not succeed")

        if not skip_ddl:
            apply_ddl(database_url, POST_CHUNK_DDL)
            result["steps"]["post_chunk_ddl"] = {"status": "succeeded"}
        else:
            result["steps"]["post_chunk_ddl"] = {"status": "skipped"}

        result["database_counts"] = database_counts(database_url, config_sha)
        result["chunking_config_sha256"] = config_sha
        result["status"] = "succeeded"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        write_json(pipeline_path, result)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a current Phase 7 runtime corpus from official e-Gov all_xml.zip"
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--captured-on", type=date.fromisoformat, default=date.today())
    parser.add_argument(
        "--database-url",
        default=os.environ.get("LEGAL_KB_DATABASE_URL")
        or os.environ.get("LEGAL_KB_DSN")
        or os.environ.get("DATABASE_URL"),
    )
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--history-request-interval", type=float, default=0.6)
    parser.add_argument("--max-chars", type=int, default=1200)
    parser.add_argument("--skip-ddl", action="store_true")
    parser.add_argument("--skip-phase3", action="store_true")
    parser.add_argument("--skip-phase4", action="store_true")
    parser.add_argument("--skip-chunks", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit(
            "LEGAL_KB_DATABASE_URL, LEGAL_KB_DSN, DATABASE_URL, or --database-url is required"
        )
    result = run_pipeline(
        archive=args.archive,
        manifest_path=args.manifest,
        captured_on=args.captured_on,
        database_url=args.database_url,
        work_dir=args.work_dir,
        workers=args.workers,
        history_request_interval=args.history_request_interval,
        max_chars=args.max_chars,
        skip_ddl=args.skip_ddl,
        skip_phase3=args.skip_phase3,
        skip_phase4=args.skip_phase4,
        skip_chunks=args.skip_chunks,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
