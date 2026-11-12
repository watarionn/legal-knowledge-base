"""CMP-20 V3 source-only positive/negative owner-policy regression tests.

No Windows Task, private key, port or public route changes are made by tests.
"""
from __future__ import annotations

import base64
from contextlib import nullcontext
import json
import pathlib
import sys
import unittest
from unittest.mock import patch, MagicMock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import cmp20_headless_v3_verify as verifier
import cmp20_headless_v3_guard as guardian
import cmp20_headless_v3_owner as owner

class V3Protocol(unittest.TestCase):
    def setUp(self):
        self.issuer = Ed25519PrivateKey.generate()
        self.reviewer = Ed25519PrivateKey.generate()
        self.sources = {name: "a" * 40 for name in verifier.SOURCES}
        self.manifest = verifier.manifest_fields(self.sources)
        def pk(k):
            return base64.b64encode(k.public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw)).decode()
        self.trust = {
            "schema": verifier.TRUST_SCHEMA,
            "purpose": verifier.PURPOSE,
            "issuer_public_b64": pk(self.issuer),
            "reviewer_public_b64": pk(self.reviewer),
        }
        claim = verifier.statement(self.manifest)
        data = verifier.canonical(claim)
        self.packet = {
            "schema": verifier.PACKET_SCHEMA,
            "statement": claim,
            "issuer_signature_b64": base64.b64encode(
                self.issuer.sign(data)).decode(),
            "reviewer_signature_b64": base64.b64encode(
                self.reviewer.sign(data)).decode(),
        }

    def test_two_distinct_signatures(self):
        verifier.check_packet(self.trust, self.manifest, self.packet)

    def test_swap_roles_refused(self):
        p = dict(self.packet)
        p["issuer_signature_b64"] = p["reviewer_signature_b64"]
        with self.assertRaises(verifier.V3Hold):
            verifier.check_packet(self.trust, self.manifest, p)

    def test_same_roles_refused(self):
        trust = dict(self.trust)
        trust["reviewer_public_b64"] = trust["issuer_public_b64"]
        with self.assertRaises(verifier.V3Hold):
            verifier.check_packet(trust, self.manifest, self.packet)

    def test_wrong_manifest_refused(self):
        manifest = dict(self.manifest)
        manifest["forbidden_actions"] = []
        with self.assertRaises(verifier.V3Hold):
            verifier.check_packet(self.trust, manifest, self.packet)

    def test_wrong_task_refused(self):
        manifest = dict(self.manifest)
        manifest["new_task"] = "RinkaCommanderGithubQueue"
        with self.assertRaises(verifier.V3Hold):
            verifier.check_packet(self.trust, manifest, self.packet)

    def test_wrong_python_refused(self):
        manifest = dict(self.manifest)
        manifest["headless_python"] = r"C:\Python314\python.exe"
        with self.assertRaises(verifier.V3Hold):
            verifier.check_packet(self.trust, manifest, self.packet)

    def test_wrong_source_blob_refused(self):
        manifest = verifier.manifest_fields(
            {**self.sources, verifier.SOURCES[0]: "b"*40})
        with self.assertRaises(verifier.V3Hold):
            verifier.check_packet(self.trust, manifest, self.packet)

    def test_extra_permission_refused(self):
        manifest = dict(self.manifest)
        manifest["allowed_actions"] = list(manifest["allowed_actions"])+["os_reboot"]
        with self.assertRaises(verifier.V3Hold):
            verifier.check_packet(self.trust, manifest, self.packet)

    def test_corrupted_signature_refused(self):
        p = dict(self.packet)
        p["reviewer_signature_b64"] = base64.b64encode(b"\0"*64).decode()
        with self.assertRaises(verifier.V3Hold):
            verifier.check_packet(self.trust, self.manifest, p)

    def test_duplicate_json_refused(self):
        with self.assertRaises(verifier.V3Hold):
            verifier.strict_json(b'{"schema":"a","schema":"b"}')

    def test_signed_manifest_has_immutable_v2(self):
        self.assertEqual(self.manifest["old_guard_git_blob"],
                         verifier.V2_GUARD_BLOB)
        self.assertEqual(self.manifest["prior_v2_packet_sha256"],
                         verifier.V2_PACKET_SHA)
        self.assertNotIn("reboot_os", self.manifest["allowed_actions"])
        self.assertIn("reboot_os", self.manifest["forbidden_actions"])

    def test_signed_manifest_binds_headless_command(self):
        self.assertTrue(self.manifest["headless_python"].endswith("pythonw.exe"))
        self.assertIn("--once", self.manifest["new_task_args"])
        self.assertNotIn("powershell", self.manifest["new_task_args"])

