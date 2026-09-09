import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).with_name("003_external_source_identity.py")
SPEC = importlib.util.spec_from_file_location("phase6_identity", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class ExternalSourceIdentityTest(unittest.TestCase):
    def test_document_identity_is_deterministic(self):
        a = mod.external_document_id("kokkai-ndl", "100105254X00119470520")
        b = mod.external_document_id("kokkai-ndl", "100105254X00119470520")
        self.assertEqual(a, b)
        self.assertEqual(64, len(a))

    def test_provider_namespace_is_part_of_identity(self):
        a = mod.external_document_id("kokkai-ndl", "same-id")
        b = mod.external_document_id("teikoku-ndl", "same-id")
        self.assertNotEqual(a, b)

    def test_snapshot_changes_when_payload_changes(self):
        doc_id = mod.external_document_id("kanpo-go-jp", "2026-09-09:main:1786")
        a = mod.snapshot_id(doc_id, "a" * 64)
        b = mod.snapshot_id(doc_id, "b" * 64)
        self.assertNotEqual(a, b)

    def test_sha256_normalization_is_case_insensitive(self):
        doc_id = mod.external_document_id("ndl-search", "oai:test:1")
        a = mod.snapshot_id(doc_id, "A" * 64)
        b = mod.snapshot_id(doc_id, "a" * 64)
        self.assertEqual(a, b)

    def test_invalid_sha256_is_rejected(self):
        with self.assertRaises(ValueError):
            mod.snapshot_id("a" * 64, "not-a-sha")

    def test_target_shape_validation(self):
        self.assertEqual(
            "425AC0000000027",
            mod.target_identifier(target_kind="law", law_id="425AC0000000027"),
        )
        self.assertEqual(
            "7:11",
            mod.target_identifier(
                target_kind="provision_node",
                document_pk=7,
                document_order=11,
            ),
        )
        with self.assertRaises(ValueError):
            mod.target_identifier(
                target_kind="law",
                law_id="425AC0000000027",
                law_revision_id="unexpected",
            )

    def test_relation_identity_is_deterministic(self):
        doc_id = mod.external_document_id("kokkai-ndl", "issue-1")
        first = mod.source_relation_id(doc_id, "law", "425AC0000000027", "discusses")
        second = mod.source_relation_id(doc_id, "law", "425AC0000000027", "discusses")
        self.assertEqual(first, second)

    def test_automatic_match_defaults_to_candidate(self):
        for basis in ("identifier-match", "metadata-match", "text-match", "derived"):
            self.assertEqual("candidate", mod.default_assertion_status(basis))

    def test_explicit_or_manual_can_be_confirmed(self):
        self.assertEqual("confirmed", mod.default_assertion_status("provider-explicit"))
        self.assertEqual("confirmed", mod.default_assertion_status("manual"))

    def test_assertion_identity_uses_canonical_evidence(self):
        relation_id = "a" * 64
        first = mod.relation_assertion_id(relation_id, "metadata-match", {"b": 2, "a": 1})
        second = mod.relation_assertion_id(relation_id, "metadata-match", {"a": 1, "b": 2})
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
