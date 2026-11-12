"""CMP-20 V3 independent, read-only Ed25519 verifier for a windowless guardian.

This file authorizes NOTHING until TWO newly enrolled owner keys sign an exact
source-bound manifest. V2 signed source, V1 trust and signed bytes stay immutable.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

OWNER_HOST = "YWSHTMR"
OWNER_SID = "S-1-5-21-2008575412-695584821-1269537588-1001"
BASE = Path(os.environ.get("LOCALAPPDATA", "")) / "RinkaMissionControl"
RELEASE_ID = "cmp20-headless-guard-owner-v3"
RELEASE = BASE / "releases" / RELEASE_ID
TRUST = BASE / "owner_approvals" / RELEASE_ID
TASK_NAME = "RinkaLegalKBPublicGuardedOnceV3"
OLD_TASK = "RinkaLegalKBPublicGuardedOnceV2"
PYTHONW = r"C:\Python314\pythonw.exe"
ARGUMENTS = '-B "' + str(RELEASE / "cmp20_headless_v3_guard.py") + '" --once'
OLD_ACTION = '-B ' + str(BASE / "releases" /
    "cmp20-public-demo-guarded-once-owner-v2" /
    "cmp20_public_guarded_owner_v2.py") + ' --once'
V2_RELEASE = BASE / "releases" / "cmp20-public-demo-guarded-once-owner-v2"
V2_GUARD_BLOB = "df38e01947cd04a15bf144aecd512f6815945ecf"
V2_VERIFY_BLOB = "3e58401b0882022e69ed9a2548d88ab73fcc4448"
V2_PACKET_SHA = "e369c3669f6047b3eff5ac2604efde828d28aa3cf548f9ac8244c34db422d670"
SCHEMA = "legal-kb.cmp20.headless-v3-verifier.v1"
TRUST_SCHEMA = "legal-kb.cmp20.headless-v3-trust.v1"
MANIFEST_SCHEMA = "legal-kb.cmp20.headless-v3-manifest.v1"
PACKET_SCHEMA = "legal-kb.cmp20.headless-v3-packet.v1"
PURPOSE = "legal-kb.cmp20.owner-windowless-new-task-exact-recovery-v3.v1"
SOURCES = (
    "cmp20_headless_v3_verify.py",
    "cmp20_headless_v3_guard.py",
    "cmp20_headless_v3_owner.py",
)
ALLOWED = (
    "enroll_two_new_independent_owner_keys",
    "issue_exact_source_bound_packet",
    "stage_immutable_v3_release_only",
    "register_disabled_exact_v3_task_only",
    "disable_exact_existing_v2_task_for_cutover",
    "enable_exact_v3_task_after_atomic_preimage",
    "run_existing_signed_v2_public_only_recovery_bounded",
    "rollback_disable_exact_v3_enable_exact_v2",
)
FORBIDDEN = (
    "modify_existing_signed_v2_source",
    "modify_original_public_8878",
    "modify_private_8877_or_database",
    "reboot_os",
    "modify_unrelated_tasks",
    "change_other_tailscale_routes",
)

class V3Hold(ValueError):
    pass

def require(condition: bool, code: str):
    if not condition:
        raise V3Hold(code)

def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()

def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")

def safe_file(path: Path, max_size: int = 120000) -> bytes:
    require(path.is_file() and not path.is_symlink()
            and not (hasattr(path, "is_junction") and path.is_junction())
            and 0 < path.stat().st_size <= max_size,
            "V3_FILE_MISSING_OR_REPARSE")
    return path.read_bytes()

def safe_directory(path: Path):
    require(path.is_dir() and not path.is_symlink()
            and not (hasattr(path, "is_junction") and path.is_junction()),
            "V3_DIRECTORY_MISSING_OR_REPARSE")

def strict_json(raw: bytes) -> dict:
    def pairs(values):
        result = {}
        for key, val in values:
            require(key not in result, "V3_DUPLICATE_JSON_KEY")
            result[key] = val
        return result
    def nonfinite(_):
        raise V3Hold("V3_NONFINITE_NUMBER")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=nonfinite)
    except (UnicodeError, ValueError, RecursionError):
        raise V3Hold("V3_JSON_INVALID") from None
    require(type(data) is dict, "V3_OBJECT_REQUIRED")
    return data

def owner() -> None:
    require(os.name == "nt" and
            os.environ.get("COMPUTERNAME", "").upper() == OWNER_HOST
            and os.environ.get("USERNAME", "").casefold() == "watar",
            "V3_WRONG_OWNER")

def manifest_fields(source_blobs: dict) -> dict:
    require(type(source_blobs) is dict and set(source_blobs) == set(SOURCES),
            "V3_MANIFEST_SOURCES_WRONG")
    for val in source_blobs.values():
        require(type(val) is str and len(val) == 40
                and all(ch in "0123456789abcdef" for ch in val),
                "V3_SOURCE_HASH_INVALID")
    return {
        "schema": MANIFEST_SCHEMA,
        "purpose": PURPOSE,
        "release_id": RELEASE_ID,
        "owner_host": OWNER_HOST,
        "owner_sid": OWNER_SID,
        "headless_python": PYTHONW,
        "new_task": TASK_NAME,
        "new_task_args": ARGUMENTS,
        "old_task": OLD_TASK,
        "expected_old_executable": PYTHONW,
        "expected_old_args": OLD_ACTION,
        "old_guard_git_blob": V2_GUARD_BLOB,
        "old_verifier_git_blob": V2_VERIFY_BLOB,
        "prior_v2_packet_sha256": V2_PACKET_SHA,
        "new_task_triggers": ["Logon:owner", "Daily:PT5M/P1D"],
        "task_policy": {
            "owner": OWNER_SID, "logon": "Interactive",
            "run_level": "Limited", "overlap": "IgnoreNew",
            "hard_terminate": False, "start_on_demand": False,
        },
        "source_blobs": {name: source_blobs[name] for name in SOURCES},
        "allowed_actions": list(ALLOWED),
        "forbidden_actions": list(FORBIDDEN),
    }

def statement(manifest: dict) -> dict:
    return {"schema": PACKET_SCHEMA, "purpose": PURPOSE,
            "manifest_sha256": digest(canonical(manifest)),
            "release_id": RELEASE_ID, "task": TASK_NAME}

def decode_b64(encoded: str, expected_length: int) -> bytes:
    require(type(encoded) is str, "V3_KEY_NOT_STRING")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError):
        raise V3Hold("V3_KEY_NOT_BASE64") from None
    require(len(raw) == expected_length, "V3_KEY_LENGTH_WRONG")
    return raw

def check_packet(trust: dict, manifest: dict, packet: dict) -> None:
    require(type(trust) is dict and
            set(trust) == {"schema", "purpose", "issuer_public_b64",
                           "reviewer_public_b64"} and
            trust["schema"] == TRUST_SCHEMA and trust["purpose"] == PURPOSE,
            "V3_TRUST_PURPOSE_INVALID")
    require(type(manifest) is dict and
            manifest == manifest_fields(manifest.get("source_blobs", {})),
            "V3_MANIFEST_SCOPE_CHANGED")
    require(type(packet) is dict and
            set(packet) == {"schema", "statement", "issuer_signature_b64",
                            "reviewer_signature_b64"} and
            packet["schema"] == PACKET_SCHEMA and
            packet["statement"] == statement(manifest),
            "V3_PACKET_SCOPE_CHANGED")
    pub = [decode_b64(trust[k + "_public_b64"], 32)
           for k in ("issuer", "reviewer")]
    require(pub[0] != pub[1], "V3_SAME_SIGNER_TWO_ROLES")
    data = canonical(statement(manifest))
    for i, role in enumerate(("issuer", "reviewer")):
        try:
            Ed25519PublicKey.from_public_bytes(pub[i]).verify(
                decode_b64(packet[role + "_signature_b64"], 64), data)
        except (InvalidSignature, ValueError, TypeError):
            raise V3Hold("V3_ED25519_SIGNATURE_REJECTED") from None

def verify() -> dict:
    owner()
    safe_directory(TRUST)
    safe_directory(RELEASE)
    trust = strict_json(safe_file(TRUST / "trust.json", 8192))
    manifest = strict_json(safe_file(TRUST / "manifest.json", 16384))
    packet = strict_json(safe_file(TRUST / "packet.json", 16384))
    check_packet(trust, manifest, packet)
    for name, value in manifest["source_blobs"].items():
        require(blob(safe_file(RELEASE / name)) == value,
                "V3_INSTALLED_SOURCE_DRIFT")
    safe_directory(V2_RELEASE)
    original = V2_RELEASE / "cmp20_public_guarded_owner_v2.py"
    verifier = V2_RELEASE / "cmp20_public_guarded_task_verify_v2.py"
    require(blob(safe_file(original)) == V2_GUARD_BLOB
            and blob(safe_file(verifier)) == V2_VERIFY_BLOB
            and digest(safe_file(BASE / "owner_approvals" /
                                 "cmp20-public-demo-guarded-once-owner-v2" /
                                 "packet.json", 16384)) == V2_PACKET_SHA,
            "V3_V2_PIN_CHANGED")
    module_spec = importlib.util.spec_from_file_location("cmp20_v2_original_verifier", verifier)
    require(module_spec is not None and module_spec.loader is not None,
            "V3_V2_VERIFIER_UNLOADABLE")
    old = importlib.util.module_from_spec(module_spec)
    prior = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        module_spec.loader.exec_module(old)
    finally:
        sys.dont_write_bytecode = prior
    require(old.inspect()["status"] == "PASS", "V3_PRIOR_V2_ED25519_NOT_PASS")
    return {
        "schema": SCHEMA, "status": "PASS",
        "signed_release": RELEASE_ID, "two_distinct_ed25519_roles": True,
        "prior_v2_signature": "PASS", "headless_exe": PYTHONW,
        "v2_task_mutated_by_verifier": False,
        "os_reboot": False, "source_writes": False,
    }

def main() -> int:
    if sys.argv[1:] != ["--verify"]:
        print(json.dumps({"status": "HOLD", "reason": "V3_VERIFY_ONLY"}))
        return 2
    try:
        print(json.dumps(verify(), sort_keys=True))
        return 0
    except (V3Hold, OSError, KeyError, ValueError, TypeError) as error:
        reason = str(error) if isinstance(error, V3Hold) else "V3_READONLY_VERIFY_FAILED"
        print(json.dumps({"status": "HOLD", "reason": reason}, sort_keys=True))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
