from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

PHASE5_DIR = Path(__file__).resolve().parent
path = PHASE5_DIR / "038_rag_answer_contract.py"
spec = importlib.util.spec_from_file_location("legal_kb_phase5_rag_answer_test_target", path)
assert spec is not None and spec.loader is not None
RAG = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = RAG
spec.loader.exec_module(RAG)


def evidence(evidence_id: str = "e1"):
    node = RAG.SourceNodeEvidence(
        document_order=1,
        node_id_hex="a" * 64,
        xml_path="/Law[1]",
        tag_name="Law",
        structural_num=None,
        display_label=None,
        text_original="原文",
    )
    return RAG.EvidenceBundle(
        evidence_id=evidence_id,
        retrieval_rank=1,
        chunk_id="chunk-1",
        law_id="123456789012345",
        law_revision_id="123456789012345_20200101_000000000000000",
        document_pk=1,
        source_xml_sha256="b" * 64,
        source_nodes=(node,),
    )


def valid_draft(evidence_id: str = "e1"):
    return RAG.AnswerDraft(
        answer_text="回答",
        claims=(RAG.AnswerClaim(
            claim_id="claim-1",
            text="主張",
            evidence_ids=(evidence_id,),
        ),),
    )


class RagAnswerContractTest(unittest.TestCase):
    def test_evidence_id_is_deterministic(self):
        args = ("rev", "c" * 64, "chunk", ["d" * 64, "e" * 64])
        self.assertEqual(RAG._evidence_id(*args), RAG._evidence_id(*args))

    def test_valid_draft_is_citation_ready(self):
        result = RAG.finalize_answer(valid_draft(), (evidence(),))
        self.assertEqual(result.status, "citation-ready")
        self.assertTrue(result.citation_ready)
        self.assertFalse(result.semantic_entailment_verified)
        self.assertFalse(result.generated_answer_is_source_truth)

    def test_unknown_evidence_blocks_answer(self):
        result = RAG.finalize_answer(valid_draft("missing"), (evidence(),))
        self.assertEqual(result.status, "blocked")
        self.assertFalse(result.citation_ready)
        self.assertTrue(any(x.startswith("UNKNOWN_EVIDENCE_ID") for x in result.warnings))

    def test_claim_without_evidence_is_blocked(self):
        draft = RAG.AnswerDraft(
            answer_text="回答",
            claims=(RAG.AnswerClaim("claim-1", "主張", ()),),
        )
        result = RAG.finalize_answer(draft, (evidence(),))
        self.assertIn("CLAIM_WITHOUT_EVIDENCE:claim-1", result.warnings)

    def test_duplicate_claim_id_is_blocked(self):
        claim = RAG.AnswerClaim("same", "主張", ("e1",))
        draft = RAG.AnswerDraft("回答", (claim, claim))
        result = RAG.finalize_answer(draft, (evidence(),))
        self.assertIn("DUPLICATE_CLAIM_ID:same", result.warnings)

    def test_empty_answer_and_no_claims_are_blocked(self):
        result = RAG.finalize_answer(RAG.AnswerDraft("  ", ()), (evidence(),))
        self.assertIn("ANSWER_TEXT_EMPTY", result.warnings)
        self.assertIn("NO_CLAIMS", result.warnings)

    def test_duplicate_evidence_reference_is_blocked(self):
        draft = RAG.AnswerDraft(
            "回答",
            (RAG.AnswerClaim("claim-1", "主張", ("e1", "e1")),),
        )
        result = RAG.finalize_answer(draft, (evidence(),))
        self.assertIn("DUPLICATE_EVIDENCE_REFERENCE:claim-1", result.warnings)

    def test_provider_metadata_rejects_blank_model(self):
        metadata = RAG.ProviderMetadata("provider", " ", "1")
        with self.assertRaises(ValueError):
            metadata.validate()

    def test_deterministic_provider_references_existing_evidence(self):
        provider = RAG.DeterministicTestAnswerProvider()
        result = RAG.generate_and_finalize(provider, "質問", (evidence(),))
        self.assertTrue(result.citation_ready)
        self.assertEqual(result.claims[0].evidence_ids, ("e1",))
        self.assertEqual(result.provider.provider, "deterministic-test")


if __name__ == "__main__":
    unittest.main()
