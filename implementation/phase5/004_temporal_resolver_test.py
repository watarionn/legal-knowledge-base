from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys
import unittest

PHASE5_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "phase5_temporal_resolver", PHASE5_DIR / "003_temporal_resolver.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

LAW_ID = "900AC0000000001"


def row(
    revision_id: str,
    *,
    quality: str | None = "confirmed-api",
    documents: int = 1,
    document_pk: int | None = 1,
    document_id: str | None = "a" * 64,
    source_xml_sha256: str | None = "b" * 64,
):
    return {
        "law_revision_id": revision_id,
        "valid_from": date(2020, 1, 1),
        "valid_to_exclusive": None,
        "temporal_resolution_quality": quality,
        "revision_sequence": 1,
        "law_title": "テスト法",
        "succeeded_document_count": documents,
        "document_pk": document_pk if documents == 1 else None,
        "document_id": document_id if documents == 1 else None,
        "source_xml_sha256": source_xml_sha256 if documents == 1 else None,
    }


class TemporalResolverTest(unittest.TestCase):
    def test_single_confirmed_candidate_resolves(self):
        revision_id = f"{LAW_ID}_20200101_000000000000000"
        result = MODULE.classify_candidates(
            LAW_ID, date(2020, 6, 1), [row(revision_id)]
        )
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.selected_revision_id, revision_id)
        self.assertEqual(result.content_status, "available")
        self.assertEqual(result.selected_document_pk, 1)
        self.assertEqual(result.warnings, ())

    def test_multiple_candidates_are_ambiguous_and_not_selected(self):
        rows = [
            row(f"{LAW_ID}_20200101_000000000000001"),
            row(f"{LAW_ID}_20200101_000000000000002"),
        ]
        result = MODULE.classify_candidates(LAW_ID, date(2020, 6, 1), rows)
        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.selected_revision_id)
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.content_status, "candidate-dependent")

    def test_single_ambiguous_quality_is_unresolved(self):
        revision_id = f"{LAW_ID}_20200101_000000000000000"
        result = MODULE.classify_candidates(
            LAW_ID,
            date(2020, 6, 1),
            [row(revision_id, quality="ambiguous")],
        )
        self.assertEqual(result.status, "unresolved")
        self.assertIsNone(result.selected_revision_id)
        self.assertIn("TEMPORAL_QUALITY_NOT_STRICT", result.warnings)

    def test_no_candidate_does_not_fallback(self):
        result = MODULE.classify_candidates(LAW_ID, date(1900, 1, 1), [])
        self.assertEqual(result.status, "not-found")
        self.assertIsNone(result.selected_revision_id)
        self.assertEqual(result.content_status, "none")

    def test_resolved_revision_can_have_missing_content_without_revision_fallback(self):
        revision_id = f"{LAW_ID}_20200101_000000000000000"
        result = MODULE.classify_candidates(
            LAW_ID,
            date(2020, 6, 1),
            [
                row(
                    revision_id,
                    documents=0,
                    document_pk=None,
                    document_id=None,
                    source_xml_sha256=None,
                )
            ],
        )
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.selected_revision_id, revision_id)
        self.assertEqual(result.content_status, "missing")
        self.assertIsNone(result.selected_document_id)
        self.assertIn("CONTENT_NOT_AVAILABLE", result.warnings)

    def test_multiple_documents_do_not_choose_one(self):
        revision_id = f"{LAW_ID}_20200101_000000000000000"
        result = MODULE.classify_candidates(
            LAW_ID,
            date(2020, 6, 1),
            [row(revision_id, documents=2)],
        )
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.content_status, "multiple")
        self.assertIsNone(result.selected_document_id)
        self.assertIn("MULTIPLE_SUCCEEDED_DOCUMENTS", result.warnings)

    def test_single_document_requires_provenance(self):
        revision_id = f"{LAW_ID}_20200101_000000000000000"
        with self.assertRaises(ValueError):
            MODULE.classify_candidates(
                LAW_ID,
                date(2020, 6, 1),
                [row(revision_id, documents=1, document_pk=None)],
            )

    def test_invalid_law_id_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.classify_candidates("bad", date(2020, 1, 1), [])


if __name__ == "__main__":
    unittest.main()
