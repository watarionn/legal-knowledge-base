"""CMP-20 V3 windowless, fail-closed public-only recovery worker.

The V3 permit independently signs THIS code, the verifier and installer. The
original V2 signed guardian is imported as an immutable, exact-blob library:
no V2 source edits or Task-authentication monkeypatch. The bounded V2 public
recovery primitives are reused under its SAME existing byte-lock. V3 receipt
is separate and explicitly identifies the new task/signer; no fake V2 tick.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import cmp20_headless_v3_verify as grant

RELEASE = grant.RELEASE
TASK = grant.TASK_NAME
OLD_TASK = grant.OLD_TASK
OWNER_PYTHON = grant.PYTHONW
V2 = grant.V2_RELEASE / "cmp20_public_guarded_owner_v2.py"

class HeadlessHold(ValueError):
    pass

def require(value: bool, reason: str):
    if not value:
        raise HeadlessHold(reason)

def source_pinned(path: Path, expected: str):
    require(grant.blob(grant.safe_file(path)) == expected,
            "V3_PINNED_SOURCE_CHANGED")
    spec = importlib.util.spec_from_file_location("cmp20_v3_prior_signed_core", path)
    require(spec is not None and spec.loader is not None,
            "V3_PRIOR_CORE_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    prior = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prior
    return module

@contextmanager
def invisible_children():
    """Only in this single-use owner process: suppress ALL child console windows.

    Prior signed V2 subprocess.run calls do not set CREATE_NO_WINDOW, so using
    pythonw alone would NOT prove that their PowerShell children stayed hidden.
    Bound the adapter to the synchronous guardian scope; restore Popen after.
    """
    original = subprocess.Popen
    def launch(*args, **kwargs):
        if os.name == "nt":
            kwargs["creationflags"] = (
                kwargs.get("creationflags", 0)
                | subprocess.CREATE_NO_WINDOW
            )
            startup = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            kwargs["startupinfo"] = startup
        return original(*args, **kwargs)
    subprocess.Popen = launch
    try:
        yield
    finally:
        subprocess.Popen = original

def task_info(v2, name: str) -> dict:
    require(name in (TASK, OLD_TASK), "V3_TASK_ID_OUTSIDE_SCOPE")
    query = (
        "$ErrorActionPreference='Stop';"
        "$t=Get-ScheduledTask -TaskName '" + name + "' -ErrorAction Stop;"
        "$i=Get-ScheduledTaskInfo -TaskName '" + name + "' -ErrorAction Stop;"
        "[pscustomobject]@{state=[string]$t.State;"
        "owner=[string]$t.Principal.UserId;"
        "logon=[string]$t.Principal.LogonType;"
        "level=[string]$t.Principal.RunLevel;"
        "action_count=@($t.Actions).Count;"
        "execute=[string]$t.Actions[0].Execute;"
        "args=[string]$t.Actions[0].Arguments;"
        "cwd=[string]$t.Actions[0].WorkingDirectory;"
        "overlap=[string]$t.Settings.MultipleInstances;"
        "hard=[bool]$t.Settings.AllowHardTerminate;"
        "on_demand=[bool]$t.Settings.AllowStartOnDemand;"
        "trigger_count=@($t.Triggers).Count;"
        "triggers=@($t.Triggers|ForEach-Object{[pscustomobject]@{"
        "type=$_.CimClass.CimClassName;"
        "enabled=[bool]$_.Enabled;"
        "interval=[string]$_.Repetition.Interval;"
        "duration=[string]$_.Repetition.Duration}});"
        "last=[string]$i.LastRunTime;"
        "result=[int]$i.LastTaskResult"
        "}|ConvertTo-Json -Depth 5 -Compress"
    )
    return json.loads(v2.shell(query, timeout=25))

def check_new_task(current: dict, require_ready: bool) -> None:
    require(current.get("owner") in ("watar", grant.OWNER_SID)
            and current.get("logon") == "Interactive"
            and current.get("level") == "Limited"
            and current.get("action_count") == 1
            and current.get("execute", "").casefold() == OWNER_PYTHON.casefold()
            and current.get("args") == grant.ARGUMENTS
            and current.get("cwd") == str(RELEASE)
            and current.get("overlap") == "IgnoreNew"
            and current.get("hard") is False
            and current.get("on_demand") is False,
            "V3_TASK_ACTION_OR_OWNER_CHANGED")
    triggers = current.get("triggers")
    require(isinstance(triggers, list) and len(triggers) == 2,
            "V3_TRIGGER_COUNT_CHANGED")
    types = {t.get("type") for t in triggers}
    require(types == {"MSFT_TaskLogonTrigger", "MSFT_TaskDailyTrigger"}
            and all(t.get("enabled") is True for t in triggers),
            "V3_TRIGGERS_CHANGED")
    daily = next(t for t in triggers if t["type"] == "MSFT_TaskDailyTrigger")
    require(daily.get("interval") == "PT5M"
            and daily.get("duration") == "P1D",
            "V3_5MIN_INTERVAL_CHANGED")
    if require_ready:
        require(current.get("state") in ("Ready", "Running"),
                "V3_TASK_NOT_ENABLED")

def checked_old_task(old: dict) -> None:
    require(old.get("owner") in ("watar", grant.OWNER_SID)
            and old.get("logon") == "Interactive"
            and old.get("level") == "Limited"
            and old.get("action_count") == 1
            and old.get("execute", "").casefold() == grant.PYTHONW.casefold()
            and old.get("args") == grant.OLD_ACTION
            and old.get("overlap") == "IgnoreNew"
            and old.get("hard") is False
            and old.get("trigger_count") == 2,
            "V3_PRIOR_V2_TASK_PREIMAGE_CHANGED")
    require(old.get("state") == "Disabled", "V3_PRIOR_V2_TASK_NOT_DISABLED")

def persist_receipt(data: dict, suffix: str):
    require(suffix in ("last-pass.json", "last-hold.json"),
            "V3_RECEIPT_SUFFIX_OUTSIDE_SCOPE")
    wire = grant.canonical(data)
    require(len(wire) < 8192 and not RELEASE.is_symlink(),
            "V3_RECEIPT_UNSAFE")
    path = RELEASE / suffix
    new = RELEASE / (suffix + ".new")
    require(not path.is_symlink() and not new.exists(),
            "V3_PREVIOUS_WRITE_INCOMPLETE")
    with new.open("xb") as handle:
        handle.write(wire)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(new, path)

def one_tick() -> dict:
    signed = grant.verify()
    require(signed.get("status") == "PASS", "V3_SIGNED_GRANT_HOLD")
    v2 = source_pinned(V2, grant.V2_GUARD_BLOB)
    with invisible_children():
        old = task_info(v2, OLD_TASK)
        actual = task_info(v2, TASK)
        checked_old_task(old)
        check_new_task(actual, require_ready=True)
        with v2.exclusive():
            original_pid = v2.require_old_and_private()
            route = v2.proxy(v2.current_route())
            require(route in (v2.OLD, v2.NEW),
                    "V3_FALLBACK_TARGET_UNAPPROVED")
            healthy, pid = v2.candidate_ok()
            recovered = False
            fallback = False
            if not healthy:
                if route == v2.NEW:
                    v2.switch_route(v2.NEW, v2.OLD)
                    fallback = True
                # No arbitrary or forceful stop of an unhealthy listener.
                require(v2.port_owner(8879) is None,
                        "V3_CANDIDATE_OCCUPIED_REQUIRES_SEPARATE_GRANT")
                new = v2.launch_without_capture()
                pid = new["candidate_pid"]
                recovered = True
                if route == v2.NEW:
                    v2.switch_route(v2.OLD, v2.NEW)
            require(v2.port_owner(8878)["pid"] == original_pid,
                    "V3_ORIGINAL_PUBLIC_PID_CHANGED")
            healthy, actual_pid = v2.candidate_ok()
            require(healthy and actual_pid == pid,
                    "V3_CANDIDATE_IDENTITY_CHANGED")
            v2.require_old_and_private()
            require(v2.proxy(v2.current_route()) == route,
                    "V3_ROUTE_NOT_RESTORED")
            v2.https_public_pass()
            result = {
                "schema": "legal-kb.cmp20.headless-v3-tick.v1",
                "status": "PASS",
                "signed_grant": grant.PURPOSE,
                "source_signed": True,
                "v2_immutable_ed25519": True,
                "pythonw_headless": True,
                "checked_utc": datetime.now(timezone.utc).isoformat(),
                "task": TASK,
                "candidate_recovered": recovered,
                "public_fallback_used": fallback,
                "candidate_pid": actual_pid,
                "old_public_pid": original_pid,
                "public_route": route,
                "private_8877_healthy": True,
                "old_public_8878_healthy": True,
                "candidate_8879_healthy": True,
                "public_https_8443_healthy": True,
                "did_reboot": False,
                "old_public_stop": False,
                "mutated_other_task": False,
            }
            persist_receipt(result, "last-pass.json")
            return result

def main() -> int:
    if sys.argv[1:] != ["--once"]:
        return 2
    try:
        report = one_tick()
        if sys.stdout is not None:
            print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as error:
        # A windowless task has no reliable console, so write bounded, private
        # diagnostic. Never persist exception messages with possible secrets.
        try:
            persist_receipt({
                "schema": "legal-kb.cmp20.headless-v3-hold.v1",
                "status": "HOLD",
                "error_kind": type(error).__name__,
                "checked_utc": datetime.now(timezone.utc).isoformat(),
                "task": TASK,
            }, "last-hold.json")
        except (OSError, ValueError):
            pass
        if sys.stdout is not None:
            print(json.dumps({"status": "HOLD",
                              "error_kind": type(error).__name__}))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
