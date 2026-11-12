"""Pure negative acceptance cases for immutable CMP20 V3 24h owner reader."""
from __future__ import annotations
from datetime import timedelta
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"cmp20_v3_24h_owner_acceptance_readonly.py"
spec=importlib.util.spec_from_file_location("cmp20_24h_test",SCRIPT)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

BOOT="2026-11-12T03:03:46.500000+00:00"
NOW="2026-11-13T06:30:00+00:00"
LAST="2026-11-13T06:25:01+00:00"
FINISH_AT="2026-11-12T06:26:28.487269+00:00"

class V3ElapsedAcceptance(unittest.TestCase):
    def setUp(self):
        self.runtime={
            "status":"PASS","native_task_pass":True,
            "matching_receipt_pass":True,"read_only":True,
            "headless_pythonw":True,"source_signed":True,
            "v2_immutable_signature":True,
            "public_local_https_and_private_isolation":"PASS",
            "boot_utc":BOOT,"last_natural_tick_utc":LAST,
            "receipt_sha256":"a"*64,
        }
        self.finish={
            "status":"PASS","independent_owner_signers":2,
            "signed_prior_drill":"PASS",
            "original_signed_v3_recovery":"PASS",
            "task_and_services_modified":False,
        }
        self.receipt={
            "schema":"legal-kb.cmp20.v3-fault-drill-signed-finish-v2.v1",
            "status":"PASS","source_signed":True,
            "native_v3_last_result":0,
            "signed_candidate_stopped_pid":9900,
            "original_public_pid":12736,
            "recovered_candidate_pid":15972,
            "public_route":"http://127.0.0.1:8879",
            "public_8443_healthy":True,
            "private_8877_preserved":True,
            "original_8878_preserved":True,
            "candidate_8879_healthy":True,
            "no_task_modifications":True,
            "no_new_reboot":True,
            "drill_start_sha256":"99ec7c2f0ab8d0d83cdf15c6d4bf0df6683ae3489de8c00d5d7c3cca32eb3d8b",
            "signed_recovered_v3_receipt_sha256":"11d6b4de644c0e6169d0b82e625ac6624b289d34bf96e2efb61855394db2191b",
            "completed_utc":FINISH_AT,
        }
    def check(self,**updates):
        inputs={"now_utc":NOW,"boot_utc":BOOT,"last_utc":LAST,
                "owner_witness":self.runtime,
                "signed_finish":self.finish,
                "finish_receipt":self.receipt}
        inputs.update(updates)
        return mod.gate(**inputs)

    def test_after_real_24h_elapsed_passes(self):
        result=self.check()
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["real_signed_candidate_fault_and_restore"],"PASS")
        self.assertFalse(result["task_schedule_every_tick_observed"])
        self.assertEqual(result["canonical_campaign_closure"],"SEPARATE_REVIEW_GATE")

    def test_before_24h_must_hold(self):
        with self.assertRaises(mod.Hold):
            self.check(now_utc="2026-11-12T16:30:00+00:00")

    def test_reboot_during_window_rejected(self):
        with self.assertRaises(mod.Hold):
            self.check(boot_utc="2026-11-12T09:00:00+00:00")

    def test_no_post_24h_natural_task_rejected(self):
        with self.assertRaises(mod.Hold):
            self.check(last_utc="2026-11-13T05:00:01+00:00")

    def test_task_last_receipt_stale_rejected(self):
        with self.assertRaises(mod.Hold):
            self.check(last_utc="2026-11-13T06:01:01+00:00")

    def test_signature_role_mismatch_rejected(self):
        self.finish["independent_owner_signers"]=1
        with self.assertRaises(mod.Hold):
            self.check()

    def test_unsigned_recovery_rejected(self):
        self.finish["signed_prior_drill"]="HOLD"
        with self.assertRaises(mod.Hold):
            self.check()

    def test_current_owner_task_not_pass_rejected(self):
        self.runtime["native_task_pass"]=False
        with self.assertRaises(mod.Hold):
            self.check()

    def test_owner_only_no_task_mutation(self):
        self.runtime["read_only"]=False
        with self.assertRaises(mod.Hold):
            self.check()

    def test_owner_not_exact_boot_rejected(self):
        self.runtime["boot_utc"]="2026-11-10T05:24:48+00:00"
        with self.assertRaises(mod.Hold):
            self.check()

    def test_wrong_old_public_pid_rejected(self):
        self.receipt["original_public_pid"]=12345
        with self.assertRaises(mod.Hold):
            self.check()

    def test_wrong_recovered_pid_rejected(self):
        self.receipt["recovered_candidate_pid"]=9900
        with self.assertRaises(mod.Hold):
            self.check()

    def test_public_not_on_new_candidate_rejected(self):
        self.receipt["public_route"]="http://127.0.0.1:8878"
        with self.assertRaises(mod.Hold):
            self.check()

    def test_private_8877_not_preserved_rejected(self):
        self.receipt["private_8877_preserved"]=False
        with self.assertRaises(mod.Hold):
            self.check()

    def test_false_claim_of_unmodified_tasks_rejected(self):
        self.receipt["no_task_modifications"]=False
        with self.assertRaises(mod.Hold):
            self.check()

    def test_unbound_drill_receipt_sha_rejected(self):
        self.receipt["drill_start_sha256"]="0"*64
        with self.assertRaises(mod.Hold):
            self.check()

    def test_finish_utc_after_acceptance_rejected(self):
        self.receipt["completed_utc"]="2026-11-14T01:00:00+00:00"
        with self.assertRaises(mod.Hold):
            self.check()

    def test_unknown_mode_cli_no_execution(self):
        with patch.object(mod.sys, "argv", [str(SCRIPT),"--run"]):
            self.assertEqual(mod.main(),2)

if __name__=="__main__":
    unittest.main()
