from __future__ import annotations

from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import sys

PHASE5_DIR = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    path = PHASE5_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HYBRID = _load("legal_kb_phase5_hybrid_smoke_target", "034_hybrid_retrieval.py")
EMBED = _load("legal_kb_phase5_embedding_hybrid_smoke", "029_embedding_adapter.py")


def _one(conn, sql: str, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def run(database_url: str) -> dict:
    import psycopg

    with psycopg.connect(database_url) as conn:
        row = _one(conn, """
            SELECT c.document_pk, c.law_id, c.law_revision_id,
                   c.chunking_config_sha256, c.retrieval_text,
                   c.anchor_tag_name, c.anchor_structural_num, c.source_xml_sha256
            FROM legal_kb.retrieval_chunk c
            ORDER BY c.document_pk, c.start_document_order, c.chunk_id
            LIMIT 1
        """)
        if row is None:
            raise AssertionError("Phase 5.3a retrieval chunk smoke must run first")
        document_pk, law_id, revision_id, chunk_config, retrieval_text, anchor_tag, anchor_num, source_sha = row
        provider = EMBED.DeterministicTestProvider(8)
        profile_id = EMBED.embedding_profile_id(provider.profile)
        embedding_count = _one(
            conn,
            """SELECT count(*) FROM legal_kb.chunk_embedding e
               JOIN legal_kb.retrieval_chunk c ON c.chunk_id=e.chunk_id
               WHERE e.embedding_profile_id=%s AND c.document_pk=%s
                 AND c.chunking_config_sha256=%s""",
            (profile_id, document_pk, chunk_config),
        )[0]
        if int(embedding_count) <= 0:
            raise AssertionError("Phase 5.3b embedding smoke must run first")

        first_line = next((line.strip() for line in str(retrieval_text).splitlines() if line.strip()), "")
        query_text = first_line[: min(12, len(first_line))]
        if not query_text:
            raise AssertionError("smoke chunk has no lexical query text")
        query_vector = provider.embed([query_text])[0]
        structural_filter = HYBRID.StructuralFilter(tag_name=anchor_tag, structural_num=anchor_num)
        config = HYBRID.RetrievalConfig(
            chunking_config_sha256=str(chunk_config),
            embedding_profile_id=profile_id,
            per_channel_limit=20,
            max_contexts=5,
            character_budget=3000,
        )

        with conn.cursor() as cur:
            cur.execute("SAVEPOINT phase53c_temporal_seed")
            cur.execute(
                """UPDATE legal_kb.law_revision
                   SET valid_from=%s, valid_to_exclusive=NULL,
                       temporal_resolution_quality='confirmed-api'
                   WHERE law_revision_id=%s""",
                (date(2020, 1, 1), revision_id),
            )
        try:
            result = HYBRID.hybrid_retrieve(
                conn, str(law_id), date(2026, 1, 1), query_text,
                config=config,
                structural_filter=structural_filter,
                query_vector=query_vector,
            )
        finally:
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT phase53c_temporal_seed")
                cur.execute("RELEASE SAVEPOINT phase53c_temporal_seed")

        if result.status != "ok":
            raise AssertionError(f"hybrid retrieval did not return context: {result.status}")
        if result.resolution.selected_revision_id != revision_id:
            raise AssertionError("hybrid retrieval changed the resolved revision")
        if result.resolution.selected_document_pk != document_pk:
            raise AssertionError("hybrid retrieval changed the selected document")
        counts = dict(result.channel_counts)
        if counts["lexical"] <= 0 or counts["vector"] <= 0:
            raise AssertionError("lexical and vector channels must both produce smoke hits")
        if structural_filter.active() and counts["structural"] <= 0:
            raise AssertionError("active structural channel produced no hits")
        if not result.contexts:
            raise AssertionError("context assembly produced no contexts")
        if structural_filter.active() and not any(len(context.channels) >= 2 for context in result.contexts):
            raise AssertionError("hybrid fusion did not combine any channel evidence")

        for context in result.contexts:
            if context.law_revision_id != revision_id or context.document_pk != document_pk:
                raise AssertionError("context leaked outside selected revision/document")
            if context.source_xml_sha256.lower() != str(source_sha).lower():
                raise AssertionError("context source SHA differs from temporal selection")
            if context.citation_ready:
                raise AssertionError("5.3c derived context must not claim citation readiness")
            if not context.anchor_xml_path or not context.start_xml_path or not context.end_xml_path:
                raise AssertionError("context must retain Phase 4 XML paths")
            if not context.source_document_orders:
                raise AssertionError("context must retain source node orders")

        return {
            "schema_version": "1.0",
            "runner": "036_hybrid_retrieval_smoke.py",
            "status": "passed",
            "retrieval_version": HYBRID.RETRIEVAL_VERSION,
            "retrieval_config_sha256": result.retrieval_config_sha256,
            "law_id": str(law_id),
            "law_revision_id": str(revision_id),
            "document_pk": int(document_pk),
            "chunking_config_sha256": str(chunk_config),
            "embedding_profile_id": profile_id,
            "vector_backend": result.vector_backend,
            "channel_counts": counts,
            "context_count": len(result.contexts),
            "multi_channel_context": any(len(context.channels) >= 2 for context in result.contexts),
            "strict_revision_scope": True,
            "provenance_roundtrip": True,
            "context_citation_ready": False,
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
