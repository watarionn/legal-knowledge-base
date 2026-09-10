from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


linker = _load("phase65_linker_test", "029_cross_source_linker.py")
retrieval = _load("phase65_retrieval_test", "033_external_relation_retrieval.py")

LAW = linker.LawCatalogEntry(
    "405AC0000000088",
    "平成五年法律第八十八号",
    ("行政手続法",),
)
REV = linker.RevisionCatalogEntry(
    "405AC0000000088_20260401_506AC0000000046",
    "405AC0000000088",
    "506AC0000000046",
    "令和六年法律第四十六号",
    "情報通信技術を活用した行政の推進等に関する法律の一部を改正する法律",
)


class CrossSourceLinkageTest(unittest.TestCase):
    def proposals(self, text: str, provider: str = "kokkai-ndl"):
        return linker.build_link_proposals(
            provider_code=provider,
            text_sources=(("fixture", text),),
            laws=(LAW,),
            revisions=(REV,),
        )

    def test_exact_law_id_creates_candidate_signal(self):
        proposals = self.proposals("対象は405AC0000000088です。")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].target_kind, "law")
        self.assertEqual(proposals[0].signals[0].assertion_basis, "identifier-match")

    def test_exact_law_number_creates_candidate_signal(self):
        proposals = self.proposals("平成五年法律第八十八号について審議する。")
        self.assertEqual(proposals[0].target_id, LAW.law_id)
        self.assertEqual(proposals[0].signals[0].signal_kind, "law-number-exact")

    def test_nfkc_and_whitespace_are_normalized_only(self):
        proposals = self.proposals("平成五年 法律 第八十八号")
        self.assertEqual(len(proposals), 1)

    def test_exact_title_is_text_match_not_confirmation(self):
        proposals = self.proposals("行政手続法の運用について")
        self.assertEqual(proposals[0].signals[0].assertion_basis, "text-match")
        self.assertFalse(linker.citation_ready("candidate"))

    def test_partial_title_is_not_matched(self):
        self.assertEqual(self.proposals("行政手続について"), ())

    def test_amendment_number_targets_revision(self):
        proposals = self.proposals("令和六年法律第四十六号の施行状況")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].target_kind, "law_revision")
        self.assertEqual(proposals[0].target_id, REV.law_revision_id)
        self.assertEqual(proposals[0].relation_kind, "amendment-material")

    def test_gazette_has_no_automatic_text_linkage(self):
        self.assertEqual(self.proposals("行政手続法", provider="kanpo-cao"), ())

    def test_ndl_uses_bibliographic_relation_kind(self):
        proposals = self.proposals("行政手続法", provider="ndl-search")
        self.assertEqual(proposals[0].relation_kind, "bibliographic-reference")

    def test_duplicate_signal_is_deduplicated(self):
        proposals = linker.build_link_proposals(
            provider_code="kokkai-ndl",
            text_sources=(("fixture", "行政手続法"), ("fixture", "行政手続法")),
            laws=(LAW,), revisions=(),
        )
        self.assertEqual(len(proposals[0].signals), 1)

    def test_effective_state_policy(self):
        self.assertEqual(linker.effective_relation_state(["candidate"]), "candidate")
        self.assertEqual(linker.effective_relation_state(["candidate", "confirmed"]), "confirmed")
        self.assertEqual(linker.effective_relation_state(["candidate", "rejected"]), "rejected")
        self.assertEqual(linker.effective_relation_state(["confirmed", "rejected"]), "conflicted")

    def test_only_confirmed_is_citation_ready(self):
        self.assertTrue(linker.citation_ready("confirmed"))
        for state in ("candidate", "rejected", "conflicted"):
            self.assertFalse(linker.citation_ready(state))

    def test_retrieval_target_validation(self):
        clause, params = retrieval._target_clause("provision_node", "12:34")
        self.assertIn("target_document_pk", clause)
        self.assertEqual(params, (12, 34))
        with self.assertRaises(ValueError):
            retrieval._target_clause("provision_node", "bad")


if __name__ == "__main__":
    unittest.main()
