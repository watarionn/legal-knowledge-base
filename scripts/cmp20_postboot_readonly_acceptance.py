"""CMP-20 owner-only, read-only signed public guardian baseline/postboot acceptance.

No Task/process/Serve/OS/database mutations, logging, bytecode writes or
automatic recovery. This is an independent observation of the existing
purpose-scoped V2 signed release, not a new execution authority.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

HOST = "YWSHTMR"
TASK = "RinkaLegalKBPublicGuardedOnceV2"
RELEASE_ID = "cmp20-public-demo-guarded-once-owner-v2"
FQDN = "ywshtmr.tail8fd68c.ts.net:8443"
PUBLIC = "https://" + FQDN
ORIGINAL = "http://127.0.0.1:8878"
CANDIDATE = "http://127.0.0.1:8879"
PRIVATE = "http://127.0.0.1:8877"
SCHEMA = "legal-kb.cmp20.owner-postboot-readonly.v1"
OWNER_PYTHON = r"C:\Python314\python.exe"
POWER_SHELL = r"""
$ErrorActionPreference='Stop'
$t=Get-ScheduledTask -TaskName 'RinkaLegalKBPublicGuardedOnceV2' -ErrorAction Stop
$i=Get-ScheduledTaskInfo -TaskName 'RinkaLegalKBPublicGuardedOnceV2' -ErrorAction Stop
$xml=Export-ScheduledTask -TaskName 'RinkaLegalKBPublicGuardedOnceV2' -ErrorAction Stop
$boot=(Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime
$ls=@{}
foreach($port in @(8877,8878,8879)){
  $links=@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
  if($links.Count -ne 1){throw 'LISTENER_COUNT_HOLD'}
  $ownerPid=[int]$links[0].OwningProcess
  $p=Get-CimInstance Win32_Process -Filter ("ProcessId="+$ownerPid) -ErrorAction Stop
  if($null -eq $p){throw 'PROCESS_MISSING_HOLD'}
  $ls[[string]$port]=@{
    pid=$ownerPid
    name=[string]$p.Name
    started_utc=$p.CreationDate.ToUniversalTime().ToString('o')
  }
}
@{
  boot_utc=$boot.ToUniversalTime().ToString('o')
  name=[string]$t.TaskName
  state=[string]$t.State
  action=[string]$t.Actions[0].Execute
  arguments=[string]$t.Actions[0].Arguments
  logon_type=[string]$t.Principal.LogonType
  principal_user=[string]$t.Principal.UserId
  action_count=@($t.Actions).Count
  trigger_types=@($t.Triggers | ForEach-Object { $_.CimClass.CimClassName })
  multiple_instances=[string]$t.Settings.MultipleInstances
  allow_hard_terminate=[bool]$t.Settings.AllowHardTerminate
  logon_trigger=$xml.Contains('<LogonTrigger>')
  calendar_trigger=$xml.Contains('<CalendarTrigger>')
  interval_pt5m=$xml.Contains('<Interval>PT5M</Interval>')
  last_run_utc=$i.LastRunTime.ToUniversalTime().ToString('o')
  last_result=[int]$i.LastTaskResult
  missed_runs=[int]$i.NumberOfMissedRuns
  listeners=$ls
} | ConvertTo-Json -Depth 6 -Compress
"""


class Hold(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Hold(reason)


def utc(value: str) -> datetime:
    require(type(value) is str, "TIMESTAMP_MISSING")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Hold("TIMESTAMP_BAD") from None
    require(d.tzinfo is not None, "TIMESTAMP_NOT_UTC")
    return d.astimezone(timezone.utc)


def release_path() -> Path:
    local = os.environ.get("LOCALAPPDATA", "")
    require(bool(local), "LOCALAPPDATA_MISSING")
    return Path(local) / "RinkaMissionControl" / "releases" / RELEASE_ID


def json_command(args: list[str], timeout: int = 20) -> dict:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          check=False)
    require(proc.returncode == 0, "READONLY_COMMAND_FAILED")
    try:
        data = json.loads(proc.stdout)
    except (ValueError, UnicodeError):
        raise Hold("READONLY_OUTPUT_INVALID") from None
    require(type(data) is dict, "READONLY_OUTPUT_NOT_OBJECT")
    return data


def task_snapshot() -> dict:
    encoded = base64.b64encode(POWER_SHELL.encode("utf-16le")).decode("ascii")
    return json_command(["powershell.exe", "-NoProfile", "-NonInteractive",
                         "-EncodedCommand", encoded], timeout=25)


def signed_verifier(release: Path) -> dict:
    verifier = release / "cmp20_public_guarded_task_verify_v2.py"
    require(verifier.is_file() and not verifier.is_symlink(),
            "SIGNED_VERIFIER_MISSING")
    return json_command([OWNER_PYTHON, "-B", str(verifier), "--verify"], 25)


def serve_snapshot() -> dict:
    return json_command(["tailscale", "serve", "status", "--json"], 15)


def http_status(url: str, expected: int) -> dict:
    try:
        with urlopen(url, timeout=8) as reply:
            status = reply.status
            final = reply.geturl()
            headers = dict(reply.headers.items())
    except HTTPError as exc:
        status = exc.code
        final = exc.geturl()
        headers = {}
        exc.close()
    except (URLError, TimeoutError, OSError):
        raise Hold("HTTP_UNAVAILABLE") from None
    require(status == expected, "HTTP_STATUS_HOLD")
    require(final == url, "HTTP_UNEXPECTED_REDIRECT")
    return headers


def http_checks() -> dict:
    for base in (PRIVATE, ORIGINAL, CANDIDATE):
        http_status(base + "/api/v1/health", 200)
    headers = {k.lower(): v for k, v in http_status(PUBLIC + "/", 200).items()}
    http_status(PUBLIC + "/api/v1/health", 200)
    http_status(PUBLIC + "/api/v1/favorites", 404)
    require(bool(headers.get("content-security-policy")), "CSP_MISSING")
    require(headers.get("x-content-type-options", "").lower() == "nosniff",
            "NOSNIFF_MISSING")
    require(headers.get("x-frame-options", "").upper() == "DENY",
            "X_FRAME_MISSING")
    return {"public_root": 200, "public_health": 200,
            "public_private_favorites": 404, "private_health": 200,
            "old_health": 200, "candidate_health": 200,
            "security_headers": "PASS"}


def validate(task: dict, receipt: dict, signed: dict, serve: dict,
             now: datetime, phase: str, baseline_boot_utc: str | None) -> dict:
    boot = utc(task["boot_utc"])
    last = utc(task["last_run_utc"])
    checked = utc(receipt["checked_utc"])
    require(boot < now, "BOOT_IN_FUTURE")
    require(task.get("name") == TASK and task.get("state") == "Ready",
            "TASK_ID_OR_STATE_HOLD")
    release = release_path()
    expected_args = "-B " + str(release / "cmp20_public_guarded_owner_v2.py") + " --once"
    require(os.path.normcase(task.get("action", "")) == os.path.normcase(OWNER_PYTHON)
            and os.path.normcase(task.get("arguments", "")) ==
            os.path.normcase(expected_args), "TASK_ACTION_CHANGED")
    require(task.get("principal_user") == "watar"
            and task.get("action_count") == 1
            and sorted(task.get("trigger_types", [])) ==
            ["MSFT_TaskDailyTrigger", "MSFT_TaskLogonTrigger"],
            "TASK_OWNER_ACTION_OR_TRIGGER_COUNT_HOLD")
    require(task.get("logon_type") == "Interactive"
            and task.get("multiple_instances") == "IgnoreNew"
            and task.get("allow_hard_terminate") is False
            and task.get("logon_trigger") is True
            and task.get("calendar_trigger") is True
            and task.get("interval_pt5m") is True,
            "TASK_TRIGGERS_OR_POLICY_CHANGED")
    require(task.get("last_result") == 0 and task.get("missed_runs") == 0,
            "TASK_NATIVE_RESULT_HOLD")
    require(boot <= last <= checked <= now and
            (checked - last).total_seconds() <= 90 and
            (now - last).total_seconds() <= 900,
            "TASK_RECEIPT_NOT_FRESH_OR_MATCHED")
    require(signed.get("status") == "PASS"
            and signed.get("signed_release_and_prior_ed25519_proof") == "PASS"
            and signed.get("old_public_stop_authority") is False
            and signed.get("os_reboot_authority") is False,
            "V2_SIGNED_VERIFIER_HOLD")
    require(receipt.get("schema") == "legal-kb.cmp20.guarded-once-owner-receipt.v1"
            and receipt.get("status") == "PASS"
            and receipt.get("source_signed") is True
            and receipt.get("task_source_grant") == "V2_ED25519_TWO_ROLES"
            and receipt.get("owner_host") == HOST
            and receipt.get("old_public_8878") == "healthy"
            and receipt.get("new_public_8879") == "healthy"
            and receipt.get("private_8877") == "healthy"
            and receipt.get("public_route") == CANDIDATE
            and receipt.get("no_old_pid_kill") is True
            and receipt.get("no_os_reboot") is True,
            "RECEIPT_CONTENT_HOLD")
    listeners = task.get("listeners", {})
    for p in ("8877", "8878", "8879"):
        item = listeners.get(p, {})
        require(item.get("name", "").lower() == "pythonw.exe"
                and type(item.get("pid")) is int
                and item["pid"] > 0
                and boot <= utc(item["started_utc"]) <= now,
                "OWNED_LISTENER_IDENTITY_HOLD")
    require(receipt["old_public_pid"] == listeners["8878"]["pid"]
            and receipt["candidate_pid"] == listeners["8879"]["pid"],
            "RECEIPT_PID_MISMATCH")
    route = serve.get("Web", {}).get(FQDN, {}).get("Handlers", {}).get("/", {})
    require(route.get("Proxy") == CANDIDATE
            and serve.get("AllowFunnel", {}).get(FQDN) is True,
            "PUBLIC_ROUTE_OR_FUNNEL_CHANGED")
    if phase == "after-relogin":
        require(baseline_boot_utc is not None, "BASELINE_BOOT_REQUIRED")
        require(boot > utc(baseline_boot_utc), "NO_NEW_BOOT_PROVEN")
        require(last >= boot and checked >= boot, "NO_POSTBOOT_TICK_PROVEN")
    return {"status": "PASS", "schema": SCHEMA, "phase": phase,
            "boot_utc": boot.isoformat(),
            "native_last_run_utc": last.isoformat(),
            "receipt_checked_utc": checked.isoformat(),
            "receipt_sha256": None, "original_pid": listeners["8878"]["pid"],
            "candidate_pid": listeners["8879"]["pid"],
            "private_pid": listeners["8877"]["pid"],
            "signed_v2": "PASS", "native_task": "PASS",
            "http_tested_on": "owner-host-only",
            "reboot_since_baseline_proven": phase == "after-relogin",
            "every_five_minute_tick_proven": False,
            "owner_execution_authority_expanded": False}


def main() -> int:
    p = argparse.ArgumentParser()
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--baseline", action="store_true")
    group.add_argument("--after-relogin", action="store_true")
    p.add_argument("--baseline-boot-utc")
    a = p.parse_args()
    phase = "baseline" if a.baseline else "after-relogin"
    try:
        require(os.name == "nt" and os.environ.get("COMPUTERNAME", "").upper() == HOST,
                "WRONG_OWNER_HOST")
        require(a.baseline or bool(a.baseline_boot_utc), "BASELINE_BOOT_REQUIRED")
        now = datetime.now(timezone.utc)
        release = release_path()
        receipt_path = release / "last-guarded-once.json"
        require(receipt_path.is_file() and not receipt_path.is_symlink(),
                "LATEST_RECEIPT_MISSING")
        raw = receipt_path.read_bytes()
        require(0 < len(raw) < 8192, "LATEST_RECEIPT_SIZE_HOLD")
        receipt = json.loads(raw)
        result = validate(task_snapshot(), receipt, signed_verifier(release),
                          serve_snapshot(), now, phase, a.baseline_boot_utc)
        result["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
        result["http"] = http_checks()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Hold, OSError, ValueError, KeyError, TypeError,
            subprocess.SubprocessError) as exc:
        reason = str(exc) if isinstance(exc, Hold) else "READONLY_OBSERVATION_FAILED"
        print(json.dumps({"schema": SCHEMA, "status": "HOLD",
                          "phase": phase, "reason": reason}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
