"""CMP20 signed V2 Task, fault recovery, launch no inherited pipes, safe fallback."""
from __future__ import annotations
import base64
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock,patch
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

ROOT=Path(__file__).resolve().parents[1]/"scripts"
def load(name):
    path=ROOT/name
    spec=importlib.util.spec_from_file_location(name.replace(".py",""),path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

v=load("cmp20_public_guarded_task_verify_v2.py")
g=load("cmp20_public_guarded_owner_v2.py")

def synthetic():
    keys={name:Ed25519PrivateKey.generate() for name in ("issuer","reviewer")}
    trust={"schema":v.TRUST_SCHEMA,"purpose":v.PURPOSE}
    for name,key in keys.items():
        public=key.public_key().public_bytes(serialization.Encoding.Raw,
                                              serialization.PublicFormat.Raw)
        trust[name+"_public_b64"]=base64.b64encode(public).decode()
    m=v.manifest_fields("a"*40,"b"*40)
    p={"schema":v.PACKET_SCHEMA,"statement":v.statement_for(m)}
    for name,key in keys.items():
        p[name+"_signature_b64"]=base64.b64encode(
            key.sign(v.canonical(p["statement"]))).decode()
    return trust,m,p

def taskinfo():
    return {
        "principal":v.OWNER_SID,"logon":"Interactive","runlevel":"Limited",
        "action_count":1,"exe":v.OWNER_PYTHON,
        "args":v.manifest_fields("0"*40,"0"*40)["task_argument"],
        "multi":"IgnoreNew","hard":False,"state":"Ready",
        "lastresult":0,"missed":0,
        "triggers":[
            {"type":"MSFT_TaskDailyTrigger","interval":"PT5M","duration":"P1D",
             "enabled":True},
            {"type":"MSFT_TaskLogonTrigger","interval":"","duration":"",
             "enabled":True}
        ]
    }

class GuardV2Tests(unittest.TestCase):
    def test_genuine_two_role_signature_pass(self):
        t,m,p=synthetic()
        result=v.verify_packet(t,m,p)
        self.assertEqual(result["status"],"PASS")
        self.assertFalse(result["existing_task_change_authority"])
        self.assertFalse(result["old_public_stop_authority"])
        self.assertFalse(result["os_reboot_authority"])

    def test_purpose_separate_from_v1_review_and_exec(self):
        self.assertNotEqual(v.PURPOSE,"legal-kb.cmp20.parallel-public-funnel-8443-owner-exec.v1")
        self.assertNotEqual(v.PURPOSE,"legal-kb.cmp20.owner-public-release-review-only.v1")
        self.assertEqual(v.TASK_NAME,"RinkaLegalKBPublicGuardedOnceV2")

    def test_cannot_reuse_v1_packet(self):
        t,m,p=synthetic();t["purpose"]="legal-kb.cmp20.parallel-public-funnel-8443-owner-exec.v1"
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_cannot_use_same_role_key(self):
        t,m,p=synthetic();t["reviewer_public_b64"]=t["issuer_public_b64"]
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_cannot_change_signed_source_blob(self):
        t,m,p=synthetic();m["guard_source_git_blob"]="c"*40
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_cannot_authorize_old_process_stop(self):
        t,m,p=synthetic();m["allow_stop_original_public"]=True
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_cannot_authorize_unrelated_task_change(self):
        t,m,p=synthetic();m["allow_modify_existing_task"]=True
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_cannot_authorize_reboot(self):
        t,m,p=synthetic();m["allow_windows_reboot"]=True
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_cannot_authorize_private_db_mutation(self):
        t,m,p=synthetic();m["allow_change_private_database"]=True
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_cannot_authorize_tailscale_reset(self):
        t,m,p=synthetic();m["allow_reset_tailscale"]=True
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_cannot_change_fixed_python_program(self):
        t,m,p=synthetic();m["task_guard_command"]=r"C:\Windows\System32\cmd.exe"
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_cannot_change_exact_signed_task_name(self):
        t,m,p=synthetic();m["task_name"]="RandomArbitraryTask"
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_cannot_change_funnel_to_private_port(self):
        t,m,p=synthetic();m["candidate_8879"]="http://127.0.0.1:8877"
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_corrupt_signature_rejected(self):
        t,m,p=synthetic();p["reviewer_signature_b64"]=p["issuer_signature_b64"]
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_unknown_packet_keys_rejected(self):
        t,m,p=synthetic();p["execute_other_command"]=True
        with self.assertRaises(v.GuardHold):
            v.verify_packet(t,m,p)

    def test_json_duplicate_rejected(self):
        with self.assertRaises(v.GuardHold):
            v.strict_json(b'{"scope":1,"scope":2}')

    def test_json_nan_rejected(self):
        with self.assertRaises(v.GuardHold):
            v.strict_json(b'{"scope":NaN}')

    def test_fixed_xml_contains_daily_and_logon_only(self):
        raw=g.task_xml(v)
        r=ET.fromstring(raw)
        t="http://schemas.microsoft.com/windows/2004/02/mit/task"
        self.assertEqual(len(r.findall(".//{"+t+"}CalendarTrigger")),1)
        self.assertEqual(len(r.findall(".//{"+t+"}LogonTrigger")),1)
        self.assertEqual(r.find(".//{"+t+"}Interval").text,"PT5M")
        self.assertEqual(r.find(".//{"+t+"}Duration").text,"P1D")
        self.assertEqual(r.find(".//{"+t+"}MultipleInstancesPolicy").text,"IgnoreNew")
        self.assertEqual(r.find(".//{"+t+"}AllowHardTerminate").text,"false")
        self.assertEqual(r.find(".//{"+t+"}ExecutionTimeLimit").text,"PT2M")
        self.assertEqual(r.find(".//{"+t+"}Command").text,v.OWNER_PYTHON)
        self.assertEqual(r.find(".//{"+t+"}Arguments").text,
                         v.manifest_fields("0"*40,"0"*40)["task_argument"])

    def test_exact_task_properties_pass(self):
        self.assertEqual(g.check_task(v,taskinfo())["state"],"Ready")

    def test_wrong_task_principal_rejected(self):
        i=taskinfo();i["principal"]="Admin"
        with self.assertRaises(g.GuardianHold):
            g.check_task(v,i)

    def test_wrong_task_action_rejected(self):
        i=taskinfo();i["args"]="--run arbitrary command"
        with self.assertRaises(g.GuardianHold):
            g.check_task(v,i)

    def test_task_hard_terminate_rejected(self):
        i=taskinfo();i["hard"]=True
        with self.assertRaises(g.GuardianHold):
            g.check_task(v,i)

    def test_task_duplicate_trigger_rejected(self):
        i=taskinfo();i["triggers"].append(i["triggers"][1])
        with self.assertRaises(g.GuardianHold):
            g.check_task(v,i)

    def test_task_interval_changed_rejected(self):
        i=taskinfo();i["triggers"][0]["interval"]="PT1M"
        with self.assertRaises(g.GuardianHold):
            g.check_task(v,i)

    def test_fixed_public_route_set(self):
        with self.assertRaises(g.GuardianHold):
            g.switch_route(g.OLD,"http://127.0.0.1:8877")

    def test_actual_detached_launch_does_not_capture_pipes(self):
        class FakeV:
            V1_LAUNCHER_SHA=g.sha(b"fake")
        run=MagicMock()
        run.returncode=0
        with patch.object(g,"safe_file",return_value=b"fake"),\
             patch.object(g,"verifier",return_value=FakeV()),\
             patch.object(g.subprocess,"run",return_value=run) as call,\
             patch.object(g,"candidate_ok",return_value=(True,1234)):
            result=g.launch_without_capture()
        self.assertEqual(result["launcher_returncode"],0)
        self.assertFalse(result["inherited_pipe_capture"])
        kw=call.call_args.kwargs
        self.assertEqual(kw["stdin"],subprocess.DEVNULL)
        self.assertEqual(kw["stdout"],subprocess.DEVNULL)
        self.assertEqual(kw["stderr"],subprocess.DEVNULL)
        self.assertFalse(kw["shell"])
        self.assertIsInstance(kw["timeout"],int)

    def test_detached_launcher_nonzero_fails(self):
        class FakeV: V1_LAUNCHER_SHA=g.sha(b"fake")
        run=MagicMock();run.returncode=3
        with patch.object(g,"safe_file",return_value=b"fake"),\
             patch.object(g,"verifier",return_value=FakeV()),\
             patch.object(g.subprocess,"run",return_value=run),\
             self.assertRaises(g.GuardianHold):
            g.launch_without_capture()

    def test_candidate_drill_does_not_stop_original_public(self):
        import inspect
        src=inspect.getsource(g.stop_candidate_only)
        self.assertIn("port_owner(8879)",src)
        self.assertNotIn("Stop-Process -Id 8878",src)

    def test_guardian_source_does_not_modify_private_db(self):
        raw=(ROOT/"cmp20_public_guarded_owner_v2.py").read_text()
        for token in ("DROP TABLE","ALTER TABLE","DELETE FROM",
                      "Restart-Computer","Stop-ScheduledTask",
                      "Stop-Process -Id 15900","tailscale serve reset"):
            with self.subTest(token=token):self.assertNotIn(token,raw)

    def test_require_signed_scope_before_register(self):
        import inspect
        src=inspect.getsource(g.register)
        self.assertIn("v.inspect()",src)
        self.assertIn("if known is not None",src)
        self.assertIn("check_task(v,known)",src)

    def test_guard_locks_concurrent_runs(self):
        import inspect
        src=inspect.getsource(g.exclusive)
        self.assertIn("LK_NBLCK",src)
        self.assertIn("LK_UNLCK",src)

    def test_unauthorized_cli_action_rejected(self):
        with patch.object(g.sys,"argv",["cmp20","--reboot"]):
            self.assertEqual(g.main(),2)

if __name__=="__main__":
    unittest.main()
