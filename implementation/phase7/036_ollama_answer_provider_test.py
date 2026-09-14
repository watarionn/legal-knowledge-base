from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

HERE = Path(__file__).resolve().parent
PATH = HERE / "035_ollama_answer_provider.py"
spec = importlib.util.spec_from_file_location("phase76_ollama_provider_tested", PATH)
assert spec and spec.loader
PROVIDER = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = PROVIDER
spec.loader.exec_module(PROVIDER)


def evidence(evidence_id: str = "evidence-1"):
    node = SimpleNamespace(
        xml_path="/Law/LawBody/MainProvision/Article[1]/Paragraph[1]/Sentence[1]",
        tag_name="Sentence",
        text_original="公の秩序又は善良の風俗に反する法律行為は、無効とする。",
    )
    return SimpleNamespace(
        evidence_id=evidence_id,
        law_revision_id="revision-1",
        source_xml_sha256="a" * 64,
        source_nodes=(node,),
    )


def heading_evidence(evidence_id: str = "heading-1"):
    node = SimpleNamespace(
        xml_path="/Law/LawBody/MainProvision/Article[1]/ArticleTitle[1]",
        tag_name="ArticleTitle",
        text_original="第九十条",
    )
    return SimpleNamespace(
        evidence_id=evidence_id,
        law_revision_id="revision-1",
        source_xml_sha256="a" * 64,
        source_nodes=(node,),
    )


class ConfigTest(unittest.TestCase):
    def test_loopback_url_is_allowed(self):
        config = PROVIDER.OllamaAnswerProviderConfig(
            base_url="http://127.0.0.1:11434", model="gemma3:4b", timeout_seconds=30
        )
        config.validate()

    def test_external_url_is_rejected(self):
        config = PROVIDER.OllamaAnswerProviderConfig(
            base_url="https://example.com", model="gemma3:4b", timeout_seconds=30
        )
        with self.assertRaisesRegex(ValueError, "loopback"):
            config.validate()


class ProviderTest(unittest.TestCase):
    def test_select_generation_evidence_rejects_heading_only(self):
        provider = PROVIDER.OllamaAnswerProvider(
            transport=lambda url, payload, timeout: {"message": {"content": "{}"}}
        )
        selected = provider.select_generation_evidence(
            [heading_evidence(), evidence()]
        )
        self.assertEqual([item.evidence_id for item in selected], ["evidence-1"])

    def test_heading_only_fails_before_transport(self):
        called = []
        provider = PROVIDER.OllamaAnswerProvider(
            transport=lambda url, payload, timeout: called.append(True) or {}
        )
        with self.assertRaises(PROVIDER.NoSubstantiveEvidenceError):
            provider.generate("質問", [heading_evidence()])
        self.assertEqual(called, [])

    def test_generate_is_evidence_bound(self):
        captured = {}

        def transport(url, payload, timeout):
            captured["url"] = url
            captured["payload"] = payload
            captured["timeout"] = timeout
            content = {
                "claims": [
                    {
                        "text": "この条文は、公序良俗に反する法律行為を無効と定めています。",
                        "evidence_ids": ["E1"],
                    }
                ]
            }
            return {"message": {"content": json.dumps(content, ensure_ascii=False)}}

        provider = PROVIDER.OllamaAnswerProvider(
            PROVIDER.OllamaAnswerProviderConfig(timeout_seconds=12),
            transport=transport,
        )
        draft = provider.generate("民法第90条を簡単に説明して", [evidence()])
        self.assertEqual(len(draft.claims), 1)
        self.assertEqual(draft.claims[0].evidence_ids, ("evidence-1",))
        self.assertEqual(draft.answer_text, draft.claims[0].text)
        self.assertEqual(captured["url"], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(captured["timeout"], 12)
        serialized = json.dumps(captured["payload"], ensure_ascii=False)
        self.assertIn("公の秩序又は善良の風俗", serialized)
        self.assertIn("EVIDENCE_ID: E1", serialized)
        self.assertNotIn("EVIDENCE_ID: evidence-1", serialized)
        self.assertIsInstance(captured["payload"]["format"], dict)
        enum_values = captured["payload"]["format"]["properties"]["claims"]["items"]["properties"]["evidence_ids"]["items"]["enum"]
        self.assertEqual(enum_values, ["E1"])

    def test_unknown_evidence_id_fails_closed(self):
        def transport(url, payload, timeout):
            content = {"claims": [{"text": "推測です。", "evidence_ids": ["E9"]}]}
            return {"message": {"content": json.dumps(content, ensure_ascii=False)}}

        provider = PROVIDER.OllamaAnswerProvider(transport=transport)
        with self.assertRaisesRegex(PROVIDER.OllamaAnswerProviderError, "unknown evidence alias"):
            provider.generate("質問", [evidence()])

    def test_non_json_response_fails_closed(self):
        provider = PROVIDER.OllamaAnswerProvider(
            transport=lambda url, payload, timeout: {
                "message": {"content": "法令上はこうです。"}
            }
        )
        with self.assertRaisesRegex(PROVIDER.OllamaAnswerProviderError, "valid JSON"):
            provider.generate("質問", [evidence()])

    def test_multiple_claims_synthesize_answer_text(self):
        def transport(url, payload, timeout):
            content = {
                "claims": [
                    {"text": "主張A", "evidence_ids": ["E1"]},
                    {"text": "主張B", "evidence_ids": ["E1"]},
                ]
            }
            return {"message": {"content": json.dumps(content, ensure_ascii=False)}}

        provider = PROVIDER.OllamaAnswerProvider(transport=transport)
        draft = provider.generate("質問", [evidence()])
        self.assertEqual(draft.answer_text, "主張A\n主張B")
        self.assertEqual([claim.claim_id for claim in draft.claims], ["claim-1", "claim-2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
