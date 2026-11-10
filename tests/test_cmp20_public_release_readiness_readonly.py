"""CMP20 truthful public patch readiness boundary tests, no live mutations."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

FILE=Path(__file__).resolve().parents[1]/"scripts"/"cmp20_public_release_readiness_readonly.py"
spec=importlib.util.spec_from_file_location("cmp20_readiness",FILE)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def runtime(**changes):
    x={"status":"HEALTHY","source_git_head_pinned":True,
       "launcher_sha256_pinned":True,"funnel_target_pinned":True,
       "owner_process_verified":True,"public_health_verified":True,
       "read_only":True,"owner_execution_authority":False}
    x.update(changes)
    return x


def stage(**changes):
    x={"status":"PASS","stage_manifest_sha256":
       "9b8730abdfe399b9f8d9bf86e95fac0b9063236f214c306c439da4588b80374f",
       "patch_bytes_match":True,"source_files":2}
    x.update(changes)
    return x


def public(**changes):
    x={"public_https_root":200,"public_https_health":200,
       "private_public_exposure":404,"public_security_headers_verified":True}
    x.update(changes)
    return x


class CMP20OwnerReadinessTests(unittest.TestCase):
    def test_current_stage_healthy_but_unsigned_is_not_pass(self):
        v=m.evaluate(runtime(),stage(),None,public())
        self.assertEqual(v["status"],"HOLD_FOR_PRODUCTION_CUTOVER")
        self.assertEqual(v["review_key_or_packet_state"],
                         "OWNER_REVIEW_KEY_ENROLLMENT_AND_PACKET_PENDING")
        self.assertFalse(v["owner_execution_authority"])
        self.assertFalse(v["public_new_patch_deployed"])
        self.assertFalse(v["cmp20_canonical_campaign_completed"])

    def test_signed_review_still_cannot_activate_cutover(self):
        review={"status":"PASS","verified_scope":"REVIEW_ONLY_NOT_EXECUTION",
                "owner_execution_authority":False}
        v=m.evaluate(runtime(),stage(),review,public())
        self.assertTrue(v["review_signed"])
        self.assertFalse(v["owner_execution_authority"])
        self.assertFalse(v["public_new_patch_deployed"])
        self.assertFalse(v["shared_reboot_performed"])

    def test_forged_execution_authority_refused(self):
        signed={"status":"PASS","verified_scope":"REVIEW_ONLY_NOT_EXECUTION",
                "owner_execution_authority":True}
        with self.assertRaises(m.ReadinessHold):
            m.evaluate(runtime(),stage(),signed,public())

    def test_wrong_signed_purpose_refused(self):
        signed={"status":"PASS","verified_scope":"EXECUTE","owner_execution_authority":False}
        with self.assertRaises(m.ReadinessHold):
            m.evaluate(runtime(),stage(),signed,public())

    def test_other_runtime_head_is_not_current_healthy(self):
        with self.assertRaises(m.ReadinessHold):
            m.evaluate(runtime(source_git_head_pinned=False),stage(),None,public())

    def test_public_listener_unverified_fails(self):
        with self.assertRaises(m.ReadinessHold):
            m.evaluate(runtime(owner_process_verified=False),stage(),None,public())

    def test_false_read_only_runtime_fails(self):
        with self.assertRaises(m.ReadinessHold):
            m.evaluate(runtime(read_only=False),stage(),None,public())

    def test_stage_patch_changed_fails(self):
        with self.assertRaises(m.ReadinessHold):
            m.evaluate(runtime(),stage(patch_bytes_match=False),None,public())

    def test_stage_wrong_source_count_fails(self):
        with self.assertRaises(m.ReadinessHold):
            m.evaluate(runtime(),stage(source_files=3),None,public())

    def test_stage_wrong_manifest_fails(self):
        with self.assertRaises(m.ReadinessHold):
            m.evaluate(runtime(),stage(stage_manifest_sha256="f"*64),None,public())

    def test_public_favorites_exposed_fails(self):
        with self.assertRaises(m.ReadinessHold):
            m.evaluate(runtime(),stage(),None,public(private_public_exposure=200))

    def test_https_not_200_fails(self):
        with self.assertRaises(m.ReadinessHold):
            m.evaluate(runtime(),stage(),None,public(public_https_health=502))

    def test_csp_and_nosniff_both_required(self):
        root=(200,{},{"Content-Security-Policy":"default-src 'self'",
                      "X-Content-Type-Options":"nosniff"})
        health=(200,{"status":"ok","mode":"public-demo","app_version":"phase8-public-demo"},{})
        hidden=(404,{},{})
        self.assertTrue(m.check_http(root,health,hidden)["public_security_headers_verified"])
        for headers in ({},{"Content-Security-Policy":"default-src 'self'"},
                        {"X-Content-Type-Options":"nosniff"}):
            with self.subTest(headers=headers),self.assertRaises(m.ReadinessHold):
                m.check_http((200,{},headers),health,hidden)

    def test_wrong_health_mode_fails(self):
        with self.assertRaises(m.ReadinessHold):
            m.check_http((200,{},{"Content-Security-Policy":"1","X-Content-Type-Options":"nosniff"}),
                         (200,{"status":"ok","mode":"private","app_version":"phase8-public-demo"},{}),
                         (404,{},{}))

    def test_https_network_errors_remain_hold(self):
        with patch.object(m,"urlopen",side_effect=OSError("network")):
            with self.assertRaises(m.ReadinessHold):
                m.public_fetch("/api/v1/health")

    def test_unknown_https_endpoints_never_requested(self):
        with self.assertRaisesRegex(m.ReadinessHold,"UNKNOWN_PUBLIC"):
            m.public_fetch("/api/v1/refresh")

    def test_sha_pin_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"mod.py";src.write_text("VALUE=3\n",encoding="utf8")
            with self.assertRaises(m.ReadinessHold):
                m.module(src,"0"*40)

    def test_module_loader_does_not_write_pycache(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"mod.py";src.write_text("VALUE=3\n",encoding="utf8")
            result=m.module(src,m.gitblob(src.read_bytes()))
            self.assertEqual(result.VALUE,3)
            self.assertFalse((src.parent/"__pycache__").exists())

    def test_no_mutating_owner_api_in_source(self):
        s=FILE.read_text(encoding="utf8")
        for needle in ("Start-ScheduledTask","Stop-ScheduledTask","Restart-Computer",
                       "subprocess.Popen(","write_bytes(","write_text(","unlink(",
                       "RegisterTask(","tailscale serve --bg"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle,s)

    def test_actual_cli_has_no_recover_or_sign_paths(self):
        with patch.object(m.sys,"argv",["gate","--recover"]):
            self.assertEqual(m.main(),2)
        with patch.object(m.sys,"argv",["gate","--issue-review"]):
            self.assertEqual(m.main(),2)


if __name__=="__main__":
    unittest.main()
