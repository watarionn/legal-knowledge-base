"""Pure owner-readonly V3 native tick binding and negative tests."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"cmp20_headless_v3_owner_acceptance_readonly.py"
spec=importlib.util.spec_from_file_location("cmp20_v3_acceptance_test",SCRIPT)
reader=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)

BOOT="2026-11-12T03:03:46.500000+00:00"
TICK="2026-11-12T05:15:01+00:00"
NOW="2026-11-12T05:15:19+00:00"

class Receipt(unittest.TestCase):
    def setUp(self):
        self.receipt={
            "schema":"legal-kb.cmp20.headless-v3-tick.v1",
            "status":"PASS",
            "task":"RinkaLegalKBPublicGuardedOnceV3",
            "source_signed":True,
            "v2_immutable_ed25519":True,
            "pythonw_headless":True,
            "old_public_stop":False,
            "mutated_other_task":False,
            "did_reboot":False,
            "private_8877_healthy":True,
            "old_public_8878_healthy":True,
            "candidate_8879_healthy":True,
            "public_https_8443_healthy":True,
            "public_route":"http://127.0.0.1:8879",
            "checked_utc":"2026-11-12T05:15:08+00:00",
            "old_public_pid":12736,
            "candidate_pid":9900,
        }

    def check(self,**overrides):
        fields={
            "boot_utc":BOOT,"last_utc":TICK,
            "last_result":0,"missed":0,
            "receipt":self.receipt,"now_utc":NOW,
        }
        fields.update(overrides)
        return reader.bound_receipt(**fields)

    def test_genuine_tick(self):
        self.assertTrue(self.check()["matching_receipt_pass"])

    def test_unchanged_boot(self):
        with self.assertRaises(reader.AcceptanceHold):
            self.check(boot_utc="2026-11-10T05:24:48.500000+00:00")

    def test_native_task_failure(self):
        with self.assertRaises(reader.AcceptanceHold):
            self.check(last_result=2)

    def test_missed_task_run(self):
        with self.assertRaises(reader.AcceptanceHold):
            self.check(missed=1)

    def test_tick_before_boot(self):
        with self.assertRaises(reader.AcceptanceHold):
            self.check(last_utc="2026-11-12T02:15:01+00:00")

    def test_unmatched_receipt_timestamp(self):
        self.receipt["checked_utc"]="2026-11-12T05:07:01+00:00"
        with self.assertRaises(reader.AcceptanceHold):
            self.check()

    def test_stale_receipt(self):
        with self.assertRaises(reader.AcceptanceHold):
            self.check(now_utc="2026-11-12T05:30:00+00:00")

    def test_wrong_campaign_task(self):
        self.receipt["task"]="RinkaLegalKBPublicGuardedOnceV2"
        with self.assertRaises(reader.AcceptanceHold):
            self.check()

    def test_wrong_route(self):
        self.receipt["public_route"]="http://127.0.0.1:8878"
        with self.assertRaises(reader.AcceptanceHold):
            self.check()

    def test_not_ed25519(self):
        self.receipt["source_signed"]=False
        with self.assertRaises(reader.AcceptanceHold):
            self.check()

    def test_original_process_stop_is_forbidden(self):
        self.receipt["old_public_stop"]=True
        with self.assertRaises(reader.AcceptanceHold):
            self.check()

    def test_no_timezone_offset(self):
        with self.assertRaises(reader.AcceptanceHold):
            self.check(last_utc="2026-11-12T05:15:01")

if __name__=="__main__":
    unittest.main()
