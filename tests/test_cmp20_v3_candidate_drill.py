"""Pure positive/negative tests of separate owner-signed V3 candidate fault drill."""
from __future__ import annotations
import base64
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch,MagicMock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import cmp20_v3_candidate_drill_verify as v
import cmp20_v3_candidate_drill_owner as ops

START="2026-11-12T06:00:30+00:00"
NEXT="2026-11-12T06:05:01+00:00"
RECEIPT="2026-11-12T06:05:08+00:00"

class Signature(unittest.TestCase):
    def setUp(self):
        issuer=Ed25519PrivateKey.generate()
        reviewer=Ed25519PrivateKey.generate()
        self.keys=(issuer,reviewer)
        self.manifest=v.fields({k:"a"*40 for k in v.SOURCES})
        def b64(k):return base64.b64encode(k.public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
        self.trust={
            "schema":v.TRUST_SCHEMA,"purpose":v.PURPOSE,
            "issuer_public_b64":b64(issuer),"reviewer_public_b64":b64(reviewer)}
        wire=v.canonical(v.claim(self.manifest))
        self.packet={
            "schema":v.PACKET_SCHEMA,"statement":v.claim(self.manifest),
            "issuer_signature_b64":base64.b64encode(issuer.sign(wire)).decode(),
            "reviewer_signature_b64":base64.b64encode(reviewer.sign(wire)).decode()}

    def test_distinct_real_signatures(self):
        v.verify_packet(self.trust,self.manifest,self.packet)

    def test_key_swap_rejected(self):
        p=copy.deepcopy(self.packet)
        p["issuer_signature_b64"]=p["reviewer_signature_b64"]
        with self.assertRaises(v.Hold):
            v.verify_packet(self.trust,self.manifest,p)

    def test_same_role_public_key_rejected(self):
        t=dict(self.trust)
        t["reviewer_public_b64"]=t["issuer_public_b64"]
        with self.assertRaises(v.Hold):
            v.verify_packet(t,self.manifest,self.packet)

    def test_tamper_manifest_port_rejected(self):
        m=dict(self.manifest)
        m["original_port"]=8879
        with self.assertRaises(v.Hold):
            v.verify_packet(self.trust,m,self.packet)

    def test_tamper_manifest_task_rejected(self):
        m=dict(self.manifest)
        m["task"]="RinkaCommanderGithubQueue"
        with self.assertRaises(v.Hold):
            v.verify_packet(self.trust,m,self.packet)

    def test_task_mutation_permission_rejected(self):
        m=dict(self.manifest)
        m["allowed_actions"]=m["allowed_actions"]+["modify_any_windows_task"]
        with self.assertRaises(v.Hold):
            v.verify_packet(self.trust,m,self.packet)

    def test_prior_v3_packet_pin(self):
        self.assertEqual(self.manifest["prior_v3_packet_sha256"],v.V3_PACKET_SHA)

    def test_source_scope_fixed(self):
        with self.assertRaises(v.Hold):
            v.fields({"foo.py":"a"*40})

    def test_duplicate_json_rejected(self):
        with self.assertRaises(v.Hold):
            v.parsed(b'{"schema":"x","schema":"y"}')

    def test_corrupt_packet_signature_rejected(self):
        p=dict(self.packet)
        p["reviewer_signature_b64"]=base64.b64encode(b"\0"*64).decode()
        with self.assertRaises(v.Hold):
            v.verify_packet(self.trust,self.manifest,p)

class NaturalRecovery(unittest.TestCase):
    def setUp(self):
        self.start={
            "schema":"legal-kb.cmp20.v3-signed-drill-start.v1",
            "status":"CANDIDATE_STOPPED_ORIGINAL_PUBLIC_HEALTHY",
            "signed":True,"started_utc":START,"original_public_pid":100,
            "candidate_stopped_pid":200}
        self.tick={"last":NEXT,"result":0}
        self.receipt={
            "schema":"legal-kb.cmp20.headless-v3-tick.v1",
            "status":"PASS","source_signed":True,
            "candidate_recovered":True,"old_public_8878_healthy":True,
            "private_8877_healthy":True,"candidate_8879_healthy":True,
            "original_public_pid":100,"candidate_pid":300,
            "checked_utc":RECEIPT,
        }

    def test_real_postfault_positive(self):
        ops.check_after(self.start,self.tick,self.receipt)

    def test_native_task_failed(self):
        self.tick["result"]=2
        with self.assertRaises(ops.Stop):
            ops.check_after(self.start,self.tick,self.receipt)

    def test_task_before_fault(self):
        self.tick["last"]="2026-11-12T05:59:01+00:00"
        with self.assertRaises(ops.Stop):
            ops.check_after(self.start,self.tick,self.receipt)

    def test_unrecovered_receipt(self):
        self.receipt["candidate_recovered"]=False
        with self.assertRaises(ops.Stop):
            ops.check_after(self.start,self.tick,self.receipt)

    def test_same_pid_not_accepted(self):
        self.receipt["candidate_pid"]=200
        with self.assertRaises(ops.Stop):
            ops.check_after(self.start,self.tick,self.receipt)

    def test_old_public_pid_change_rejected(self):
        self.receipt["original_public_pid"]=400
        with self.assertRaises(ops.Stop):
            ops.check_after(self.start,self.tick,self.receipt)

    def test_unbound_recovery_time_rejected(self):
        self.receipt["checked_utc"]="2026-11-12T05:55:00+00:00"
        with self.assertRaises(ops.Stop):
            ops.check_after(self.start,self.tick,self.receipt)

    def test_private_unhealthy_rejected(self):
        self.receipt["private_8877_healthy"]=False
        with self.assertRaises(ops.Stop):
            ops.check_after(self.start,self.tick,self.receipt)

    def test_injected_unsigned_start_rejected(self):
        self.start["signed"]=False
        with self.assertRaises(ops.Stop):
            ops.check_after(self.start,self.tick,self.receipt)

    def test_task_imminent_injection_refused(self):
        record={"result":0,"missed":0,
                "at":"2026-11-12T06:04:32+00:00",
                "last":"2026-11-12T06:00:01+00:00",
                "next":"2026-11-12T06:05:01+00:00"}
        with self.assertRaises(ops.Stop):
            ops.signed_start_state(record,record["at"])

    def test_safe_pre_next_tick_window_accepted(self):
        record={"result":0,"missed":0,
                "at":"2026-11-12T06:02:00+00:00",
                "last":"2026-11-12T06:00:01+00:00",
                "next":"2026-11-12T06:05:01+00:00"}
        ops.signed_start_state(record,record["at"])

    def test_missed_runs_refused(self):
        record={"result":0,"missed":1,
                "at":"2026-11-12T06:02:00+00:00",
                "last":"2026-11-12T06:00:01+00:00",
                "next":"2026-11-12T06:05:01+00:00"}
        with self.assertRaises(ops.Stop):
            ops.signed_start_state(record,record["at"])

    def test_wrong_source_verifier_rejected(self):
        self.assertEqual(set(v.SOURCES),{
            "cmp20_v3_candidate_drill_verify.py","cmp20_v3_candidate_drill_owner.py"})
        self.assertIn("modify_any_windows_task",v.FORBIDDEN)
        self.assertNotIn("modify_any_windows_task",v.ALLOWED)

class SignedV3ImportContract(unittest.TestCase):
    def test_isolated_qa_explicitly_binds_verified_v3_release_path(self):
        original=list(sys.path)
        with patch.object(ops.signed,"owner"), \
             patch.object(ops.signed,"safe",return_value=b"reviewed"), \
             patch.object(ops.signed,"blob",return_value=ops.V3_VERIFY_BLOB), \
             patch.object(ops.signed,"sha",return_value=ops.signed.V3_PACKET_SHA), \
             patch.object(ops,"module") as imported:
            signature=MagicMock()
            signature.verify.return_value={"status":"PASS"}
            guardian=MagicMock()
            imported.side_effect=[signature,guardian]
            try:
                ops.v3_runtime()
                self.assertIn(str(ops.V3),sys.path)
                self.assertEqual(imported.call_args_list[0].args[1],
                                 ops.V3_VERIFY_BLOB)
            finally:
                sys.path[:]=original

    def test_mismatched_verifier_bytes_fail_before_any_import(self):
        with patch.object(ops.signed,"owner"), \
             patch.object(ops.signed,"safe",return_value=b"tampered"), \
             patch.object(ops.signed,"blob",return_value="f"*40), \
             patch.object(ops,"module") as imported:
            with self.assertRaises(ops.Stop):
                ops.v3_runtime()
            imported.assert_not_called()

if __name__=="__main__":unittest.main()
