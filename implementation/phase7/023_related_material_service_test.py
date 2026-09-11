from datetime import date
import importlib.util
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "022_related_material_service.py"
spec = importlib.util.spec_from_file_location("phase7_related_material_tested", MODULE_PATH)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MODULE
spec.loader.exec_module(MODULE)


def resolution(status="resolved", revision_id="rev-1"):
    return SimpleNamespace(
        status=status,
        selected_revision_id=revision_id if status == "resolved" else None,
        to_dict=lambda: {
            "status": status,
            "selected_revision_id": revision_id if status == "resolved" else None,
        },
    )


def envelope(
    relation_id,
    *,
    document_id="doc-1",
    family="diet-minutes",
    state="confirmed",
    citation_ready=True,
    target_kind="law",
):
    return SimpleNamespace(
        source_relation_id=relation_id,
        external_document_id=document_id,
        provider_code="provider-a",
        source_family=family,
        provider_document_id=f"provider-{document_id}",
        document_kind="meeting",
        issued_on=date(2026, 1, 2),
        title="関連資料",
        canonical_url="https://example.test/material",
        target_kind=target_kind,
        relation_kind="mentions",
        effective_state=state,
        citation_ready=citation_ready,
        snapshot_id="snap-1",
        source_file_id="file-1",
        source_file_sha256="a" * 64,
    )


class BuildResponseTest(unittest.TestCase):
    def test_same_document_relations_are_grouped(self):
        data = MODULE.build_material_response(
            "129AC0000000089",
            date(2026, 9, 11),
            resolution(),
            [
                ("law", "129AC0000000089", (envelope("r1"),)),
                ("law_revision", "rev-1", (
                    envelope("r2", target_kind="law_revision"),
                )),
            ],
            include_nonconfirmed=False,
        )
        self.assertEqual(data["material_count"], 1)
        self.assertEqual(data["relation_count"], 2)
        self.assertEqual(len(data["materials"][0]["relations"]), 2)
        self.assertTrue(data["materials"][0]["citation_ready"])

    def test_candidate_remains_non_citation_ready(self):
        data = MODULE.build_material_response(
            "129AC0000000089",
            date(2026, 9, 11),
            resolution(),
            [("law", "129AC0000000089", (
                envelope("r1", state="candidate", citation_ready=False),
            ))],
            include_nonconfirmed=True,
        )
        self.assertFalse(data["materials"][0]["citation_ready"])
        self.assertEqual(data["state_counts"], {"candidate": 1})


class RetrievalPolicyTest(unittest.TestCase):
    def test_ambiguous_temporal_does_not_fetch_revision_scope(self):
        original_exists = MODULE._law_exists
        original_resolve = MODULE.TEMPORAL.resolve_as_of
        original_collect = MODULE._collect_target
        calls = []
        try:
            MODULE._law_exists = lambda conn, law_id: True
            MODULE.TEMPORAL.resolve_as_of = lambda conn, law_id, as_of: resolution("ambiguous")
            MODULE._collect_target = lambda conn, **kwargs: calls.append(kwargs) or ()
            data = MODULE.get_related_materials(
                object(), "129AC0000000089", as_of_date=date(2023, 4, 1)
            )
        finally:
            MODULE._law_exists = original_exists
            MODULE.TEMPORAL.resolve_as_of = original_resolve
            MODULE._collect_target = original_collect
        self.assertFalse(data["revision_scope_available"])
        self.assertEqual([call["target_kind"] for call in calls], ["law"])

    def test_resolved_temporal_fetches_law_and_revision_scopes(self):
        original_exists = MODULE._law_exists
        original_resolve = MODULE.TEMPORAL.resolve_as_of
        original_collect = MODULE._collect_target
        calls = []
        try:
            MODULE._law_exists = lambda conn, law_id: True
            MODULE.TEMPORAL.resolve_as_of = lambda conn, law_id, as_of: resolution()
            MODULE._collect_target = lambda conn, **kwargs: calls.append(kwargs) or ()
            data = MODULE.get_related_materials(
                object(), "129AC0000000089", as_of_date=date(2026, 9, 11)
            )
        finally:
            MODULE._law_exists = original_exists
            MODULE.TEMPORAL.resolve_as_of = original_resolve
            MODULE._collect_target = original_collect
        self.assertTrue(data["revision_scope_available"])
        self.assertEqual(
            [call["target_kind"] for call in calls],
            ["law", "law_revision"],
        )
        self.assertEqual(calls[1]["target_id"], "rev-1")

    def test_family_count_counts_materials_not_relations(self):
        data = MODULE.build_material_response(
            "129AC0000000089", date(2026, 9, 11), resolution(),
            [("law", "129AC0000000089", (envelope("r1"),)),
             ("law_revision", "rev-1", (envelope("r2", target_kind="law_revision"),))],
            include_nonconfirmed=False,
        )
        self.assertEqual(data["source_family_counts"], {"diet-minutes": 1})

    def test_invalid_relation_id_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.get_relation_detail(object(), "bad")

    def test_invalid_law_id_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.get_related_materials(
                object(), "bad", as_of_date=date(2026, 9, 11)
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