class V3TaskIdentity(unittest.TestCase):
    def sample(self):
        return {
            "state": "Ready",
            "owner": "watar",
            "logon": "Interactive",
            "level": "Limited",
            "action_count": 1,
            "execute": verifier.PYTHONW,
            "args": verifier.ARGUMENTS,
            "cwd": str(verifier.RELEASE),
            "overlap": "IgnoreNew",
            "hard": False,
            "on_demand": False,
            "triggers": [
                {"type": "MSFT_TaskDailyTrigger", "enabled": True,
                 "interval": "PT5M", "duration": "P1D"},
                {"type": "MSFT_TaskLogonTrigger", "enabled": True,
                 "interval": "", "duration": ""},
            ],
        }

    def test_valid(self):
        guardian.check_new_task(self.sample(), True)

    def test_visible_python_rejected(self):
        value = self.sample()
        value["execute"] = r"C:\Python314\python.exe"
        with self.assertRaises(guardian.HeadlessHold):
            guardian.check_new_task(value, True)

    def test_modified_trigger_rejected(self):
        value = self.sample()
        value["triggers"][0]["interval"] = "PT1M"
        with self.assertRaises(guardian.HeadlessHold):
            guardian.check_new_task(value, True)

    def test_wrong_owner_rejected(self):
        value = self.sample()
        value["owner"] = "SYSTEM"
        with self.assertRaises(guardian.HeadlessHold):
            guardian.check_new_task(value, True)

    def test_wrong_args_rejected(self):
        value = self.sample()
        value["args"] += " --another-task"
        with self.assertRaises(guardian.HeadlessHold):
            guardian.check_new_task(value, True)

    def test_original_task_must_be_disabled(self):
        old = {
            "state": "Ready", "owner": "watar",
            "logon": "Interactive", "level": "Limited",
            "action_count": 1, "execute": verifier.PYTHONW,
            "args": verifier.OLD_ACTION, "overlap": "IgnoreNew",
            "hard": False, "trigger_count": 2,
        }
        with self.assertRaises(guardian.HeadlessHold):
            guardian.checked_old_task(old)
        old["state"] = "Disabled"
        guardian.checked_old_task(old)

    def test_old_original_action_tamper_rejected(self):
        old = {
            "state": "Disabled", "owner": "watar",
            "logon": "Interactive", "level": "Limited",
            "action_count": 1, "execute": verifier.PYTHONW,
            "args": verifier.OLD_ACTION + " --unsafe",
            "overlap": "IgnoreNew", "hard": False,
            "trigger_count": 2,
        }
        with self.assertRaises(guardian.HeadlessHold):
            guardian.checked_old_task(old)

    def test_disabled_xml_is_headless_and_5minute(self):
        s = owner.task_xml()
        self.assertIn("<Enabled>false</Enabled>", s)
        self.assertIn("<Hidden>true</Hidden>", s)
        self.assertIn("<Interval>PT5M</Interval>", s)
        self.assertIn("<Command>" + verifier.PYTHONW + "</Command>", s)
        self.assertIn("<AllowHardTerminate>false</AllowHardTerminate>", s)

