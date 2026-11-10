"""CMP20 owner public-demo release boundary: read-only and fail-closed.

Reports actual current live runtime/source and preexisting signed review, while
NEVER issuing a signature, switching process/Task, or marking execution allowed.
Owner-approved source review and separately owner-signed cutover are different.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

SCHEMA = "legal-kb.cmp20.owner-release-readiness-readonly.v1"
OWNER_HOST = "YWSHTMR"
SOURCES = {
    "cmp20_public_runtime_inspect.py": "33f0e3549f881bb5f9f5267b7ae5d6aca5d95ea8",
    "cmp20_public_release_review.py": "ae7f2cbd01dab3d6dd9823ce340be34ee95bbe3b",
}
HTTPS = "https://ywshtmr.tail8fd68c.ts.net:8443"
MAX_BODY = 8192


class ReadinessHold(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ReadinessHold(reason)


def gitblob(data: bytes) -> str:
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\x00"+data).hexdigest()


def module(path: Path, blob: str):
    require(path.is_file() and not path.is_symlink()
            and not (hasattr(path, "is_junction") and path.is_junction())
            and 0 < path.stat().st_size <= 100000,
            "PINNED_SOURCE_MISSING_OR_REPARSE")
    raw = path.read_bytes()
    require(gitblob(raw) == blob, "PINNED_SOURCE_CHANGED")
    spec = importlib.util.spec_from_file_location("cmp20_gate_"+path.stem, path)
    require(spec is not None and spec.loader is not None, "SOURCE_IMPORT_HOLD")
    obj = importlib.util.module_from_spec(spec)
    original = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(obj)
    finally:
        sys.dont_write_bytecode = original
    return obj


def public_fetch(path: str) -> tuple[int, dict, dict]:
    require(path in ("/", "/api/v1/health", "/api/v1/favorites"),
            "UNKNOWN_PUBLIC_READONLY_ENDPOINT")
    try:
        with urlopen(HTTPS+path, timeout=7) as r:
            raw = r.read(MAX_BODY+1)
            require(len(raw) <= MAX_BODY, "PUBLIC_HTTP_BODY_OVERSIZE")
            if path == "/api/v1/health":
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeError):
                    raise ReadinessHold("PUBLIC_HEALTH_UNREADABLE") from None
                require(type(body) is dict, "PUBLIC_HEALTH_NOT_OBJECT")
            else:
                body = {}
            return r.status, body, dict(r.headers.items())
    except HTTPError as err:
        return err.code, {}, dict(err.headers.items())
    except (OSError, URLError) as err:
        raise ReadinessHold("OWNER_PUBLIC_HTTPS_UNREACHABLE") from err


def check_http(root: tuple, health: tuple, hidden: tuple) -> dict:
    require(root[0] == 200 and health[0] == 200
            and hidden[0] == 404, "PUBLIC_HTTPS_OR_PRIVATE_ROUTE_HOLD")
    data = health[1]
    require(data.get("status") == "ok"
            and data.get("mode") == "public-demo"
            and data.get("app_version") == "phase8-public-demo",
            "PUBLIC_HEALTH_IDENTITY_HOLD")
    headers = {str(k).lower():str(v) for k,v in root[2].items()}
    require(bool(headers.get("content-security-policy"))
            and headers.get("x-content-type-options","").lower() == "nosniff",
            "PUBLIC_SECURITY_HEADERS_HOLD")
    return {"public_https_root":200,"public_https_health":200,
            "private_public_exposure":404,
            "public_security_headers_verified":True}


def evaluate(runtime: dict, stage: dict, review: dict | None,
             public: dict) -> dict:
    require(runtime.get("status") == "HEALTHY"
            and runtime.get("source_git_head_pinned") is True
            and runtime.get("launcher_sha256_pinned") is True
            and runtime.get("funnel_target_pinned") is True
            and runtime.get("owner_process_verified") is True
            and runtime.get("public_health_verified") is True
            and runtime.get("read_only") is True
            and runtime.get("owner_execution_authority") is False,
            "OWNER_PUBLIC_RUNTIME_NOT_HEALTHY")
    require(stage.get("status") == "PASS"
            and stage.get("stage_manifest_sha256") ==
                "9b8730abdfe399b9f8d9bf86e95fac0b9063236f214c306c439da4588b80374f"
            and stage.get("patch_bytes_match") is True
            and stage.get("source_files") == 2,
            "OWNER_IMMUTABLE_STAGE_CHANGED")
    require(public == {"public_https_root":200,"public_https_health":200,
                       "private_public_exposure":404,
                       "public_security_headers_verified":True},
            "PUBLIC_HTTP_BOUNDARY_NOT_VERIFIED")
    if review is None:
        verdict = "OWNER_REVIEW_KEY_ENROLLMENT_AND_PACKET_PENDING"
        signed = False
    else:
        require(review.get("status") == "PASS"
                and review.get("verified_scope") == "REVIEW_ONLY_NOT_EXECUTION"
                and review.get("owner_execution_authority") is False,
                "SIGNED_REVIEW_SCOPE_UNTRUSTED")
        verdict = "SIGNED_REVIEW_ONLY_SEPARATE_EXECUTION_APPROVAL_PENDING"
        signed = True
    return {
        "schema": SCHEMA, "status": "HOLD_FOR_PRODUCTION_CUTOVER",
        "owner_public_runtime": "HEALTHY",
        "immutable_patch_stage": "PASS",
        "review_key_or_packet_state": verdict,
        "review_signed": signed,
        **public,
        "owner_execution_authority": False,
        "task_or_process_mutated": False,
        "source_or_stage_mutated": False,
        "private_database_accessed": False,
        "shared_reboot_performed": False,
        "public_new_patch_deployed": False,
        "cmp20_canonical_campaign_completed": False,
    }


def inspect() -> dict:
    require(os.name == "nt" and
            os.environ.get("COMPUTERNAME","").upper() == OWNER_HOST,
            "OWNER_WINDOWS_HOST_ONLY")
    source_dir = Path(__file__).resolve().parent
    guard = module(source_dir/"cmp20_public_runtime_inspect.py",
                   SOURCES["cmp20_public_runtime_inspect.py"])
    verifier = module(source_dir/"cmp20_public_release_review.py",
                      SOURCES["cmp20_public_release_review.py"])
    public = check_http(public_fetch("/"), public_fetch("/api/v1/health"),
                        public_fetch("/api/v1/favorites"))
    runtime = guard.inspect()
    stage = verifier.verify_staged_source()
    if verifier.TRUST_DIR.exists():
        review = verifier.inspect()
    else:
        review = None
    return evaluate(runtime,stage,review,public)


def main() -> int:
    if sys.argv[1:] != ["--inspect"]:
        print(json.dumps({"schema": SCHEMA, "status": "HOLD",
                          "reason": "READ_ONLY_INSPECT_ONLY",
                          "owner_execution_authority": False}))
        return 2
    try:
        print(json.dumps(inspect(), sort_keys=True))
        return 2  # Genuine release execution and canonicality are still OPEN.
    except (ReadinessHold,OSError,ValueError,TypeError,KeyError) as exc:
        reason = str(exc) if isinstance(exc, ReadinessHold) else \
                "OWNER_READONLY_READINESS_FAILED"
        print(json.dumps({"schema":SCHEMA,"status":"HOLD",
                          "reason":reason,
                          "owner_execution_authority":False}, sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
