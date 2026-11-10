"""Owner-local issuer for CMP20 PUBLIC DEMO REVIEW ONLY signing packets.

No live process/task/rollback/deploy operations. Only owner Windows may enroll
two new independent owner-only Ed25519 keys in the fixed CMP20 trust folder.
Issuing a packet requires exact owner consent plus independently read-back
trust.json SHA256 and a byte-verified immutable unsigned source stage.
Do not confuse this review packet with a signed execution grant.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SOURCE_ROOT = Path(__file__).resolve().parent
REVIEW_VERIFIER = "cmp20_public_release_review.py"
REVIEW_VERIFIER_BLOB = "b6366bb2a31c85d93dd1faff5b8cf3397342450f"
APPROVALS = Path(os.environ.get("LOCALAPPDATA", "")) / "RinkaMissionControl" / "owner_approvals"
KEY_ROOT = APPROVALS / "cmp20-public-demo-release-review"
CONSENT = {
    "enroll-review": "ENROLL CMP20 PUBLIC DEMO REVIEW ONLY KEYS",
    "issue-review": "ISSUE CMP20 PUBLIC DEMO REVIEW ONLY PACKET",
}


class SigningHold(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise SigningHold(code)


def canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gitblob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()


def pinned_verifier():
    path = SOURCE_ROOT / REVIEW_VERIFIER
    require(path.is_file() and not path.is_symlink(),
            "OWNER_REVIEW_VERIFIER_MISSING")
    raw = path.read_bytes()
    require(gitblob(raw) == REVIEW_VERIFIER_BLOB,
            "OWNER_REVIEW_VERIFIER_BLOB_DRIFT")
    spec = importlib.util.spec_from_file_location("cmp20_signed_review_verifier", path)
    require(spec is not None and spec.loader is not None, "VERIFIER_IMPORT_HOLD")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def make_trust(keys: dict, verifier) -> dict:
    require(set(keys) == {"issuer", "reviewer"}, "OWNER_ROLES_HOLD")
    require(public_b64(keys["issuer"]) != public_b64(keys["reviewer"]),
            "DUPLICATE_OWNER_SIGNING_KEYS_HOLD")
    return {
        "schema": verifier.TRUST_SCHEMA,
        "purpose": verifier.PURPOSE,
        "issuer_public_b64": public_b64(keys["issuer"]),
        "reviewer_public_b64": public_b64(keys["reviewer"]),
    }


def make_signed_review(keys: dict, verifier) -> tuple[dict, dict]:
    require(set(keys) == {"issuer", "reviewer"}, "OWNER_ROLES_HOLD")
    manifest = verifier.expected_manifest()
    statement = {
        "purpose": verifier.PURPOSE,
        "release_id": verifier.RELEASE_ID,
        "old_public_git_head": verifier.OWNER_HEAD,
        "reviewed_fix_main_commit": verifier.SOURCE_MAIN,
        "stage_manifest_sha256": verifier.STAGE_MANIFEST_SHA256,
        "review_manifest_sha256": sha(canonical(manifest)),
        "approval_scope": "REVIEW_ONLY_NOT_EXECUTION",
    }
    wire = canonical(statement)
    packet = {"schema": verifier.PACKET_SCHEMA, "statement": statement}
    for role, key in keys.items():
        packet[role + "_signature_b64"] = base64.b64encode(
            key.sign(wire)).decode("ascii")
    return manifest, packet


def safe_dir(path: Path) -> None:
    require(path.is_dir() and not path.is_symlink()
            and not (hasattr(path, "is_junction") and path.is_junction()),
            "OWNER_SIGNER_DIRECTORY_UNSAFE")


def owner_sid() -> str:
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
        capture_output=True, timeout=10, check=False)
    require(r.returncode == 0 and 0 < len(r.stdout) <= 256,
            "OWNER_SIGNER_SID_READ_HOLD")
    sid = r.stdout.decode("ascii", errors="ignore").strip()
    require(re.fullmatch(r"S-1-5-21-(?:\d+-){3}\d+", sid) is not None,
            "OWNER_SIGNER_SID_FORMAT_HOLD")
    return sid


def protect_new(path: Path) -> None:
    """Change DACL only, no SACL escalation. Exact owner/SYSTEM/Admin readback.

    Protecting a new keys directory MUST use inheritable (OI)(CI) grants,
    otherwise child private-key creation becomes unreadable to its owner.
    """
    require(os.name == "nt", "OWNER_WINDOWS_ONLY")
    require(path.exists() and not path.is_symlink()
            and not (hasattr(path, "is_junction") and path.is_junction()),
            "OWNER_ACL_TARGET_UNSAFE")
    icacls = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "icacls.exe"
    require(icacls.is_file(), "OWNER_ICACLS_MISSING")
    sid = owner_sid()
    suffix = ":(OI)(CI)(F)" if path.is_dir() else ":(F)"
    for args in (
        [str(icacls), str(path), "/inheritance:r"],
        [str(icacls), str(path), "/grant:r",
         "*" + sid + suffix,
         "*S-1-5-18" + suffix, "*S-1-5-32-544" + suffix],
        [str(icacls), str(path), "/remove:g", "*S-1-3-4"],
    ):
        r = subprocess.run(args, capture_output=True, timeout=15, check=False)
        require(r.returncode == 0, "OWNER_DACL_APPLY_HOLD")
    verify = (
        "$ErrorActionPreference='Stop';"
        "$p=$env:CMP20_SIGNER_KEY_PATH;"
        "$sid=$env:CMP20_SIGNER_OWNER_SID;"
        "$acl=Get-Acl -LiteralPath $p;"
        "if(-not $acl.AreAccessRulesProtected -or "
        "@($acl.Access).Count -ne 3){exit 3};"
        "$owner=$acl.GetOwner([Security.Principal.SecurityIdentifier]).Value;"
        "if($owner -ne $sid){exit 4};"
        "$expected=@($sid,'S-1-5-18','S-1-5-32-544');"
        "$found=@();"
        "foreach($a in @($acl.Access)){"
        "$value=$a.IdentityReference.Translate("
        "[Security.Principal.SecurityIdentifier]).Value;"
        "if($a.IsInherited -or $a.AccessControlType -ne 'Allow' "
        "-or $a.FileSystemRights -ne 'FullControl' "
        "-or $value -notin $expected){exit 5};"
        "$found+= $value};"
        "foreach($key in $expected){if($key -notin $found){exit 6}}"
    )
    env = {**os.environ, "CMP20_SIGNER_KEY_PATH": str(path),
           "CMP20_SIGNER_OWNER_SID": sid}
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", verify],
        env=env, capture_output=True, timeout=18, check=False)
    require(r.returncode == 0, "OWNER_ACL_READBACK_HOLD")


def create_new(path: Path, raw: bytes) -> None:
    safe_dir(path.parent)
    require(not path.exists() and not path.is_symlink(),
            "OWNER_SIGNER_NO_CLOBBER_HOLD")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(path.read_bytes() == raw, "OWNER_SIGNER_WRITE_READBACK_HOLD")
    protect_new(path)
    require(path.read_bytes() == raw, "OWNER_SIGNER_PROTECTED_READBACK_HOLD")


def enroll(verifier) -> dict:
    safe_dir(APPROVALS)
    require(not KEY_ROOT.exists() and not KEY_ROOT.is_symlink(),
            "CMP20_REVIEW_KEY_ROOT_ALREADY_EXISTS")
    KEY_ROOT.mkdir(mode=0o700)
    protect_new(KEY_ROOT)
    private = KEY_ROOT / "keys"
    private.mkdir(mode=0o700)
    protect_new(private)
    keys = {role: Ed25519PrivateKey.generate() for role in ("issuer", "reviewer")}
    trust = make_trust(keys, verifier)
    for role, key in keys.items():
        secret = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        create_new(private / (role + ".pem"), secret)
    wire = canonical(trust)
    create_new(KEY_ROOT / "trust.json", wire)
    require((KEY_ROOT / "trust.json").read_bytes() == wire,
            "CMP20_REVIEW_TRUST_READBACK_HOLD")
    return {
        "status": "ENROLLED_REVIEW_ONLY",
        "purpose": verifier.PURPOSE,
        "trust_sha256": sha(wire),
        "private_keys_exported": False,
        "production_activated": False,
        "task_changed": False,
        "execution_authority": False,
    }


def _read_json(raw: bytes, verifier) -> dict:
    return verifier.strict_json(raw)


def issue(verifier, independent_trust_pin: str) -> dict:
    require(isinstance(independent_trust_pin, str)
            and re.fullmatch(r"[0-9a-f]{64}", independent_trust_pin) is not None,
            "INDEPENDENT_OWNER_TRUST_PIN_REQUIRED")
    safe_dir(KEY_ROOT)
    safe_dir(KEY_ROOT / "keys")
    trust_path = KEY_ROOT / "trust.json"
    require(trust_path.is_file() and not trust_path.is_symlink()
            and not (hasattr(trust_path, "is_junction") and trust_path.is_junction()),
            "OWNER_SIGNER_TRUST_FILE_UNSAFE")
    trust_raw = trust_path.read_bytes()
    require(0 < len(trust_raw) <= 8192, "OWNER_SIGNER_TRUST_SIZE_HOLD")
    require(sha(trust_raw) == independent_trust_pin, "OWNER_TRUST_PIN_CHANGED")
    trust = _read_json(trust_raw, verifier)
    require(trust.get("schema") == verifier.TRUST_SCHEMA
            and trust.get("purpose") == verifier.PURPOSE,
            "OWNER_REVIEW_TRUST_PURPOSE_CHANGED")
    require(not (KEY_ROOT / "manifest.json").exists()
            and not (KEY_ROOT / "packet.json").exists(),
            "OWNER_SIGNING_PACKET_ALREADY_ISSUED")
    verifier.verify_staged_source()
    keys = {}
    for role in ("issuer", "reviewer"):
        path = KEY_ROOT / "keys" / (role + ".pem")
        require(path.is_file() and not path.is_symlink()
                and path.stat().st_size < 8192,
                "OWNER_SIGNING_PRIVATE_KEY_MISSING")
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        require(isinstance(key, Ed25519PrivateKey),
                "OWNER_SIGNING_KEY_TYPE_HOLD")
        require(public_b64(key) == trust[role + "_public_b64"],
                "OWNER_SIGNING_KEY_TRUST_MISMATCH")
        keys[role] = key
    manifest, packet = make_signed_review(keys, verifier)
    verdict = verifier.verify_packet(trust, manifest, packet)
    require(verdict["status"] == "PASS"
            and verdict["owner_execution_authority"] is False,
            "OWNER_REVIEW_VERIFIER_REJECTED")
    create_new(KEY_ROOT / "manifest.json", canonical(manifest))
    create_new(KEY_ROOT / "packet.json", canonical(packet))
    require(verifier.inspect()["status"] == "PASS",
            "OWNER_REVIEW_SIGNATURE_READBACK_HOLD")
    return {
        "status": "ISSUED_AND_INDEPENDENTLY_VERIFIED_REVIEW_ONLY",
        "packet_sha256": sha(canonical(packet)),
        "signed_scope": "REVIEW_ONLY_NOT_EXECUTION",
        "private_keys_exported": False,
        "task_or_process_modified": False,
        "production_activated": False,
        "execution_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Owner Windows CMP20 public demo review signer, not executor")
    parser.add_argument("action", choices=sorted(CONSENT))
    parser.add_argument("--owner-consent")
    parser.add_argument("--independent-trust-pin")
    args = parser.parse_args()
    try:
        require(os.name == "nt", "OWNER_WINDOWS_ONLY")
        require(args.owner_consent == CONSENT[args.action],
                "EXPLICIT_OWNER_REVIEW_CONSENT_REQUIRED")
        verifier = pinned_verifier()
        if args.action == "enroll-review":
            require(args.independent_trust_pin is None, "UNEXPECTED_TRUST_PIN")
            result = enroll(verifier)
        else:
            result = issue(verifier, args.independent_trust_pin)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (SigningHold, OSError, ValueError, TypeError, KeyError,
            subprocess.SubprocessError) as exc:
        code = str(exc) if isinstance(exc, SigningHold) else "OWNER_SIGNING_FAILED"
        print(json.dumps({"status": "HOLD", "reason": code,
                          "production_activated": False,
                          "execution_authority": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