class V3GuardIntegrationMock(unittest.TestCase):
    def test_does_not_launch_duplicate_candidate(self):
        fake = MagicMock()
        fake.OLD = "http://127.0.0.1:8878"
        fake.NEW = "http://127.0.0.1:8879"
        fake.exclusive.return_value = nullcontext()
        fake.require_old_and_private.return_value = 123
        fake.proxy.return_value = fake.NEW
        fake.candidate_ok.return_value = (True, 456)
        fake.port_owner.return_value = {"pid": 123}
        old = {"state": "Disabled", "owner": "watar",
               "logon": "Interactive", "level": "Limited",
               "action_count": 1, "execute": verifier.PYTHONW,
               "args": verifier.OLD_ACTION,
               "overlap": "IgnoreNew", "hard": False,
               "trigger_count": 2}
        new = V3TaskIdentity().sample()
        with (patch.object(guardian.grant, "verify", return_value={"status": "PASS"}),
              patch.object(guardian, "source_pinned", return_value=fake),
              patch.object(guardian, "invisible_children", return_value=nullcontext()),
              patch.object(guardian, "task_info", side_effect=[old, new]),
              patch.object(guardian, "persist_receipt") as receipt):
            result = guardian.one_tick()
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["candidate_recovered"])
        fake.launch_without_capture.assert_not_called()
        fake.switch_route.assert_not_called()
        receipt.assert_called_once()

    def test_no_unhealthy_occupied_candidate_force_kill(self):
        fake = MagicMock()
        fake.OLD = "http://127.0.0.1:8878"
        fake.NEW = "http://127.0.0.1:8879"
        fake.exclusive.return_value = nullcontext()
        fake.require_old_and_private.return_value = 123
        fake.proxy.return_value = fake.OLD
        fake.candidate_ok.return_value = (False, 456)
        fake.port_owner.return_value = {"pid": 456}
        old = {"state": "Disabled", "owner": "watar",
               "logon": "Interactive", "level": "Limited",
               "action_count": 1, "execute": verifier.PYTHONW,
               "args": verifier.OLD_ACTION,
               "overlap": "IgnoreNew", "hard": False,
               "trigger_count": 2}
        new = V3TaskIdentity().sample()
        with (patch.object(guardian.grant, "verify", return_value={"status": "PASS"}),
              patch.object(guardian, "source_pinned", return_value=fake),
              patch.object(guardian, "invisible_children", return_value=nullcontext()),
              patch.object(guardian, "task_info", side_effect=[old, new])):
            with self.assertRaises(guardian.HeadlessHold):
                guardian.one_tick()
        fake.stop_candidate_only.assert_not_called()

class V3NoPopupContract(unittest.TestCase):
    def test_wrong_task_name_refused_before_windows_shell(self):
        with self.assertRaises(guardian.HeadlessHold):
            guardian.task_info(MagicMock(), "RinkaCommanderGithubQueue")

    def test_no_signature_no_recovery(self):
        with patch.object(guardian.grant, "verify",
                          side_effect=verifier.V3Hold("NOT_SIGNED")), \
             patch.object(guardian, "source_pinned") as load:
            with self.assertRaises(verifier.V3Hold):
                guardian.one_tick()
        load.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "owner Windows only")
    def test_all_subprocess_windows_hidden_even_if_v2_uses_powershell(self):
        original = guardian.subprocess.Popen
        with patch.object(guardian.subprocess, "Popen") as pop:
            with guardian.invisible_children():
                guardian.subprocess.Popen(
                    ["powershell.exe", "-NoProfile"], shell=False)
            kwargs = pop.call_args.kwargs
            self.assertTrue(
                kwargs["creationflags"] &
                guardian.subprocess.CREATE_NO_WINDOW)
            self.assertTrue(
                kwargs["startupinfo"].dwFlags &
                guardian.subprocess.STARTF_USESHOWWINDOW)
            self.assertEqual(
                kwargs["startupinfo"].wShowWindow,
                guardian.subprocess.SW_HIDE)
        self.assertIs(guardian.subprocess.Popen, original)

    def test_signer_loads_protected_helper_from_reviewed_qa_not_v2_release(self):
        fake = object()
        with patch.object(owner.runtime, "source_pinned", return_value=fake) as pinned:
            self.assertIs(owner.helper(), fake)
        self.assertEqual(pinned.call_args.args[0],
                         owner.QA / "cmp20_public_release_owner_signer.py")
        self.assertEqual(pinned.call_args.args[1],
                         "4199852e192349270096807af52d358ee89afe2b")

    def test_exact_source_set_cannot_be_expanded(self):
        source = {name: "a" * 40 for name in verifier.SOURCES}
        source["unexpected_task.py"] = "f" * 40
        with self.assertRaises(verifier.V3Hold):
            verifier.manifest_fields(source)

if __name__ == "__main__":
    unittest.main()
