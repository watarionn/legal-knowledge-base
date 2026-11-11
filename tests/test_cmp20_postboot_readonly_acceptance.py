"""Pure negative/positive contract tests for CMP20 read-only postboot gate."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import os
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "cmp20_postboot_readonly_acceptance.py"
spec = importlib.util.spec_from_file_location("cmp20_postboot_readonly", SOURCE)
m = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(m)

NOW = datetime(2026, 11, 11, 8, 10, tzinfo=timezone.utc)
BASELINE = "2026-11-10T05:24:48.5000000Z"
CURRENT_BOOT = "2026-11-11T07:00:00Z"
RUN = "2026-11-11T08:05:01Z"
RECEIPT = "2026-11-11T08:05:06Z"


class ReadonlyPostbootGateTests(unittest.TestCase):
    def setUp(self):
        self.local_env = patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\watar\AppData\Local"})
        self.local_env.start()
        self.addCleanup(self.local_env.stop)
        action = "-B " + str(m.release_path() / "cmp20_public_guarded_owner_v2.py") + " --once"
        self.task = {
            "boot_utc": CURRENT_BOOT, "name": m.TASK, "state": "Ready",
            "action": m.OWNER_PYTHON, "arguments": action,
            "principal_user": "watar", "action_count": 1,
            "trigger_types": ["MSFT_TaskDailyTrigger", "MSFT_TaskLogonTrigger"],
            "logon_type": "Interactive", "multiple_instances": "IgnoreNew",
            "allow_hard_terminate": False,
            "logon_trigger": True, "calendar_trigger": True,
            "interval_pt5m": True,
            "last_run_utc": RUN, "last_result": 0, "missed_runs": 0,
            "listeners": {
                "8877": {"pid": 5740, "name": "pythonw.exe", "started_utc": "2026-11-11T07:30:00Z"},
                "8878": {"pid": 15900, "name": "pythonw.exe", "started_utc": "2026-11-11T07:30:00Z"},
                "8879": {"pid": 8976, "name": "pythonw.exe", "started_utc": "2026-11-11T07:30:00Z"},
            },
        }
        self.receipt = {
            "schema": "legal-kb.cmp20.guarded-once-owner-receipt.v1",
            "status": "PASS", "source_signed": True,
            "task_source_grant": "V2_ED25519_TWO_ROLES",
            "owner_host": "YWSHTMR",
            "old_public_8878": "healthy", "new_public_8879": "healthy",
            "private_8877": "healthy", "public_route": m.CANDIDATE,
            "no_old_pid_kill": True, "no_os_reboot": True,
            "old_public_pid": 15900, "candidate_pid": 8976,
            "checked_utc": RECEIPT,
        }
        self.signed = {
            "status": "PASS", "signed_release_and_prior_ed25519_proof": "PASS",
            "old_public_stop_authority": False, "os_reboot_authority": False,
        }
        self.serve = {"Web": {m.FQDN: {"Handlers": {"/": {"Proxy": m.CANDIDATE}}}},
                      "AllowFunnel": {m.FQDN: True}}

    def validate(self, phase="after-relogin", baseline=BASELINE):
        return m.validate(self.task, self.receipt, self.signed, self.serve,
                          NOW, phase, baseline)

    def assert_hold(self, reason):
        with self.assertRaises(m.Hold) as ctx:
            self.validate()
        self.assertEqual(str(ctx.exception), reason)

    def test_positive_postboot(self):
        value = self.validate()
        self.assertEqual(value["status"], "PASS")
        self.assertTrue(value["reboot_since_baseline_proven"])
        self.assertFalse(value["every_five_minute_tick_proven"])

    def test_positive_baseline_without_reboot_claim(self):
        self.task["boot_utc"] = BASELINE
        value = self.validate("baseline", None)
        self.assertEqual(value["status"], "PASS")
        self.assertFalse(value["reboot_since_baseline_proven"])

    def test_unchanged_boot_holds(self):
        self.task["boot_utc"] = BASELINE
        self.assert_hold("NO_NEW_BOOT_PROVEN")

    def test_older_reboot_receipt_holds(self):
        self.task["last_run_utc"] = "2026-11-11T06:50:01Z"
        self.receipt["checked_utc"] = "2026-11-11T06:50:06Z"
        self.assert_hold("TASK_RECEIPT_NOT_FRESH_OR_MATCHED")

    def test_unsigned_packet_holds(self):
        self.signed["status"] = "HOLD"
        self.assert_hold("V2_SIGNED_VERIFIER_HOLD")

    def test_action_drift_holds(self):
        self.task["arguments"] = "--unapproved"
        self.assert_hold("TASK_ACTION_CHANGED")

    def test_missing_trigger_holds(self):
        self.task["interval_pt5m"] = False
        self.assert_hold("TASK_TRIGGERS_OR_POLICY_CHANGED")

    def test_unexpected_extra_action_holds(self):
        self.task["action_count"] = 2
        self.assert_hold("TASK_OWNER_ACTION_OR_TRIGGER_COUNT_HOLD")

    def test_wrong_owner_holds(self):
        self.task["principal_user"] = "SYSTEM"
        self.assert_hold("TASK_OWNER_ACTION_OR_TRIGGER_COUNT_HOLD")

    def test_native_failure_holds(self):
        self.task["last_result"] = 2
        self.assert_hold("TASK_NATIVE_RESULT_HOLD")

    def test_stale_or_mismatched_receipt_holds(self):
        self.receipt["checked_utc"] = "2026-11-11T08:09:00Z"
        self.assert_hold("TASK_RECEIPT_NOT_FRESH_OR_MATCHED")

    def test_pid_mismatch_holds(self):
        self.receipt["candidate_pid"] = 1
        self.assert_hold("RECEIPT_PID_MISMATCH")

    def test_process_not_created_after_boot_holds(self):
        self.task["listeners"]["8879"]["started_utc"] = "2026-11-11T06:00:00Z"
        self.assert_hold("OWNED_LISTENER_IDENTITY_HOLD")

    def test_wrong_funnel_holds(self):
        self.serve["Web"][m.FQDN]["Handlers"]["/"]["Proxy"] = m.ORIGINAL
        self.assert_hold("PUBLIC_ROUTE_OR_FUNNEL_CHANGED")

    def test_broadened_authority_holds(self):
        self.signed["os_reboot_authority"] = True
        self.assert_hold("V2_SIGNED_VERIFIER_HOLD")

    def test_false_private_health_holds(self):
        self.receipt["private_8877"] = "unhealthy"
        self.assert_hold("RECEIPT_CONTENT_HOLD")


if __name__ == "__main__":
    unittest.main()
