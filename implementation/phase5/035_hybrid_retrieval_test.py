from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys
import unittest

PHASE5_DIR = Path(__file__).resolve().parent


def _load():
    path = PHASE5_DIR / "034_hybrid_retrieval.py"
    spec = importlib.util.spec_from_file_location("legal_kb_phase5_hybrid_retrieval_test_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HYBRID = _load()
CONFIG_SHA = "a" * 64
SOURCE_SHA = "b" * 64
TEXT_SHA = "c" * 64


def config(**kwargs):
    values = {"chunking_config_sha256": CONFIG_SHA}
    values.update(kwargs)
    return HYBRID.RetrievalConfig(**values)


def hit(channel, rank, chunk_id, *, order=10, score=1.0):
    return HYBRID.ChannelHit(
        channel=channel, rank=rank, chunk_id=chunk_id,
        law_id="123AC0000000001", law_revision_id="rev-1", document_pk=7,
        anchor_document_order=order, start_document_order=order,
        end_document_order=order, context_prefix="第一条",
        retrieval_text=f"本文-{chunk_id}", source_xml_sha256=SOURCE_SHA,
        retrieval_text_sha256=TEXT_SHA, raw_score=score,
    )
class HybridRetrievalTest(unittest.TestCase):
    def test_chunking_config_is_required(self):
        with self.assertRaisesRegex(ValueError, "chunking_config_sha256"):
            HYBRID.RetrievalConfig().validate()

    def test_config_hash_changes_with_retrieval_inputs(self):
        first = HYBRID.retrieval_config_sha256(config(character_budget=6000))
        second = HYBRID.retrieval_config_sha256(config(character_budget=6001))
        third = HYBRID.retrieval_config_sha256(config(embedding_profile_id="d" * 64))
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)

    def test_cosine_similarity(self):
        self.assertAlmostEqual(HYBRID._cosine_similarity((1.0, 0.0), (1.0, 0.0)), 1.0)
        self.assertAlmostEqual(HYBRID._cosine_similarity((1.0, 0.0), (-1.0, 0.0)), -1.0)
        self.assertAlmostEqual(HYBRID._cosine_similarity((1.0, 0.0), (0.0, 1.0)), 0.0)
        with self.assertRaisesRegex(ValueError, "zero vector"):
            HYBRID._cosine_similarity((0.0, 0.0), (1.0, 0.0))

    def test_rrf_fuses_same_chunk_without_mixing_raw_scores(self):
        fused = HYBRID.fuse_hits([
            hit("lexical", 1, "a", score=0.2),
            hit("vector", 2, "a", score=0.99),
            hit("vector", 1, "b", order=20, score=1.0),
        ], config())
        self.assertEqual(fused[0].chunk_id, "a")
        self.assertEqual(fused[0].channels, ("lexical", "vector"))
        self.assertEqual(dict(fused[0].channel_ranks), {"lexical": 1, "vector": 2})
        self.assertEqual(dict(fused[0].channel_scores), {"lexical": 0.2, "vector": 0.99})

    def test_rrf_tie_break_is_deterministic(self):
        fused = HYBRID.fuse_hits([
            hit("lexical", 1, "b", order=10),
            hit("lexical", 1, "a", order=10),
        ], config())
        self.assertEqual([item.chunk_id for item in fused], ["a", "b"])
    def _resolution(self, status, content_status, *, selected=True):
        return HYBRID.TEMPORAL.TemporalResolution(
            law_id="123AC0000000001", as_of_date=date(2026, 1, 1),
            status=status,
            selected_revision_id="rev-1" if selected else None,
            content_status=content_status,
            selected_document_pk=7 if selected and content_status == "available" else None,
            selected_document_id="doc-1" if selected and content_status == "available" else None,
            source_xml_sha256=SOURCE_SHA if selected and content_status == "available" else None,
            candidates=(), warnings=("TEST_WARNING",),
        )

    def test_ambiguous_temporal_resolution_blocks_all_channels(self):
        original = HYBRID.TEMPORAL.resolve_as_of
        HYBRID.TEMPORAL.resolve_as_of = lambda conn, law_id, as_of: self._resolution(
            "ambiguous", "candidate-dependent", selected=False
        )
        try:
            result = HYBRID.hybrid_retrieve(object(), "123AC0000000001", date(2026, 1, 1), "本文", config=config())
        finally:
            HYBRID.TEMPORAL.resolve_as_of = original
        self.assertEqual(result.status, "blocked-temporal")
        self.assertEqual(result.contexts, ())
        self.assertIn("RETRIEVAL_NOT_RUN", result.warnings)

    def test_missing_content_blocks_all_channels(self):
        original = HYBRID.TEMPORAL.resolve_as_of
        HYBRID.TEMPORAL.resolve_as_of = lambda conn, law_id, as_of: self._resolution(
            "resolved", "missing", selected=True
        )
        try:
            result = HYBRID.hybrid_retrieve(object(), "123AC0000000001", date(2026, 1, 1), "本文", config=config())
        finally:
            HYBRID.TEMPORAL.resolve_as_of = original
        self.assertEqual(result.status, "blocked-content")
        self.assertEqual(dict(result.channel_counts), {"lexical": 0, "structural": 0, "vector": 0})

    def test_scope_guard_rejects_cross_revision_hit(self):
        resolution = self._resolution("resolved", "available")
        leaked = hit("lexical", 1, "x")
        leaked = HYBRID.ChannelHit(**{**leaked.__dict__, "law_revision_id": "other-rev"})
        with self.assertRaisesRegex(AssertionError, "law_revision_id"):
            HYBRID._assert_scope(leaked, resolution)
    def test_context_budget_never_truncates_first_chunk(self):
        base = HYBRID.FusedHit(
            chunk_id="a", fused_score=1.0, channels=("lexical",),
            channel_ranks=(("lexical", 1),), channel_scores=(("lexical", 1.0),),
            law_id="123AC0000000001", law_revision_id="rev-1", document_pk=7,
            anchor_document_order=10, start_document_order=10, end_document_order=10,
            context_prefix="第一条", retrieval_text="あ" * 20,
            source_xml_sha256=SOURCE_SHA, retrieval_text_sha256=TEXT_SHA,
        )
        original = HYBRID._fetch_context_provenance
        HYBRID._fetch_context_provenance = lambda conn, hit: ((10,), "/a", "/a/s", "/a/e")
        try:
            contexts = HYBRID.assemble_contexts(object(), [base], max_contexts=8, character_budget=10)
        finally:
            HYBRID._fetch_context_provenance = original
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].retrieval_text, "あ" * 20)
        self.assertTrue(contexts[0].budget_overflow)
        self.assertFalse(contexts[0].citation_ready)

    def test_query_vector_and_profile_must_be_paired(self):
        with self.assertRaisesRegex(ValueError, "supplied together"):
            HYBRID.hybrid_retrieve(
                object(), "123AC0000000001", date(2026, 1, 1), "本文",
                config=config(embedding_profile_id="d" * 64),
            )


if __name__ == "__main__":
    unittest.main()
