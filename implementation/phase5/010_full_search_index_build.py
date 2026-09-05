from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("phase5_search_builder", HERE / "008_search_unit_builder.py")
builder = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = builder
assert spec.loader is not None
spec.loader.exec_module(builder)


def _psycopg():
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit("psycopg 3 is required") from exc
    return psycopg, Jsonb


def _rows(cur) -> list[dict[str, Any]]:
    names = [c.name for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _document_metadata(conn, *, limit: int | None = None, start_document_pk: int | None = None):
    sql = """
    SELECT d.document_pk, d.document_id, d.law_revision_id, d.source_xml_sha256,
           r.law_id, r.law_title
    FROM legal_kb.law_document d
    JOIN legal_kb.law_revision r ON r.law_revision_id = d.law_revision_id
    WHERE d.parse_status IN ('succeeded', 'succeeded-with-warnings')
      AND (%s::bigint IS NULL OR d.document_pk >= %s::bigint)
    ORDER BY d.document_pk
    """
    if limit is not None:
        sql += " LIMIT %s"
        params = (start_document_pk, start_document_pk, limit)
    else:
        params = (start_document_pk, start_document_pk)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return _rows(cur)


def _fetch_nodes(conn, document_pk: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT document_order, node_id, parent_document_order, node_kind, ordinal,
                   path_index, depth, tag_name, structural_num, display_label,
                   text_original, mixed_content_jsonb
            FROM legal_kb.provision_node
            WHERE document_pk = %s
            ORDER BY document_order
            """,
            (document_pk,),
        )
        return _rows(cur)


def _resume_complete(conn, document_pk: int, build_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM legal_kb.search_document_state
            WHERE document_pk = %s AND build_id = %s
              AND index_version = %s AND status = 'succeeded'
            """,
            (document_pk, build_id, builder.INDEX_VERSION),
        )
        return cur.fetchone() is not None


def _ensure_build(conn, build_id: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.search_index_build(
                build_id, index_version, builder_version, normalization_version, status
            ) VALUES (%s, %s, %s, %s, 'running')
            ON CONFLICT (build_id) DO UPDATE SET
                index_version = EXCLUDED.index_version,
                builder_version = EXCLUDED.builder_version,
                normalization_version = EXCLUDED.normalization_version,
                status = 'running', completed_at = NULL
            """,
            (build_id, builder.INDEX_VERSION, builder.BUILDER_VERSION, builder.NORMALIZATION_VERSION),
        )
    conn.commit()


def _write_document(conn, meta, result, build_id: str, Jsonb):
    document_pk = int(meta["document_pk"])
    with conn.cursor() as cur:
        cur.execute("DELETE FROM legal_kb.search_unit WHERE document_pk = %s", (document_pk,))
        if result.units:
            with cur.copy(
                """COPY legal_kb.search_unit(
                    search_unit_id, build_id, law_id, law_revision_id, document_pk,
                    source_document_order, anchor_document_order, unit_kind,
                    anchor_tag_name, anchor_structural_num, anchor_display_label,
                    hierarchy_jsonb, search_text_cache, search_text_normalized,
                    context_text_cache, context_text_normalized, source_xml_sha256
                ) FROM STDIN"""
            ) as cp:
                for u in result.units:
                    cp.write_row((
                        u.search_unit_id, build_id, u.law_id, u.law_revision_id, u.document_pk,
                        u.source_document_order, u.anchor_document_order, u.unit_kind,
                        u.anchor_tag_name, u.anchor_structural_num, u.anchor_display_label,
                        Jsonb(u.hierarchy_jsonb), u.search_text_cache, u.search_text_normalized,
                        u.context_text_cache, u.context_text_normalized, u.source_xml_sha256,
                    ))
        cur.execute(
            """
            INSERT INTO legal_kb.search_document_state(
                document_pk, build_id, index_version, status, search_unit_count,
                searchable_sentence_count, covered_sentence_count, uncovered_sentence_count,
                detail_jsonb, built_at
            ) VALUES (%s,%s,%s,'succeeded',%s,%s,%s,%s,%s,now())
            ON CONFLICT (document_pk) DO UPDATE SET
                build_id=EXCLUDED.build_id, index_version=EXCLUDED.index_version,
                status=EXCLUDED.status, search_unit_count=EXCLUDED.search_unit_count,
                searchable_sentence_count=EXCLUDED.searchable_sentence_count,
                covered_sentence_count=EXCLUDED.covered_sentence_count,
                uncovered_sentence_count=EXCLUDED.uncovered_sentence_count,
                detail_jsonb=EXCLUDED.detail_jsonb, built_at=now()
            """,
            (document_pk, build_id, builder.INDEX_VERSION, len(result.units),
             result.searchable_sentence_count, result.covered_sentence_count,
             result.uncovered_sentence_count,
             Jsonb({"uncovered_sentence_orders": list(result.uncovered_sentence_orders[:100])})),
        )
    conn.commit()


def _finalize(conn, build_id: str, Jsonb):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)::int, coalesce(sum(search_unit_count),0)::bigint,
                   coalesce(sum(searchable_sentence_count),0)::bigint,
                   coalesce(sum(uncovered_sentence_count),0)::bigint
            FROM legal_kb.search_document_state
            WHERE build_id=%s AND status='succeeded'
            """,
            (build_id,),
        )
        document_count, unit_count, sentence_count, uncovered = cur.fetchone()
        cur.execute(
            "SELECT pg_total_relation_size('legal_kb.search_unit')::bigint, "
            "pg_total_relation_size('legal_kb.search_document_state')::bigint"
        )
        search_unit_bytes, state_bytes = cur.fetchone()
        result = {
            "schema_version": "1.0",
            "evidence_type": "phase5-full-search-index-build",
            "build_id": build_id,
            "index_version": builder.INDEX_VERSION,
            "builder_version": builder.BUILDER_VERSION,
            "normalization_version": builder.NORMALIZATION_VERSION,
            "document_count": int(document_count),
            "search_unit_count": int(unit_count),
            "searchable_sentence_count": int(sentence_count),
            "uncovered_sentence_count": int(uncovered),
            "search_unit_relation_bytes": int(search_unit_bytes),
            "search_document_state_relation_bytes": int(state_bytes),
            "status": "passed" if uncovered == 0 else "failed",
        }
        cur.execute(
            """
            UPDATE legal_kb.search_index_build
            SET status=%s, completed_at=now(), document_count=%s,
                search_unit_count=%s, searchable_sentence_count=%s,
                uncovered_sentence_count=%s, detail_jsonb=%s
            WHERE build_id=%s
            """,
            ("succeeded" if uncovered == 0 else "failed", document_count, unit_count,
             sentence_count, uncovered, Jsonb({"search_unit_relation_bytes": int(search_unit_bytes)}), build_id),
        )
    conn.commit()
    return result


def run(conn, *, build_id: str, resume: bool, limit: int | None,
        start_document_pk: int | None, progress_every: int = 100):
    _, Jsonb = _psycopg()
    _ensure_build(conn, build_id)
    docs = _document_metadata(conn, limit=limit, start_document_pk=start_document_pk)
    processed = 0
    skipped = 0
    for meta in docs:
        document_pk = int(meta["document_pk"])
        if resume and _resume_complete(conn, document_pk, build_id):
            skipped += 1
            continue
        result = builder.build_search_units(
            _fetch_nodes(conn, document_pk),
            law_id=meta["law_id"], law_revision_id=meta["law_revision_id"],
            document_pk=document_pk, document_id=meta["document_id"],
            source_xml_sha256=meta["source_xml_sha256"], law_title=meta.get("law_title"),
        )
        if result.uncovered_sentence_count:
            conn.rollback()
            raise RuntimeError(
                f"searchable Sentence coverage failure document_pk={document_pk}: "
                f"{result.uncovered_sentence_orders[:20]}"
            )
        _write_document(conn, meta, result, build_id, Jsonb)
        processed += 1
        if progress_every and processed % progress_every == 0:
            print(json.dumps({"processed": processed, "skipped": skipped,
                              "last_document_pk": document_pk,
                              "last_units": len(result.units)}, ensure_ascii=False), flush=True)
    final = _finalize(conn, build_id, Jsonb)
    final["processed_this_run"] = processed
    final["skipped_this_run"] = skipped
    return final


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    p.add_argument("--build-id", required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--start-document-pk", type=int)
    p.add_argument("--progress-every", type=int, default=100)
    p.add_argument("--result")
    args = p.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    psycopg, _ = _psycopg()
    with psycopg.connect(args.database_url) as conn:
        result = run(conn, build_id=args.build_id, resume=args.resume, limit=args.limit,
                     start_document_pk=args.start_document_pk, progress_every=args.progress_every)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.result:
        Path(args.result).write_text(text, encoding="utf-8")
    print(text, end="")
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
