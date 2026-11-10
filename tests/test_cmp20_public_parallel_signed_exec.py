"""CMP20 exact signed public parallel cutover gate, no owner writes in tests."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

DIR=Path(__file__).resolve().parents[1]/"scripts"


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,DIR/path)
    o=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(o)
    return o


v=load("cmp20_public_parallel_exec_verify.py","cmp20_exec_verify")
a=load("cmp20_public_parallel_owner_action.py","cmp20_action")
o=load("cmp20_public_parallel_overlay.py","cmp20_overlay")
s=load("cmp20_public_parallel_exec_signer.py","cmp20_exec_signer")


def synthetic():
    keys={name:Ed25519PrivateKey.generate() for name in ("issuer","reviewer")}
    trust={"schema":v.TRUST_SCHEMA,"purpose":v.PURPOSE}
    for name,key in keys.items():
        pub=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        import base64
        trust[name+"_public_b64"]=base64.b64encode(pub).decode()
    manifest=v.manifest_fields("1"*40,"2"*40)
    statement=v.statement_for(manifest)
    packet={"schema":v.PACKET_SCHEMA,"statement":statement}
    import base64
    for name,key in keys.items():
        packet[name+"_signature_b64"]=base64.b64encode(key.sign(v.canonical(statement))).decode()
    return trust,manifest,packet


class CMP20SignedParallelTests(unittest.TestCase):
    def test_positive_signed_execution_scope(self):
        t,m,p=synthetic()
        x=v.verify_packet(t,m,p)
        self.assertEqual(x["status"],"PASS")
        self.assertFalse(x["old_public_stop_allowed"])
        self.assertFalse(x["owner_os_reboot_allowed"])
        self.assertFalse(x["windows_task_change_allowed"])
        self.assertEqual(x["authorized_actions"],v.ALLOWED)

    def test_review_keys_are_distinct_purpose(self):
        self.assertNotEqual(v.PURPOSE,v.REVIEW_PURPOSE)
        self.assertEqual(s.CONSENT["issue-execution"],
                         "ISSUE CMP20 PUBLIC PARALLEL EXECUTION ONLY PACKET")

    def test_wrong_review_purpose_rejected(self):
        t,m,p=synthetic()
        t["purpose"]=v.REVIEW_PURPOSE
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_cannot_grant_old_public_stop(self):
        t,m,p=synthetic();m["old_public_process_stop_allowed"]=True
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_cannot_grant_os_reboot(self):
        t,m,p=synthetic();m["owner_os_reboot_allowed"]=True
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_cannot_grant_windows_task_edit(self):
        t,m,p=synthetic();m["windows_task_change_allowed"]=True
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_cannot_grant_private_db_access(self):
        t,m,p=synthetic();m["private_8877_or_postgres_change_allowed"]=True
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_cannot_grant_funnel_reset(self):
        t,m,p=synthetic();m["funnel_reset_allowed"]=True
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_cannot_change_funnel_destination(self):
        t,m,p=synthetic();m["candidate_public_target"]="http://127.0.0.1:8877"
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_cannot_swap_source_after_signature(self):
        t,m,p=synthetic();m["owner_action_git_blob"]="9"*40
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_corrupted_signed_statement_rejected(self):
        t,m,p=synthetic();p["statement"]["approval_scope"]="EXECUTE_ARBITRARY"
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_signature_wrong_signer_rejected(self):
        t,m,p=synthetic()
        p["issuer_signature_b64"]=p["reviewer_signature_b64"]
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_duplicate_roles_rejected(self):
        t,m,p=synthetic();t["reviewer_public_b64"]=t["issuer_public_b64"]
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_packet_extra_field_rejected(self):
        t,m,p=synthetic();p["arbitrary_start"]=True
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_trust_extra_field_rejected(self):
        t,m,p=synthetic();t["something"]=True
        with self.assertRaises(v.ExecutionHold):
            v.verify_packet(t,m,p)

    def test_signer_exact_action_and_overlay_sha_binding(self):
        self.assertEqual(s.ACTION_BLOB,
                         a.gitblob((DIR/"cmp20_public_parallel_owner_action.py").read_bytes()))
        self.assertEqual(s.OVERLAY_BLOB,
                         o.git_blob((DIR/"cmp20_public_parallel_overlay.py").read_bytes()))
        self.assertEqual(a.OVERLAY_BLOB,s.OVERLAY_BLOB)
        self.assertEqual(a.EXEC_VERIFIER_BLOB,
                         v.gitblob((DIR/"cmp20_public_parallel_exec_verify.py").read_bytes()))

    def test_no_untrusted_exec_verifier_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"m.py"
            path.write_text("VALUE=9\n")
            with self.assertRaises(a.CutoverHold):
                a.pinned_module(path,"f"*40)

    def test_exact_launcher_transform(self):
        # A source fixture exercises precisely all seven required patch anchors.
        text=r"""$logDir = Join-Path $runtime 'logs'
