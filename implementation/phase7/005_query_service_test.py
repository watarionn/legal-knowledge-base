from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    path = HERE / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SERVICE = _load("legal_kb_phase7_query_service_test_target", "002_query_service.py")


@dataclass(frozen=True)
class Candidate:
    law_id: str
    matched_text: str | None


@dataclass(frozen=True)
class Resolution:
    selected_law_id: str | None
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True)
class Node:
    document_order: int
    node_id_hex: str
    xml_path: str
    tag_name: str | None
    structural_num: str | None
    display_label: str | None
    text_original: str | None


@dataclass(frozen=True)
class Bundle:
    evidence_id: str
    retrieval_rank: int
    chunk_id: str
    law_id: str
    law_revision_id: str
    document_pk: int
    source_xml_sha256: str
    source_nodes: tuple[Node, ...]


class QueryPlannerTest(unittest.TestCase):
    def test_retrieval_text_removes_law_date_and_boilerplate(self):
        resolution = Resolution(
            selected_law_id="324AC0000000100",
            candidates=(Candidate("324AC0000000100", "建設業法"),),
        )
        text = SERVICE.plan_retrieval_text(
            "2024年4月1日時点の建設業法で請負契約に関係する規定を教えて",
            resolution,
        )
        self.assertEqual(text, "請負契約")

    def test_confirmation_intent_does_not_outweigh_subject(self):
        resolution = Resolution(
            selected_law_id="322AC0000000049",
            candidates=(Candidate("322AC0000000049", "労働基準法"),),
        )
        text = SERVICE.plan_retrieval_text(
            "労働基準法で労働時間に関係する規定を確認したい",
            resolution,
        )
        self.assertEqual(text, "労働時間")

    def test_contract_subject_survives_confirmation_intent(self):
        resolution = Resolution(
            selected_law_id="324AC0000000100",
            candidates=(Candidate("324AC0000000100", "建設業法"),),
        )
        text = SERVICE.plan_retrieval_text(
            "建設業法で請負契約に関係する規定を確認したい",
            resolution,
        )
        self.assertEqual(text, "請負契約")

    def test_fullwidth_article_number_is_normalized(self):
        value = SERVICE.structural_filter_from_question("民法の第９０条を確認したい")
        self.assertEqual(value["tag_name"], "Article")
        self.assertEqual(value["structural_num"], "90")

    def test_bad_chunking_sha_is_rejected(self):
        with self.assertRaisesRegex(SERVICE.Phase7ConfigurationError, "SHA-256"):
            SERVICE.QueryServiceConfig(chunking_config_sha256="bad").validate()


class EvidenceProjectionTest(unittest.TestCase):
    def test_projection_keeps_source_truth_fields(self):
        sha = "a" * 64
        bundle = Bundle(
            evidence_id="evidence-1",
            retrieval_rank=1,
            chunk_id="chunk-1",
            law_id="129AC0000000089",
            law_revision_id="129AC0000000089_20260401_000000000000000",
            document_pk=10,
            source_xml_sha256=sha,
            source_nodes=(
                Node(
                    document_order=42,
                    node_id_hex="b" * 64,
                    xml_path="/Law/LawBody/MainProvision/Article[1]",
                    tag_name="Article",
                    structural_num="1",
                    display_label="第一条",
                    text_original="これは法令原文です。",
                ),
            ),
        )
        projected = SERVICE.evidence_to_api(bundle)
        self.assertEqual(projected["citation_truth"], "phase3-phase4")
        self.assertEqual(projected["source_xml_sha256"], sha)
        self.assertEqual(projected["source_xml_sha256_short"], "a" * 12)
        self.assertEqual(projected["quote"], "これは法令原文です。")
        self.assertEqual(
            projected["display_path"],
            "/Law/LawBody/MainProvision/Article[1]",
        )


if __name__ == "__main__":
    unittest.main()
