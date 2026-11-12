"""Read-only tests for CMP20 V3 signed natural fault-finish correction."""
from __future__ import annotations
import base64
import copy
from pathlib import Path
import sys
import unittest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import cmp20_v3_finish_verify_v2 as v
import cmp20_v3_finish_owner_v2 as o

class Signature(unittest.TestCase):
    def setUp(self):
        a,b=Ed25519PrivateKey.generate(),Ed25519PrivateKey.generate()
        def pb(k):return base64.b64encode(k.public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
        self.manifest=v.fields({n:"a"*40 for n in v.SOURCES})
        self.trust={"schema":v.T_SCHEMA,"purpose":v.PURPOSE,
                    "issuer_public_b64":pb(a),"reviewer_public_b64":pb(b)}
        wire=v.canonical(v.claim(self.manifest))
        self.packet={"schema":v.P_SCHEMA,"statement":v.claim(self.manifest),
                     "issuer_signature_b64":base64.b64encode(a.sign(wire)).decode(),
                     "reviewer_signature_b64":base64.b64encode(b.sign(wire)).decode()}
    def test_signatures_valid(self):v.verify_packet(self.trust,self.manifest,self.packet)
    def test_signature_swap_denied(self):
        p=dict(self.packet);p["issuer_signature_b64"]=p["reviewer_signature_b64"]
        with self.assertRaises(v.Hold):v.verify_packet(self.trust,self.manifest,p)
    def test_manifest_cannot_stop_any_process(self):
        p=dict(self.manifest);p["allowed"]=p["allowed"]+["stop_any_process"]
        with self.assertRaises(v.Hold):v.verify_packet(self.trust,p,self.packet)
    def test_manifest_pid_change_refused(self):
        p=dict(self.manifest);p["recovered_candidate_pid"]=15973
        with self.assertRaises(v.Hold):v.verify_packet(self.trust,p,self.packet)
    def test_manifest_route_change_refused(self):
        p=dict(self.manifest);p["exact_public_route_from"]="http://127.0.0.1:9999"
        with self.assertRaises(v.Hold):v.verify_packet(self.trust,p,self.packet)
    def test_private_old_signer_not_reused(self):
        self.assertEqual(self.manifest["signed_start_receipt_sha256"],v.START_SHA)
        self.assertEqual(self.manifest["signed_v3_natural_recovery_receipt_sha256"],v.RECOVERED_SHA)
        self.assertIn("modify_any_windows_task",self.manifest["forbidden"])
        self.assertNotIn("stop_any_process",self.manifest["allowed"])
    def test_duplicate_json_denied(self):
        with self.assertRaises(v.Hold):v.parsed(b'{"x":1,"x":2}')

class NaturalReceipt(unittest.TestCase):
    def setUp(self):
        self.start={"schema":"legal-kb.cmp20.v3-signed-drill-start.v1",
                    "status":"CANDIDATE_STOPPED_ORIGINAL_PUBLIC_HEALTHY",
                    "signed":True,"original_public_pid":12736,
                    "candidate_stopped_pid":9900,
                    "started_utc":"2026-11-12T06:10:33.790475+00:00"}
        self.recovered={"schema":"legal-kb.cmp20.headless-v3-tick.v1",
                        "status":"PASS","source_signed":True,
                        "candidate_recovered":True,"old_public_pid":12736,
                        "candidate_pid":15972,
                        "candidate_8879_healthy":True,
                        "old_public_8878_healthy":True,
                        "private_8877_healthy":True,
                        "checked_utc":"2026-11-12T06:15:11.525855+00:00"}
        self.tick={"last":"2026-11-12T06:15:01+00:00","result":0,"missed":0}
    def check(self):o.check_recovered(self.start,self.recovered,self.tick)
    def test_exact_real_v3_key_old_public_pid(self):self.check()
    def test_wrong_legacy_key_is_denied(self):
        self.recovered["original_public_pid"]=12736
        self.recovered.pop("old_public_pid")
        with self.assertRaises(o.Hold):self.check()
    def test_wrong_pid_denied(self):
        self.recovered["candidate_pid"]=9900
        with self.assertRaises(o.Hold):self.check()
    def test_missing_recovery_true_denied(self):
        self.recovered["candidate_recovered"]=False
        with self.assertRaises(o.Hold):self.check()
    def test_unhealthy_private_denied(self):
        self.recovered["private_8877_healthy"]=False
        with self.assertRaises(o.Hold):self.check()
    def test_unbound_tick_denied(self):
        self.tick["last"]="2026-11-12T06:13:00+00:00"
        with self.assertRaises(o.Hold):self.check()
    def test_native_failed_denied(self):
        self.tick["result"]=2
        with self.assertRaises(o.Hold):self.check()
    def test_native_missed_denied(self):
        self.tick["missed"]=1
        with self.assertRaises(o.Hold):self.check()
    def test_original_pid_tamper_denied(self):
        self.start["original_public_pid"]=12737
        with self.assertRaises(o.Hold):self.check()
if __name__=="__main__":unittest.main()
