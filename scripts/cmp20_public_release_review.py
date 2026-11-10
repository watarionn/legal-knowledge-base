"""CMP-20 independent owner Ed25519 review of a fixed, staged source repair.

Review-only, fail-closed. No Task, live process, Tailscale, credential, DB,
private runtime or filesystem mutation. A valid review packet NEVER grants
release activation or rollback execution authority.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCHEMA = "legal-kb.cmp20.owner-public-release-review-result.v1"
TRUST_SCHEMA = "legal-kb.cmp20.owner-public-release-review-trust.v1"
MANIFEST_SCHEMA = "legal-kb.cmp20.owner-public-release-review-manifest.v1"
PACKET_SCHEMA = "legal-kb.cmp20.owner-public-release-review-packet.v1"
PURPOSE = "legal-kb.cmp20.owner-public-release-review-only.v1"
RELEASE_ID = "cmp20-public-demo-win10055-patch-review-20261110-v1"
OWNER_HEAD = "4acdda5aac833a30189858ff1e43c34ada23c839"
SOURCE_MAIN = "14d5d6dae5ca1b238a78860b0e473ebbd795415d"
ORIGINAL_BLOB = "a394f509b51fe598eb0f1852339ba7f21e2be9b4"
LAUNCHER_SHA256 = "fa806751be935fd93c4650a56171c9615c2ce3550acb222e233b038e0e32a77f"
STAGE_MANIFEST_SHA256 = "9b8730abdfe399b9f8d9bf86e95fac0b9063236f214c306c439da4588b80374f"
PATCH_BLOBS = {
    "003_web_server.py": "511f5070c8c3fac8e733b35cb897868dca77369c",
    "082_public_demo_socket_retry_test.py": "ab157e90a4725d1b8923bc0a68cacdd95b82d5c5",
}
ROOT = Path(os.environ.get("LOCALAPPDATA", "")) / "RinkaMissionControl"
TRUST_DIR = ROOT / "owner_approvals" / "cmp20-public-demo-release-review"
STAGED = (ROOT / "cmp20-server-retry-qa-20261110" /
          "cmp20-public-demo-unsigned-source-candidate-v1")


class ReviewHold(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ReviewHold(code)


def canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def gitblob(raw: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\x00" + raw
    ).hexdigest()


def expected_manifest() -> dict:
    return {
        "schema": MANIFEST_SCHEMA,
        "purpose": PURPOSE,
        "release_id": RELEASE_ID,
        "stage_manifest_sha256": STAGE_MANIFEST_SHA256,
        "old_public_git_head": OWNER_HEAD,
        "old_server_git_blob": ORIGINAL_BLOB,
        "reviewed_fix_main_commit": SOURCE_MAIN,
        "reviewed_patch_git_blobs": dict(sorted(PATCH_BLOBS.items())),
        "existing_task": "LegalKB Public Demo Runtime",
        "existing_task_action_sha256": LAUNCHER_SHA256,
        "public_bind": "127.0.0.1:8878",
        "private_bind_unmodified": "127.0.0.1:8877",
        "funnel_unmodified": "HTTPS:8443_TO_LOOPBACK:8878",
        "rollback_source": "PINNED_ORIGINAL_PUBLIC_WORKTREE_NO_OVERWRITE",
        "signature_scope": "REVIEW_ONLY_NOT_EXECUTION",
        "signed_execution_grant": False,
        "task_register_or_enable_allowed": False,
        "task_trigger_allowed": False,
        "process_stop_or_restart_allowed": False,
        "production_files_modify_allowed": False,
        "database_credentials_read_allowed": False,
        "os_reboot_allowed": False,
    }


def _exact(value, keys: set[str], reason: str) -> None:
    require(isinstance(value, dict) and set(value) == keys, reason)


def _public_key(encoded: str) -> bytes:
    require(isinstance(encoded, str), "KEY_ENCODING_HOLD")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise ReviewHold("KEY_ENCODING_HOLD") from None
    require(len(raw) == 32, "PUBLIC_KEY_LENGTH_HOLD")
    return raw


def verify_packet(trust: dict, manifest: dict, packet: dict) -> dict:
    """Pure cryptographic verifier, independent of the issuing signer."""
    _exact(trust, {"schema", "purpose", "issuer_public_b64",
                   "reviewer_public_b64"}, "TRUST_FIELDS_HOLD")
    require(trust["schema"] == TRUST_SCHEMA and trust["purpose"] == PURPOSE,
            "TRUST_PURPOSE_HOLD")
    require(manifest == expected_manifest(), "REVIEW_MANIFEST_PIN_HOLD")
    _exact(packet, {"schema", "statement", "issuer_signature_b64",
                    "reviewer_signature_b64"}, "PACKET_FIELDS_HOLD")
    require(packet["schema"] == PACKET_SCHEMA, "PACKET_SCHEMA_HOLD")
    statement = {
        "purpose": PURPOSE,
        "release_id": RELEASE_ID,
        "old_public_git_head": OWNER_HEAD,
        "reviewed_fix_main_commit": SOURCE_MAIN,
        "stage_manifest_sha256": STAGE_MANIFEST_SHA256,
        "review_manifest_sha256": sha(canonical(manifest)),
        "approval_scope": "REVIEW_ONLY_NOT_EXECUTION",
    }
    require(packet["statement"] == statement, "STATEMENT_PIN_HOLD")
    issuer = _public_key(trust["issuer_public_b64"])
    reviewer = _public_key(trust["reviewer_public_b64"])
    require(issuer != reviewer, "INDEPENDENT_OWNER_SIGNERS_REQUIRED")
    wire = canonical(statement)
    try:
        for role, raw_key in (("issuer", issuer), ("reviewer", reviewer)):
            signature = base64.b64decode(packet[role + "_signature_b64"],
                                         validate=True)
            require(len(signature) == 64, "SIGNATURE_SIZE_HOLD")
            Ed25519PublicKey.from_public_bytes(raw_key).verify(signature, wire)
    except ReviewHold:
        raise
    except (InvalidSignature, ValueError, TypeError):
        raise ReviewHold("OWNER_SIGNATURE_INVALID") from None
    return {
        "schema": SCHEMA, "status": "PASS",
        "verified_scope": "REVIEW_ONLY_NOT_EXECUTION",
        "owner_execution_authority": False,
        "task_register_authorized": False,
        "task_enable_authorized": False,
        "process_stop_authorized": False,
        "rollback_execution_authorized": False,
        "public_runtime_modified": False,
    }


def _safe_file(path: Path, max_bytes: int = 32768) -> bytes:
    require(path.is_file() and not path.is_symlink()
            and not (hasattr(path, "is_junction") and path.is_junction()),
            "OWNER_SIGNED_FILE_MISSING_OR_REPARSE")
    size = path.stat().st_size
    require(0 < size <= max_bytes, "OWNER_SIGNED_FILE_SIZE_HOLD")
    return path.read_bytes()


def _safe_dir(path: Path) -> None:
    require(path.is_dir() and not path.is_symlink()
            and not (hasattr(path, "is_junction") and path.is_junction()),
            "OWNER_SIGNED_DIRECTORY_MISSING_OR_REPARSE")



def strict_json(raw: bytes) -> dict:
    """Fail closed on repeated JSON keys, NaN/Infinity and exponent overflow."""
    def unique_keys(pairs: list[tuple[str, object]]) -> dict:
        value = {}
        for key, item in pairs:
            require(key not in value, "OWNER_JSON_DUPLICATE_KEY")
            value[key] = item
        return value

    def reject_constant(_value: str):
        raise ReviewHold("OWNER_JSON_NONSTANDARD_NUMBER")

    def finite_float(raw_number: str) -> float:
        value = float(raw_number)
        require(math.isfinite(value), "OWNER_JSON_NONFINITE_NUMBER")
        return value

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_keys,
                           parse_constant=reject_constant,
                           parse_float=finite_float)
    except (UnicodeError, json.JSONDecodeError):
        raise ReviewHold("OWNER_JSON_INVALID") from None
    except RecursionError:
        raise ReviewHold("OWNER_JSON_TOO_DEEP") from None
    require(isinstance(value, dict), "OWNER_JSON_OBJECT_REQUIRED")
    return value

def _json_file(path: Path, size: int = 32768) -> dict:
    return strict_json(_safe_file(path, size))


def verify_staged_source(root: Path = STAGED) -> dict:
    """Bind physical owner stage bytes before accepting a signature."""
    _safe_dir(root)
    require({x.name for x in root.iterdir()} ==
            {"manifest.json", *PATCH_BLOBS}, "STAGE_EXACT_FILES_HOLD")
    raw = _safe_file(root / "manifest.json", 8192)
    require(sha(raw) == STAGE_MANIFEST_SHA256, "STAGE_MANIFEST_SHA_CHANGED")
    manifest = strict_json(raw)
    require(isinstance(manifest, dict), "STAGE_MANIFEST_OBJECT_REQUIRED")
    require(manifest.get("schema") ==
            "legal-kb.cmp20.public-demo-unsigned-source-candidate.v1"
            and manifest.get("operation") ==
            "IMMUTABLE_UNSIGNED_NONEXECUTABLE_PATCH_STAGE_ONLY"
            and manifest.get("owner_head_preimage") == OWNER_HEAD
            and manifest.get("owner_server_original_git_blob") == ORIGINAL_BLOB
            and manifest.get("owner_task_action_sha256_preimage") == LAUNCHER_SHA256
            and manifest.get("source_main_reviewed_commit") == SOURCE_MAIN
            and manifest.get("patch_files_git_blob") ==
            dict(sorted(PATCH_BLOBS.items())), "STAGE_BOUNDARY_CHANGED")
    rights = manifest.get("privileges")
    require(isinstance(rights, dict) and all(v is False for v in rights.values())
            and len(rights) == 8, "STAGE_PRIVILEGES_UNEXPECTED")
    actual_hashes = {}
    for name, blob in PATCH_BLOBS.items():
        raw_patch = _safe_file(root / name, 150000)
        require(gitblob(raw_patch) == blob, "STAGED_PATCH_BYTES_CHANGED")
        actual_hashes[name] = sha(raw_patch)
    require(manifest.get("patch_files_sha256") == actual_hashes,
            "STAGE_PATCH_SHA256_CHANGED")
    return {"status": "PASS", "stage_manifest_sha256": sha(raw),
            "patch_bytes_match": True, "source_files": len(PATCH_BLOBS)}


def inspect() -> dict:
    require(os.name == "nt", "OWNER_WINDOWS_ONLY")
    _safe_dir(TRUST_DIR)
    stage = verify_staged_source()
    verdict = verify_packet(
        _json_file(TRUST_DIR / "trust.json", 8192),
        _json_file(TRUST_DIR / "manifest.json", 8192),
        _json_file(TRUST_DIR / "packet.json", 8192),
    )
    return {**verdict, "stage_readback": stage,
            "owner_private_keys_exported": False}


def main() -> int:
    if sys.argv[1:] != ["--verify"]:
        print(json.dumps({"status": "HOLD", "reason": "VERIFY_ONLY",
                          "owner_execution_authority": False}))
        return 2
    try:
        print(json.dumps(inspect(), sort_keys=True))
        return 0
    except (ReviewHold, OSError, ValueError, TypeError, KeyError) as exc:
        code = str(exc) if isinstance(exc, ReviewHold) else "OWNER_VERIFICATION_ERROR"
        print(json.dumps({"status": "HOLD", "reason": code,
                          "owner_execution_authority": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