$env:LEGAL_KB_PUBLIC_DEMO = '1'
$env:LEGAL_KB_PORT = '8878'
$listener = Get-NetTCPConnection -State Listen -LocalPort 8878
if ($owner.CommandLine -notlike '*003_web_server.py*') {throw 'other'}
$proc = Start-Process -ArgumentList (Join-Path $app 'implementation\phase7\003_web_server.py')
Set-Content -Path (Join-Path $runtime 'public-demo.pid') -Value $proc.Id
$h = Invoke-RestMethod -Uri 'http://127.0.0.1:8878/api/v1/health'
"""
        output=a.transformed_launcher(text.encode()).decode()
        self.assertIn("-LocalPort 8879",output)
        self.assertIn("$env:LEGAL_KB_PORT = '8879'",output)
        self.assertIn("PYTHONDONTWRITEBYTECODE",output)
        self.assertIn("cmp20_public_parallel_overlay.py",output)
        self.assertNotIn("http://127.0.0.1:8878/api/v1/health",output)

    def test_launcher_transform_fails_on_unknown_original(self):
        with self.assertRaises(a.CutoverHold):
            a.transformed_launcher(b"$env:LEGAL_KB_PORT = '8878'\n")

    def test_rollback_does_not_require_new_worker(self):
        # The action must permit reverting to 8878 even after a 8879 crash.
        import inspect
        source=inspect.getsource(a.change_route)
        section=source.split("changed=copy.deepcopy(before)")[0]
        self.assertIn("if target==NEW_TARGET:",section)

    def test_overlay_never_runs_as_private(self):
        with patch.object(o.os,"name","nt"), \
             patch.dict(o.os.environ,{"COMPUTERNAME":"YWSHTMR",
                                      "LEGAL_KB_PUBLIC_DEMO":"0",
                                      "LEGAL_KB_PORT":"8879",
                                      "LEGAL_KB_HOST":"127.0.0.1"}), \
             self.assertRaises(RuntimeError):
            o.source_bytes()

    def test_overlay_never_changes_old_source(self):
        import inspect
        text=inspect.getsource(o)
        self.assertNotIn("write_bytes(",text)
        self.assertNotIn("os.remove(",text)
        self.assertNotIn("subprocess.Popen(",text)

    def test_no_broad_tailscale_reset(self):
        import inspect
        source=inspect.getsource(a)
        self.assertNotIn('"reset"',source)
        self.assertNotIn("Stop-Process",source)
        self.assertNotIn("Restart-Computer",source)

    def test_cli_unknown_action_rejected(self):
        with patch.object(a.sys,"argv",["owner_action","--run-arbitrary"]):
            self.assertEqual(a.main(),2)

    def test_json_duplicate_key_fails_closed(self):
        with self.assertRaises(v.ExecutionHold):
            v.strict_json(b'{"a":1,"a":2}')

    def test_json_nan_fails_closed(self):
        with self.assertRaises(v.ExecutionHold):
            v.strict_json(b'{"a":NaN}')

    def test_public_https_security_boundary_checks_private_route(self):
        from email.message import Message
        from unittest.mock import MagicMock
        from urllib.error import HTTPError
        h=Message()
        h["Content-Security-Policy"]="default-src 'self'"
        h["X-Content-Type-Options"]="nosniff"
        h["X-Frame-Options"]="DENY"
        root=MagicMock()
        root.status=200
        root.headers=h
        root.__enter__.return_value=root
        private=HTTPError("https://x/api/v1/favorites",404,"Not Found",{},None)
        with patch.object(a,"urlopen",side_effect=[root,private]) as called:
            a.check_public_https_security_boundary()
            self.assertEqual(called.call_count,2)

    def test_public_https_security_boundary_rejects_missing_csp(self):
        from email.message import Message
        from unittest.mock import MagicMock
        h=Message()
        h["X-Content-Type-Options"]="nosniff"
        h["X-Frame-Options"]="DENY"
        root=MagicMock()
        root.status=200
        root.headers=h
        root.__enter__.return_value=root
        with patch.object(a,"urlopen",return_value=root),\
             self.assertRaises(a.CutoverHold):
            a.check_public_https_security_boundary()

    def test_public_https_security_boundary_rejects_exposed_private_route(self):
        from email.message import Message
        from unittest.mock import MagicMock
        h=Message()
        h["Content-Security-Policy"]="default-src 'self'"
        h["X-Content-Type-Options"]="nosniff"
        h["X-Frame-Options"]="DENY"
        root=MagicMock()
        root.status=200
        root.headers=h
        root.__enter__.return_value=root
        private=MagicMock()
        private.status=200
        private.__enter__.return_value=private
        with patch.object(a,"urlopen",side_effect=[root,private]),\
             self.assertRaises(a.CutoverHold):
            a.check_public_https_security_boundary()

    def test_owner_stage_manifest_scope_fixed(self):
        x=a.output_manifest(b"a",b"b",b"c")
        self.assertTrue(x["no_task_registration_or_reboot"])
        self.assertTrue(x["original_public_8878_process_must_remain_running"])
        self.assertEqual(x["new_target"],a.NEW_TARGET)


if __name__=="__main__":
    unittest.main()
