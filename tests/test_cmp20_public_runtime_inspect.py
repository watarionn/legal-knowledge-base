"""CMP20 nonmutating public demo runtime inspection tests."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "scripts" / "cmp20_public_runtime_inspect.py"
spec=importlib.util.spec_from_file_location("cmp20_guard",SRC)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def task(listeners=None,state="Ready"):
    return {"task_name":m.TASK_NAME,"task_state":state,
            "task_executable":r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "task_args":'-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' +
                       str(m.LAUNCHER) + '"',
            "listener":listeners if listeners is not None else []}

def listener(ip="127.0.0.1",name="pythonw.exe",cmd=None):
    return {"ip":ip,"pid":1234,"name":name,
            "cmd":'"C:\\Python314\\pythonw.exe" "'+(cmd or str(m.SCRIPT))+'"'}

PUBLIC={"status":"ok","mode":"public-demo","app_version":"phase8-public-demo"}
PRIVATE={"status":"ok"}

class PublicGuardTests(unittest.TestCase):
    def reject(self,t,p=None,pr=PRIVATE,reason=None):
        with self.assertRaises(m.InspectionHold) as x:
            m.classify(t,p,pr)
        if reason:
            self.assertIn(reason,str(x.exception))
    def test_known_public_running_is_healthy(self):
        r=m.classify(task([listener()]), PUBLIC,PRIVATE)
        self.assertEqual(r["status"],"HEALTHY")
        self.assertFalse(r["recovery_candidate"])
    def test_stopped_public_ready_is_candidate_without_execution(self):
        r=m.classify(task(),None,PRIVATE)
        self.assertEqual(r["status"],"RECOVERY_CANDIDATE_NOT_AUTHORIZED")
        self.assertFalse(r["public_health_verified"])
    def test_wrong_task_action(self):
        t=task();t["task_args"]="--unknown"
        self.reject(t,reason="OWNER_TASK_ACTION_CHANGED")
    def test_task_disabled(self):
        self.reject(task(state="Disabled"),reason="OWNER_TASK_DISABLED_OR_UNKNOWN")
    def test_running_task_with_missing_child(self):
        self.reject(task(state="Running"),reason="TASK_RUNNING_WITHOUT_LISTENER")
    def test_multiple_listener_hold(self):
        self.reject(task([listener(),listener()]),reason="PUBLIC_PORT_MULTIPLE_LISTENERS")
    def test_other_process_claims_public_port(self):
        self.reject(task([listener(name="nginx.exe")]),PUBLIC,reason="PUBLIC_PORT_OTHER_OWNER")
    def test_public_process_wrong_script(self):
        self.reject(task([listener(cmd=r"C:\tmp\003_web_server.py")]),PUBLIC,
                    reason="PUBLIC_PORT_OTHER_OWNER")
    def test_public_binds_unexpected_interface(self):
        self.reject(task([listener(ip="0.0.0.0")]),PUBLIC,reason="PUBLIC_PORT_WRONG_BINDING")
    def test_public_unhealthy_must_not_restart(self):
        self.reject(task([listener()]),None,reason="PUBLIC_PROCESS_PRESENT_BUT_UNHEALTHY")
    def test_private_down_is_hold(self):
        self.reject(task(),pr=None,reason="PRIVATE_APP_NOT_HEALTHY")
    def test_private_status_not_ok(self):
        self.reject(task(),pr={"status":"down"},reason="PRIVATE_APP_NOT_HEALTHY")
    def test_public_health_without_port_is_hold(self):
        self.reject(task(),PUBLIC,reason="PUBLIC_HEALTH_WITHOUT_VERIFIABLE_LISTENER")
    def test_wrong_public_mode_is_hold(self):
        self.reject(task([listener()]),{"status":"ok","mode":"private"},
                    reason="PUBLIC_PROCESS_PRESENT_BUT_UNHEALTHY")
    def test_wrong_public_version_is_hold(self):
        self.reject(task([listener()]),{"status":"ok","mode":"public-demo",
                                      "app_version":"unexpected"},
                    reason="PUBLIC_PROCESS_PRESENT_BUT_UNHEALTHY")
    def test_empty_task_executable_rejected(self):
        t=task();t["task_executable"]=""
        self.reject(t,reason="OWNER_TASK_ACTION_CHANGED")
    def test_extra_task_args_launcher_duplication_rejected(self):
        t=task();t["task_args"]+=str(m.LAUNCHER)
        self.reject(t,reason="OWNER_TASK_ACTION_CHANGED")
    def test_inspect_does_not_perform_action(self):
        with patch.object(m,"owner_files",return_value={"source_git_head_pinned":True,
                                                        "launcher_sha256_pinned":True}),\
             patch.object(m,"windows_task_and_port",return_value=task([listener()])),\
             patch.object(m,"serve_proxy",return_value={"funnel_target_pinned":True}),\
             patch.object(m,"get_health",side_effect=[PUBLIC,PRIVATE]),\
             patch.object(m,"command") as run:
            got=m.inspect()
            self.assertTrue(got["read_only"])
            self.assertFalse(got["task_triggered"])
            self.assertFalse(got["owner_execution_authority"])
            self.assertFalse(got["process_terminated"])
            run.assert_not_called()
    def test_unauthorized_cli_never_inspects(self):
        with patch.object(m.sys,"argv",["guard","--recover"]),\
             patch.object(m,"inspect") as op:
            self.assertEqual(m.main(),2)
            op.assert_not_called()

if __name__=="__main__":
    unittest.main()
