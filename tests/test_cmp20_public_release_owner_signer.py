"""Owner CMP20 signer cryptographic tests; no owner Windows key creation."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1] / "scripts"
def load(module, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / module)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj
sign = load("cmp20_public_release_owner_signer.py", "cmp20_signer")
review = load("cmp20_public_release_review.py", "cmp20_verifier")


class OwnerSignerTests(unittest.TestCase):
    def setUp(self):
        self.keys = {role: Ed25519PrivateKey.generate()
                     for role in ("issuer", "reviewer")}

    def test_pinned_source_blob(self):
        self.assertEqual(sign.gitblob((ROOT / sign.REVIEW_VERIFIER).read_bytes()),
                         sign.REVIEW_VERIFIER_BLOB)

    def test_distinct_keys_and_valid_signed_packet(self):
        trust = sign.make_trust(self.keys, review)
        manifest, packet = sign.make_signed_review(self.keys, review)
        verdict = review.verify_packet(trust, manifest, packet)
        self.assertEqual(verdict["status"], "PASS")
        self.assertFalse(verdict["owner_execution_authority"])

    def test_duplicate_keys_rejected(self):
        bad = {"issuer": self.keys["issuer"],
               "reviewer": self.keys["issuer"]}
        with self.assertRaises(sign.SigningHold):
            sign.make_trust(bad, review)

    def test_signature_is_not_cross_campaign(self):
        trust = sign.make_trust(self.keys, review)
        manifest, packet = sign.make_signed_review(self.keys, review)
        packet["statement"]["purpose"] = "rinka.cmp08.watchdog-stage-only.v1"
        with self.assertRaises(review.ReviewHold):
            review.verify_packet(trust, manifest, packet)

    def test_unapproved_cli_while_not_owner_cannot_enroll(self):
        with patch.object(sign.sys, "argv",
                          ["owner", "enroll-review", "--owner-consent", "incorrect"]), \
             patch.object(sign, "enroll") as fn:
            self.assertEqual(sign.main(), 2)
            fn.assert_not_called()

    def test_execution_command_not_exposed(self):
        self.assertEqual(set(sign.CONSENT), {"enroll-review", "issue-review"})
        self.assertNotIn("activate", sign.CONSENT)

    def test_no_clobber_file(self):
        # A file already present may never be overwritten even if protect()
        # is replaced with a test double and no Windows APIs are present.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trust.json"
            path.write_bytes(b"existing")
            with self.assertRaises(sign.SigningHold):
                sign.create_new(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"existing")


    def test_signer_rejects_duplicate_or_nonfinite_trust_json(self):
        for raw in (b'{"schema":"x","schema":"x"}', b'{"value":NaN}',
                    b'{"value":1e309}'):
            with self.subTest(raw=raw), self.assertRaises(review.ReviewHold):
                sign._read_json(raw, review)

    def test_no_owner_approval_is_execution_authority(self):
        keys = sign.make_trust(self.keys, review)
        self.assertEqual(keys["purpose"], review.PURPOSE)
        _, pkt = sign.make_signed_review(self.keys, review)
        self.assertEqual(pkt["statement"]["approval_scope"],
                         "REVIEW_ONLY_NOT_EXECUTION")


if __name__ == "__main__":
    unittest.main()
