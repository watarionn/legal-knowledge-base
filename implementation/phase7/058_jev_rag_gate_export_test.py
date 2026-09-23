#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
TARGET = HERE / "057_jev_rag_gate_export.py"
spec = importlib.util.spec_from_file_location("jev_rag_gate_export", TARGET)
assert spec is not None and spec.loader is not None
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


def response():
    return {
        "question": "第90条は何を定めていますか",
        "effective_as_of_date": "2026-09-23",
        "status": "evidence-only",
        "law_resolution": {
            "status": "resolved",
            "selected_law_id": "L1",
            "selected_title": "テスト法",
        },
        "temporal_resolution": {"status": "resolved"},
        "retrieval": {
            "status": "ok",
            "query_text": "",
            "structural_filter": {"tag_name": "Article", "structural_num": "90"},
            "context_count": 1,
        },
        "evidence": [{
            "evidence_id": "E1",
            "retrieval_rank": 1,
            "chunk_id": "C1",
            "law_id": "L1",
            "law_revision_id": "R1",
            "document_pk": 1,
            "source_xml_sha256": "a" * 64,
            "display_path": "/Law/Article[90]",
            "source_nodes": [{
                "node_id_hex": "01",
                "xml_path": "/Law/Article[90]/Paragraph/Sentence",
                "tag_name": "Sentence",
                "structural_num": None,
                "display_label": "第九十条",
                "text_original": "本文",
            }],
        }],
        "answer": {
            "status": "answered",
            "answer_text": "これはJevへ出してはいけない",
            "claims": [{"text": "秘密の生成内容"}],
        },
    }


class JevRagGateExportTests(unittest.TestCase):
    def test_contract_is_shadow_only(self):
        out = MODULE.build_shadow_export(response())
        self.assertEqual("legal-kb-jev-rag-gate-v1", out["contract"])
        self.assertEqual("shadow_only", out["mode"])
        self.assertTrue(all(value is False for value in out["authority"].values()))

    def test_generated_answer_is_not_exported(self):
        out = MODULE.build_shadow_export(response())
        self.assertNotIn("answer", out)
        self.assertTrue(out["answer_content_exported"] is False)
        rendered = repr(out)
        self.assertNotIn("Jevへ出してはいけない", rendered)
        self.assertNotIn("秘密の生成内容", rendered)

    def test_evidence_identity_and_text_are_preserved(self):
        out = MODULE.build_shadow_export(response())
        self.assertEqual(1, len(out["evidence"]))
        item = out["evidence"][0]
        self.assertEqual("E1", item["evidence_id"])
        self.assertEqual("R1", item["law_revision_id"])
        self.assertEqual("Sentence", item["source_nodes"][0]["tag_name"])
        self.assertEqual("本文", item["source_nodes"][0]["text_original"])

    def test_export_is_bounded(self):
        src = response()
        src["evidence"] = src["evidence"] * 20
        out = MODULE.build_shadow_export(src)
        self.assertEqual(MODULE.MAX_EVIDENCE, len(out["evidence"]))

    def test_non_list_evidence_rejected(self):
        src = response()
        src["evidence"] = {}
        with self.assertRaises(ValueError):
            MODULE.build_shadow_export(src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
