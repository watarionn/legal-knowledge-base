from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

PHASE5_DIR = Path(__file__).resolve().parent


def _load():
    path = PHASE5_DIR / "024_retrieval_chunk_builder.py"
    spec = importlib.util.spec_from_file_location("legal_kb_phase5_retrieval_chunk_builder_smoke_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BUILDER = _load()


def run(database_url: str) -> dict:
    import psycopg

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT min(document_pk) FROM legal_kb.law_document")
            document_pk = cur.fetchone()[0]
        if document_pk is None:
            raise AssertionError("Phase 4 smoke fixture is required")

        first = BUILDER.rebuild_document(conn, int(document_pk), max_chars=400)
        if not first:
            raise AssertionError("retrieval chunk builder produced zero chunks")
        first_ids = [chunk.chunk_id for chunk in first]

        second = BUILDER.rebuild_document(conn, int(document_pk), max_chars=400)
        second_ids = [chunk.chunk_id for chunk in second]
        if first_ids != second_ids:
            raise AssertionError("chunk rebuild is not deterministic")

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM legal_kb.retrieval_chunk c
                JOIN legal_kb.law_document d ON d.document_pk=c.document_pk
                WHERE c.document_pk=%s
                  AND c.source_xml_sha256=d.source_xml_sha256
                  AND c.soft_max_chars=400
                  AND c.chunking_config_sha256 ~ '^[0-9a-f]{64}$'
                  AND c.start_document_order<=c.end_document_order
                  AND cardinality(c.source_document_orders)=c.source_unit_count
                  AND c.source_document_orders[1]=c.start_document_order
                  AND c.source_document_orders[array_length(c.source_document_orders,1)]=c.end_document_order
                """,
                (document_pk,),
            )
            validated_count = int(cur.fetchone()[0])
        if validated_count != len(second):
            raise AssertionError("retrieval chunk provenance checks failed")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM legal_kb.retrieval_chunk_provenance(%s)",
                (second[0].chunk_id,),
            )
            provenance = cur.fetchone()
        if provenance is None:
            raise AssertionError("retrieval_chunk_provenance returned no row")
        if provenance[6] is None or provenance[8] is None or provenance[10] is None:
            raise AssertionError("provenance XML paths must be reconstructable")

        return {
            "schema_version": "1.0",
            "runner": "026_retrieval_chunk_smoke.py",
            "status": "passed",
            "chunking_version": BUILDER.CHUNKING_VERSION,
            "chunking_config_sha256": second[0].chunking_config_sha256,
            "soft_max_chars": second[0].soft_max_chars,
            "document_pk": int(document_pk),
            "chunk_count": len(second),
            "oversize_chunk_count": sum(1 for chunk in second if chunk.is_oversize),
            "deterministic_rebuild": True,
            "provenance_roundtrip": True,
            "database_url_recorded": False,
        }


def main() -> None:
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("LEGAL_KB_DSN")
    if not database_url:
        raise SystemExit("DATABASE_URL or LEGAL_KB_DSN is required")
    result = run(database_url)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
