"""CMP-20 headless V3 owner 24h elapsed endurance acceptance (read-only).

This gate does NOT assert every unobserved PT5M invocation succeeded.
Uses the already-reviewed owner V3 read-only runtime acceptance and independently
signed, immutable V3 fault drill + finish receipts. It cannot grant or execute
new Task, signer, service, reboot, route, or campaign authority.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

BASE = Path(os.environ.get("LOCALAPPDATA", "")) / "RinkaMissionControl"
FINISH_RELEASE = BASE / "releases" / "cmp20-v3-candidate-finish-owner-v2"
FINISH_SIGNED_VERIFIER = FINISH_RELEASE / "cmp20_v3_finish_verify_v2.py"
FINISH_RESULT = FINISH_RELEASE / "finish-result.json"
OWNER_ACCEPTANCE = Path(__file__).resolve().parent / "cmp20_headless_v3_owner_acceptance_readonly.py"
OWNER_ACCEPTANCE_BLOB = "4e9070b6510dbb381b1d37aba829e69c54d897c4"
FINISH_VERIFIER_BLOB = "a02dda6159030c8fa99221ec613b2d76a754a19c"
FINISH_RESULT_SHA256 = "16e95e8a06c48dc7e5258f8bdcd441bf53bf05bbbab846c2681e58e2595ecbe4"
START_UTC = datetime.fromisoformat("2026-11-12T05:15:01+00:00")
EARLIEST_ACCEPTANCE_UTC = START_UTC + timedelta(days=1)
EXPECTED_OWNER = "YWSHTMR"
EXPECTED_ORIGINAL_PID = 12736
EXPECTED_STOPPED_PID = 9900
EXPECTED_RECOVERED_PID = 15972
MAX_BYTES = 10000

class Hold(ValueError):
    pass

def require(value: bool, error: str):
    if not value:
        raise Hold(error)

def utc(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, AttributeError, ValueError):
        raise Hold("INVALID_OFFSET_TIMESTAMP") from None
    require(dt.tzinfo is not None, "MISSING_TIMEZONE_OFFSET")
    return dt.astimezone(timezone.utc)

def blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()

def safe_bytes(path: Path, maximum: int = MAX_BYTES) -> bytes:
    require(path.is_file() and not path.is_symlink()
            and not (hasattr(path, "is_junction") and path.is_junction())
            and 0 < path.stat().st_size <= maximum,
            "EXPECTED_IMMUTABLE_FILE_MISSING")
    return path.read_bytes()

def fixed_module(path: Path, expected_blob: str, label: str):
    require(blob(safe_bytes(path, 120000)) == expected_blob,
            label + "_SOURCE_CHANGED")
    spec = importlib.util.spec_from_file_location("cmp20_24h_"+label, path)
    require(spec is not None and spec.loader is not None,
            label + "_IMPORT_FAILED")
    m = importlib.util.module_from_spec(spec)
    prior = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(m)
    finally:
        sys.dont_write_bytecode = prior
    return m

def gate(*, now_utc: str, boot_utc: str, last_utc: str,
         owner_witness: dict, signed_finish: dict,
         finish_receipt: dict) -> dict:
    now, boot, last = utc(now_utc), utc(boot_utc), utc(last_utc)
    require(now >= EARLIEST_ACCEPTANCE_UTC,
            "V3_24H_NOT_YET_ELAPSED")
    require(boot <= START_UTC and boot <= last,
            "V3_24H_UNINTERRUPTED_BOOT_NOT_PROVEN")
    require(EARLIEST_ACCEPTANCE_UTC <= last <= now
            and now - last <= timedelta(minutes=12),
            "V3_POST_24H_NATURAL_TASK_TICK_MISSING_OR_STALE")
    require(type(owner_witness) is dict and
            owner_witness.get("status") == "PASS" and
            owner_witness.get("native_task_pass") is True and
            owner_witness.get("matching_receipt_pass") is True and
            owner_witness.get("read_only") is True and
            owner_witness.get("headless_pythonw") is True and
            owner_witness.get("source_signed") is True and
            owner_witness.get("v2_immutable_signature") is True and
            owner_witness.get("public_local_https_and_private_isolation") == "PASS" and
            owner_witness.get("boot_utc") == boot.isoformat() and
            owner_witness.get("last_natural_tick_utc") == last.isoformat(),
            "V3_NATIVE_RUNTIME_OWNER_READBACK_NOT_PASS")
    require(type(signed_finish) is dict and
            signed_finish.get("status") == "PASS" and
            signed_finish.get("independent_owner_signers") == 2 and
            signed_finish.get("signed_prior_drill") == "PASS" and
            signed_finish.get("original_signed_v3_recovery") == "PASS" and
            signed_finish.get("task_and_services_modified") is False,
            "V3_SIGNED_FAULT_PROOF_NOT_PASS")
    f = finish_receipt
    require(type(f) is dict and
            f.get("schema") == "legal-kb.cmp20.v3-fault-drill-signed-finish-v2.v1" and
            f.get("status") == "PASS" and
            f.get("source_signed") is True and
            f.get("native_v3_last_result") == 0 and
            f.get("signed_candidate_stopped_pid") == EXPECTED_STOPPED_PID and
            f.get("original_public_pid") == EXPECTED_ORIGINAL_PID and
            f.get("recovered_candidate_pid") == EXPECTED_RECOVERED_PID and
            f.get("public_route") == "http://127.0.0.1:8879" and
            f.get("public_8443_healthy") is True and
            f.get("private_8877_preserved") is True and
            f.get("original_8878_preserved") is True and
            f.get("candidate_8879_healthy") is True and
            f.get("no_task_modifications") is True and
            f.get("no_new_reboot") is True and
            f.get("drill_start_sha256") ==
                "99ec7c2f0ab8d0d83cdf15c6d4bf0df6683ae3489de8c00d5d7c3cca32eb3d8b" and
            f.get("signed_recovered_v3_receipt_sha256") ==
                "11d6b4de644c0e6169d0b82e625ac6624b289d34bf96e2efb61855394db2191b",
            "V3_FAULT_RESTORE_RECEIPT_NOT_PASS")
    require(START_UTC < utc(f["completed_utc"]) < now,
            "V3_FAULT_COMPLETION_NOT_BEFORE_24H_READBACK")
    return {
        "schema": "legal-kb.cmp20.headless-v3-24h-readonly.v1",
        "status": "PASS",
        "owner": EXPECTED_OWNER,
        "window_start_utc": START_UTC.isoformat(),
        "observed_utc": now.isoformat(),
        "hours_elapsed_since_first_v3_tick": round(
            (now-START_UTC).total_seconds()/3600, 3),
        "reboot_during_window": False,
        "current_native_v3_task": "PASS",
        "latest_signed_v3_receipt": owner_witness["receipt_sha256"],
        "real_signed_candidate_fault_and_restore": "PASS",
        "fault_finish_receipt_sha256": FINISH_RESULT_SHA256,
        "task_schedule_every_tick_observed": False,
        "external_owner_iphone_carrier_cmd_acceptance": "USER_REPORTED_SEPARATELY",
        "canonical_campaign_closure": "SEPARATE_REVIEW_GATE",
        "read_only": True,
        "new_execution_grants": False,
    }

def owner_24h() -> dict:
    require(os.name == "nt" and
            os.environ.get("COMPUTERNAME", "").upper() == EXPECTED_OWNER and
            os.environ.get("USERNAME", "").casefold() == "watar",
            "WRONG_OWNER_HOST")
    # Gate must be checked before opening signed dependencies or making any
    # mistaken claim. It is legitimate and expected to HOLD on Nov 12.
    current = datetime.now(timezone.utc)
    require(current >= EARLIEST_ACCEPTANCE_UTC, "V3_24H_NOT_YET_ELAPSED")
    runtime = fixed_module(OWNER_ACCEPTANCE, OWNER_ACCEPTANCE_BLOB, "RUNTIME")
    latest = runtime.owner_witness()
    finish = fixed_module(FINISH_SIGNED_VERIFIER, FINISH_VERIFIER_BLOB, "FINISH")
    proof = finish.verify()
    finish_raw = safe_bytes(FINISH_RESULT)
    require(hashlib.sha256(finish_raw).hexdigest() == FINISH_RESULT_SHA256,
            "V3_SIGNED_FINISH_RECEIPT_BYTES_CHANGED")
    try:
        result = json.loads(finish_raw.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError):
        raise Hold("V3_FINISH_JSON_INVALID") from None
    return gate(
        now_utc=datetime.now(timezone.utc).isoformat(),
        boot_utc=latest["boot_utc"],
        last_utc=latest["last_natural_tick_utc"],
        owner_witness=latest,
        signed_finish=proof,
        finish_receipt=result,
    )

def main() -> int:
    if sys.argv[1:] != ["--after-24h"]:
        print(json.dumps({"status":"HOLD","reason":"READ_ONLY_EXACT_MODE_ONLY"}))
        return 2
    try:
        print(json.dumps(owner_24h(), sort_keys=True))
        return 0
    except (Hold, ValueError, OSError, TypeError, KeyError, RuntimeError, ImportError) as error:
        # Only fixed, predeclared Hold labels are printable; never include
        # arbitrary external exception messages that might contain credentials.
        reason = str(error) if isinstance(error, Hold) else "V3_24H_OWNER_GATE_NOT_PROVEN"
        print(json.dumps({"status":"HOLD","reason":reason}, sort_keys=True))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
