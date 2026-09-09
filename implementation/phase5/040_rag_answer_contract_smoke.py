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


HYBRID = _load("legal_kb_phase5_hybrid_answer_smoke", "034_hybrid_retrieval.py")
EMBED = _load("legal_kb_phase5_embedding_answer_smoke", "029_embedding_adapter.py")
RAG = _load("legal_kb_phase5_rag_answer_smoke", "038_rag_answer_contract.py")


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
            raise AssertionError("smoke chunk has no query text")
        query_vector = provider.embed([query_text])[0]
        config = HYBRID.RetrievalConfig(
            chunking_config_sha256=str(chunk_config),
            embedding_profile_id=profile_id,
            per_channel_limit=20,
            max_contexts=5,
            character_budget=3000,
        )
        structural_filter = HYBRID.StructuralFilter(
            tag_name=anchor_tag,
            structural_num=anchor_num,
        )
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT phase53d_temporal_seed")
            cur.execute(
                """UPDATE legal_kb.law_revision
                   SET valid_from=NULL, valid_to_exclusive=NULL
                   WHERE law_id=%s AND law_revision_id<>%s""",
                (law_id, revision_id),
            )
            cur.execute(
                """UPDATE legal_kb.law_revision
                   SET valid_from=%s, valid_to_exclusive=NULL,
                       temporal_resolution_quality='confirmed-api'
                   WHERE law_revision_id=%s""",
                (date(2020, 1, 1), revision_id),
            )
        try:
            retrieval = HYBRID.hybrid_retrieve(
                conn,
                str(law_id),
                date(2026, 1, 1),
                query_text,
                config=config,
                structural_filter=structural_filter,
                query_vector=query_vector,
            )
            evidence = RAG.build_evidence_bundles(conn, retrieval)
        finally:
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT phase53d_temporal_seed")
                cur.execute("RELEASE SAVEPOINT phase53d_temporal_seed")
        if retrieval.status != "ok" or not evidence:
            raise AssertionError("5.3d requires successful retrieval evidence")
        for item in evidence:
            if item.law_revision_id != revision_id or item.document_pk != document_pk:
                raise AssertionError("evidence leaked outside selected revision/document")
            if item.source_xml_sha256.lower() != str(source_sha).lower():
                raise AssertionError("evidence source SHA differs from temporal selection")
            if not item.source_nodes:
                raise AssertionError("evidence contains no Phase 4 source nodes")
            if any(not node.node_id_hex or not node.xml_path for node in item.source_nodes):
                raise AssertionError("source node provenance is incomplete")

        answer_provider = RAG.DeterministicTestAnswerProvider()
        answer = RAG.generate_and_finalize(answer_provider, query_text, evidence)
        if answer.status != "citation-ready" or not answer.citation_ready:
            raise AssertionError("valid answer was not citation-ready")
        if answer.semantic_entailment_verified:
            raise AssertionError("semantic entailment must not be machine-asserted")
        if answer.generated_answer_is_source_truth:
            raise AssertionError("generated answer must not become source truth")
        known_ids = {item.evidence_id for item in evidence}
        if any(eid not in known_ids for claim in answer.claims for eid in claim.evidence_ids):
            raise AssertionError("answer cites an unknown evidence bundle")

        invalid = RAG.AnswerDraft(
            answer_text="不正な回答",
            claims=(RAG.AnswerClaim(
                claim_id="invalid-claim",
                text="根拠のない主張",
                evidence_ids=("0" * 64,),
            ),),
        )
        blocked = RAG.finalize_answer(invalid, evidence)
        if blocked.citation_ready or blocked.status != "blocked":
            raise AssertionError("unknown evidence reference was not blocked")

        return {
            "schema_version": "1.0",
            "runner": "040_rag_answer_contract_smoke.py",
            "status": "passed",
            "contract_version": RAG.CONTRACT_VERSION,
            "law_id": str(law_id),
            "law_revision_id": str(revision_id),
            "document_pk": int(document_pk),
            "evidence_bundle_count": len(evidence),
            "evidence_source_node_count": sum(len(item.source_nodes) for item in evidence),
            "citation_ready": answer.citation_ready,
            "semantic_entailment_verified": answer.semantic_entailment_verified,
            "generated_answer_is_source_truth": answer.generated_answer_is_source_truth,
            "unknown_evidence_reference_blocked": True,
            "phase4_provenance_roundtrip": True,
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
