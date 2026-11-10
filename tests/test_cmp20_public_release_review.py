"""CMP20 dual-owner-signer review authorization is non-executable."""
from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

FILE = Path(__file__).resolve().parents[1] / "scripts" / "cmp20_public_release_review.py"
spec = importlib.util.spec_from_file_location("cmp20_review_tested", FILE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def pub(key):
    return base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )).decode("ascii")


def approved_keys():
    keys = {"issuer": Ed25519PrivateKey.generate(),
            "reviewer": Ed25519PrivateKey.generate()}
    trust = {"schema": m.TRUST_SCHEMA, "purpose": m.PURPOSE,
             "issuer_public_b64": pub(keys["issuer"]),
             "reviewer_public_b64": pub(keys["reviewer"])}
    manifest = m.expected_manifest()
    statement = {
        "purpose": m.PURPOSE, "release_id": m.RELEASE_ID,
        "old_public_git_head": m.OWNER_HEAD,
        "reviewed_fix_main_commit": m.SOURCE_MAIN,
        "stage_manifest_sha256": m.STAGE_MANIFEST_SHA256,
        "review_manifest_sha256": m.sha(m.canonical(manifest)),
        "approval_scope": "REVIEW_ONLY_NOT_EXECUTION",
    }
    packet = {"schema": m.PACKET_SCHEMA, "statement": statement}
    for name, key in keys.items():
        packet[name + "_signature_b64"] = base64.b64encode(
            key.sign(m.canonical(statement))).decode("ascii")
    return keys, trust, manifest, packet


class OwnerReviewVerifierTests(unittest.TestCase):
    def test_real_dual_ed25519_review_pass_without_execution(self):
        _, trust, manifest, packet = approved_keys()
        proof = m.verify_packet(trust, manifest, packet)
        self.assertEqual(proof["status"], "PASS")
        self.assertFalse(proof["owner_execution_authority"])
        self.assertFalse(proof["rollback_execution_authorized"])

    def test_same_key_used_for_both_roles_fails(self):
        _, trust, manifest, packet = approved_keys()
        trust["reviewer_public_b64"] = trust["issuer_public_b64"]
        with self.assertRaises(m.ReviewHold):
            m.verify_packet(trust, manifest, packet)

    def test_issuer_signature_tampering_fails(self):
        _, trust, manifest, packet = approved_keys()
        packet["issuer_signature_b64"] = base64.b64encode(b"\x00" * 64).decode()
        with self.assertRaises(m.ReviewHold):
            m.verify_packet(trust, manifest, packet)

    def test_wrong_owner_purpose_fails(self):
        _, trust, manifest, packet = approved_keys()
        trust["purpose"] = "rinka.cmp08.watchdog-maintenance.owner-review.v1"
        with self.assertRaises(m.ReviewHold):
            m.verify_packet(trust, manifest, packet)

    def test_modified_review_manifest_fails(self):
        _, trust, manifest, packet = approved_keys()
        manifest["task_trigger_allowed"] = True
        with self.assertRaises(m.ReviewHold):
            m.verify_packet(trust, manifest, packet)

    def test_manifest_extra_field_fails(self):
        _, trust, manifest, packet = approved_keys()
        manifest["allow_exec"] = "yes"
        with self.assertRaises(m.ReviewHold):
            m.verify_packet(trust, manifest, packet)

    def test_changed_approval_scope_fails(self):
        _, trust, manifest, packet = approved_keys()
        packet["statement"]["approval_scope"] = "EXECUTE"
        with self.assertRaises(m.ReviewHold):
            m.verify_packet(trust, manifest, packet)

    def test_swapped_issuer_and_reviewer_keys_fails(self):
        _, trust, manifest, packet = approved_keys()
        trust["issuer_public_b64"], trust["reviewer_public_b64"] = (
            trust["reviewer_public_b64"], trust["issuer_public_b64"])
        with self.assertRaises(m.ReviewHold):
            m.verify_packet(trust, manifest, packet)

    def test_packet_extra_field_fails(self):
        _, trust, manifest, packet = approved_keys()
        packet["run"] = True
        with self.assertRaises(m.ReviewHold):
            m.verify_packet(trust, manifest, packet)

    def test_stage_missing_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(m.ReviewHold):
                m.verify_staged_source(Path(root) / "absent")

    def test_stage_malformed_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            d = Path(root)
            (d / "manifest.json").write_text("{}", encoding="utf8")
            for name in m.PATCH_BLOBS:
                (d / name).write_bytes(b"x")
            with self.assertRaises(m.ReviewHold):
                m.verify_staged_source(d)

    def test_stage_unknown_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            d = Path(root)
            (d / "manifest.json").write_bytes(b"{}")
            for name in m.PATCH_BLOBS:
                (d / name).write_bytes(b"x")
            (d / "extra.sh").write_text("x")
            with self.assertRaises(m.ReviewHold):
                m.verify_staged_source(d)


    def test_strict_owner_json_rejects_duplicate_and_nonfinite_values(self):
        invalid = (
            b'{"schema":"ok","schema":"ok"}',
            b'{"outer":{"purpose":"a","purpose":"a"}}',
            b'{"value":NaN}',
            b'{"value":Infinity}',
            b'{"value":-Infinity}',
            b'{"value":1e309}',
            b'{"value":null,"nested":{"count":2,"count":2}}',
        )
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "trust.json"
            for raw in invalid:
                with self.subTest(raw=raw):
                    target.write_bytes(raw)
                    with self.assertRaises(m.ReviewHold):
                        m._json_file(target)

    def test_strict_owner_json_accepts_valid_nested_json(self):
        wire = b'{"outer":{"a":1,"b":2},"float":2.5,"enabled":false}'
        self.assertEqual(
            m.strict_json(wire),
            {"outer": {"a": 1, "b": 2}, "float": 2.5, "enabled": False}
        )

    def test_strict_owner_json_rejects_invalid_utf8_and_root_arrays(self):
        for raw in (bytes([0xff]), b'[]', b'null'):
            with self.subTest(raw=raw), self.assertRaises(m.ReviewHold):
                m.strict_json(raw)

    def test_deeply_nested_owner_json_fails_closed(self):
        raw = b'[' * 1500 + b'0' + b']' * 1500
        with self.assertRaises(m.ReviewHold):
            m.strict_json(raw)

    def test_unapproved_cli_does_not_inspect(self):
        with patch.object(m.sys, "argv", ["verifier", "--activate"]), \
             patch.object(m, "inspect") as fn:
            self.assertEqual(m.main(), 2)
            fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
