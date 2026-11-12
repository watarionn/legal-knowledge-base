"""Independent CMP20 headless V3 owner post-cutover acceptance, read-only.

Checks the ACTUAL native 5-minute V3 Task, exact two-role signature and fresh
bound receipt. Never creates keys, schedules Tasks, starts services or changes
Tailscale Serve. Not a substitute for iPhone/outside-network user acceptance.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys

RELEASE = Path(os.environ.get("LOCALAPPDATA", "")) / "RinkaMissionControl" / "releases" / "cmp20-headless-guard-owner-v3"
PREBOOT = datetime.fromisoformat("2026-11-10T05:24:48.5000000+00:00")
MAX_RECEIPT_BYTES = 8192

class AcceptanceHold(ValueError):
    pass

def need(test, msg):
    if not test:
        raise AcceptanceHold(msg)

def utc(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        raise AcceptanceHold("OWNER_UTC_INVALID") from None
    need(dt.tzinfo is not None, "OWNER_UTC_MISSING_OFFSET")
    return dt.astimezone(timezone.utc)

def bound_receipt(*, boot_utc: str, last_utc: str,
                  last_result: int, missed: int,
                  receipt: dict, now_utc: str) -> dict:
    boot, last, now = map(utc, (boot_utc, last_utc, now_utc))
    need(boot > PREBOOT, "OWNER_NO_NEW_BOOT")
    need(last > boot and last <= now + timedelta(seconds=20),
         "OWNER_TASK_NOT_AFTER_BOOT")
    need(last_result == 0 and missed == 0,
         "OWNER_NATIVE_V3_TASK_NOT_PASS")
    need(type(receipt) is dict and
         receipt.get("schema") == "legal-kb.cmp20.headless-v3-tick.v1" and
         receipt.get("status") == "PASS" and
         receipt.get("task") == "RinkaLegalKBPublicGuardedOnceV3" and
         receipt.get("source_signed") is True and
         receipt.get("v2_immutable_ed25519") is True and
         receipt.get("pythonw_headless") is True and
         receipt.get("old_public_stop") is False and
         receipt.get("mutated_other_task") is False and
         receipt.get("did_reboot") is False and
         receipt.get("private_8877_healthy") is True and
         receipt.get("old_public_8878_healthy") is True and
         receipt.get("candidate_8879_healthy") is True and
         receipt.get("public_https_8443_healthy") is True and
         receipt.get("public_route") == "http://127.0.0.1:8879",
         "OWNER_V3_RECEIPT_IDENTITY_NOT_PASS")
    stamp = utc(receipt["checked_utc"])
    need(last - timedelta(seconds=10) <= stamp <=
         last + timedelta(seconds=120),
         "OWNER_V3_RECEIPT_NOT_BOUND_TO_NATIVE_TICK")
    need(timedelta(0) <= now - stamp <= timedelta(minutes=12),
         "OWNER_V3_RECEIPT_STALE")
    return {
        "boot_utc": boot.isoformat(),
        "last_natural_tick_utc": last.isoformat(),
        "receipt_checked_utc": stamp.isoformat(),
        "new_boot_proven": True,
        "native_task_pass": True,
        "matching_receipt_pass": True,
    }

def owner_witness() -> dict:
    need(os.name == "nt" and os.environ.get("COMPUTERNAME", "").upper()
         == "YWSHTMR" and os.environ.get("USERNAME", "").casefold() == "watar",
         "OWNER_WINDOWS_ONLY")
    need(RELEASE.is_dir() and not RELEASE.is_symlink(),
         "OWNER_RELEASE_MISSING")
    sys.path.insert(0, str(RELEASE))
    import cmp20_headless_v3_verify as signed
    import cmp20_headless_v3_guard as guard
    need(signed.RELEASE == RELEASE, "OWNER_V3_RELEASE_PATH_CHANGED")
    proof = signed.verify()
    need(proof["status"] == "PASS" and
         proof["two_distinct_ed25519_roles"] is True and
         proof["prior_v2_signature"] == "PASS",
         "OWNER_V3_SIGNATURE_FAILED")
    prior = guard.source_pinned(guard.V2, signed.V2_GUARD_BLOB)
    with guard.invisible_children():
        old = guard.task_info(prior, signed.OLD_TASK)
        new = guard.task_info(prior, signed.TASK_NAME)
        guard.checked_old_task(old)
        guard.check_new_task(new, require_ready=True)
        shell = (
            "$ErrorActionPreference='Stop';"
            "$os=Get-CimInstance Win32_OperatingSystem;"
            "$task=Get-ScheduledTaskInfo -TaskName '" + signed.TASK_NAME + "';"
            "[pscustomobject]@{boot_utc=$os.LastBootUpTime.ToUniversalTime().ToString('o');"
            "last_utc=$task.LastRunTime.ToUniversalTime().ToString('o');"
            "last_result=[int]$task.LastTaskResult;"
            "missed=[int]$task.NumberOfMissedRuns;"
            "now_utc=(Get-Date).ToUniversalTime().ToString('o')"
            "}|ConvertTo-Json -Compress"
        )
        clock = json.loads(prior.shell(shell, timeout=25))
        path = RELEASE / "last-pass.json"
        need(path.is_file() and not path.is_symlink() and
             0 < path.stat().st_size <= MAX_RECEIPT_BYTES,
             "OWNER_V3_RECEIPT_MISSING")
        raw = path.read_bytes()
        receipt = signed.strict_json(raw)
        outcome = bound_receipt(receipt=receipt, **clock)
        old_public = prior.require_old_and_private()
        healthy, candidate = prior.candidate_ok()
        need(healthy and candidate is not None and
             old_public == receipt["old_public_pid"] and
             candidate == receipt["candidate_pid"],
             "OWNER_V3_RUNTIME_PIDS_CHANGED")
        need(prior.proxy(prior.current_route()) == prior.NEW,
             "OWNER_V3_PUBLIC_ROUTE_CHANGED")
        prior.https_public_pass()
    return {
        "schema": "legal-kb.cmp20.headless-v3-owner-readonly.v1",
        "status": "PASS", "phase": "after-cutover",
        "read_only": True, "windows_owner": "YWSHTMR",
        "source_signed": True, "two_distinct_ed25519_roles": True,
        "v2_immutable_signature": True, "headless_pythonw": True,
        "public_local_https_and_private_isolation": "PASS",
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "old_public_pid": old_public, "candidate_pid": candidate,
        "no_os_reboot_performed": True, "task_action_unchanged": True,
        "external_iphone_acceptance": "NOT_CHECKED",
        "canonical_campaign_status": "SEPARATE_GATE",
        **outcome,
    }

def main() -> int:
    if sys.argv[1:] != ["--after-cutover"]:
        print(json.dumps({"status": "HOLD", "reason": "V3_READONLY_FIXED_MODE"}))
        return 2
    try:
        print(json.dumps(owner_witness(), sort_keys=True))
        return 0
    except (AcceptanceHold, ValueError, OSError, TypeError, KeyError,
            RuntimeError, ImportError) as error:
        why = str(error) if isinstance(error, AcceptanceHold) else "V3_OWNER_READONLY_HOLD"
        print(json.dumps({"status": "HOLD", "reason": why}, sort_keys=True))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
