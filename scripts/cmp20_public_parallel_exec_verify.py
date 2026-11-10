"""Independent CMP20 owner Ed25519 authorization for reversible public-only cutover.

The dedicated execution trust is separate from CMP20 REVIEW_ONLY signer keys.
A valid packet authorizes ONLY a pre-pinned stage, public parallel worker at
127.0.0.1:8879, Funnel8443 switch, exact Funnel restore to original8878.
No old PID kill, Windows Task modification, private DB access or OS reboot.
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

SCHEMA="legal-kb.cmp20.public-parallel-execution-verifier.v1"
TRUST_SCHEMA="legal-kb.cmp20.public-parallel-owner-execution-trust.v1"
MANIFEST_SCHEMA="legal-kb.cmp20.public-parallel-owner-execution-manifest.v1"
PACKET_SCHEMA="legal-kb.cmp20.public-parallel-owner-execution-packet.v1"
PURPOSE="legal-kb.cmp20.parallel-public-funnel-8443-owner-exec.v1"
RELEASE_ID="cmp20-public-demo-parallel-exec-v1"
REVIEW_PURPOSE="legal-kb.cmp20.owner-public-release-review-only.v1"
REVIEW_PACKET_SHA="6bee779804cb0e9ef516eb3d5898107fcc9fa0d17a38b3d6d38459ee12f19e88"
STAGE_MANIFEST_SHA="9b8730abdfe399b9f8d9bf86e95fac0b9063236f214c306c439da4588b80374f"
OLD_HEAD="4acdda5aac833a30189858ff1e43c34ada23c839"
OLD_LAUNCHER_SHA="fa806751be935fd93c4650a56171c9615c2ce3550acb222e233b038e0e32a77f"
PATCH_BLOB="511f5070c8c3fac8e733b35cb897868dca77369c"
REVIEW_VERIFIER_BLOB="ae7f2cbd01dab3d6dd9823ce340be34ee95bbe3b"
ALLOWED=["stage","start_parallel_8879","switch_public_8443","restore_public_8878"]
BASE=Path(os.environ.get("LOCALAPPDATA",""))/"RinkaMissionControl"
TRUST_ROOT=BASE/"owner_approvals"/"cmp20-public-demo-parallel-exec-v1"
REVIEW_ROOT=BASE/"owner_approvals"/"cmp20-public-demo-release-review"
UNSIGNED_STAGE=BASE/"cmp20-server-retry-qa-20261110"/"cmp20-public-demo-unsigned-source-candidate-v1"
SCRIPTS=Path(__file__).resolve().parent


class ExecutionHold(ValueError):
    pass


def require(ok:bool,reason:str):
    if not ok:
        raise ExecutionHold(reason)


def sha(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()


def gitblob(raw:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\x00"+raw).hexdigest()


def canonical(obj:dict)->bytes:
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()


def safe_file(path:Path,max_bytes:int=120000)->bytes:
    require(path.is_file() and not path.is_symlink() and
            not (hasattr(path,"is_junction") and path.is_junction())
            and 0<path.stat().st_size<=max_bytes,
            "OWNER_SIGNED_FILE_MISSING_OR_REPARSE")
    return path.read_bytes()


def safe_dir(path:Path):
    require(path.is_dir() and not path.is_symlink() and
            not (hasattr(path,"is_junction") and path.is_junction()),
            "OWNER_SIGNED_DIR_MISSING_OR_REPARSE")


def strict_json(raw:bytes)->dict:
    def unique(pairs):
        o={}
        for key,value in pairs:
            require(key not in o,"OWNER_EXEC_JSON_DUPLICATE_KEY")
            o[key]=value
        return o
    def no_constant(_):
        raise ExecutionHold("OWNER_EXEC_JSON_NONSTANDARD_NUMBER")
    def finite_float(s):
        v=float(s)
        require(math.isfinite(v),"OWNER_EXEC_JSON_NONFINITE")
        return v
    try:
        v=json.loads(raw.decode("utf-8"),object_pairs_hook=unique,
                     parse_constant=no_constant,parse_float=finite_float)
    except (UnicodeError,json.JSONDecodeError,RecursionError):
        raise ExecutionHold("OWNER_EXEC_JSON_INVALID") from None
    require(type(v) is dict,"OWNER_EXEC_JSON_OBJECT_REQUIRED")
    return v


def manifest_fields(action_git_blob:str,overlay_git_blob:str)->dict:
    for x in (action_git_blob,overlay_git_blob):
        require(type(x) is str and len(x)==40 and
                all(c in "0123456789abcdef" for c in x),
                "REVIEWED_SOURCE_BLOB_FORMAT_HOLD")
    return {
        "schema":MANIFEST_SCHEMA,
        "purpose":PURPOSE,"release_id":RELEASE_ID,
        "owner_host":"YWSHTMR",
        "owner_public_original_git_head":OLD_HEAD,
        "owner_public_launcher_sha256":OLD_LAUNCHER_SHA,
        "review_packet_sha256":REVIEW_PACKET_SHA,
        "reviewed_unsigned_patch_stage_sha256":STAGE_MANIFEST_SHA,
        "reviewed_patch_git_blob":PATCH_BLOB,
        "owner_action_git_blob":action_git_blob,
        "owner_overlay_git_blob":overlay_git_blob,
        "public_funnel":"ywshtmr.tail8fd68c.ts.net:8443",
        "previous_public_target":"http://127.0.0.1:8878",
        "candidate_public_target":"http://127.0.0.1:8879",
        "authorized_actions":ALLOWED,
        "old_public_process_stop_allowed":False,
        "windows_task_change_allowed":False,
        "private_8877_or_postgres_change_allowed":False,
        "owner_os_reboot_allowed":False,
        "funnel_reset_allowed":False,
        "rollback_exact_original_8443_target_required":True,
    }


def statement_for(manifest:dict)->dict:
    return {
        "purpose":PURPOSE,"release_id":RELEASE_ID,
        "approval_scope":"EXACT_PUBLIC_PARALLEL_Funnel_ONLY",
        "review_packet_sha256":REVIEW_PACKET_SHA,
        "manifest_sha256":sha(canonical(manifest)),
        "owner_action_git_blob":manifest["owner_action_git_blob"],
        "owner_overlay_git_blob":manifest["owner_overlay_git_blob"],
        "authorized_actions":ALLOWED,
        "old_public_stop_allowed":False,
        "owner_os_reboot_allowed":False,
    }


def _b64(s:str,n:int)->bytes:
    require(type(s) is str,"OWNER_KEY_ENCODING_HOLD")
    try:
        raw=base64.b64decode(s,validate=True)
    except (ValueError,TypeError):
        raise ExecutionHold("OWNER_KEY_ENCODING_HOLD") from None
    require(len(raw)==n,"OWNER_KEY_SIZE_HOLD")
    return raw


def verify_packet(trust:dict,manifest:dict,packet:dict)->dict:
    require(type(trust) is dict and
            set(trust)=={"schema","purpose","issuer_public_b64","reviewer_public_b64"},
            "OWNER_EXEC_TRUST_FIELDS_HOLD")
    require(trust["schema"]==TRUST_SCHEMA and trust["purpose"]==PURPOSE,
            "OWNER_EXEC_TRUST_PURPOSE_HOLD")
    require(type(manifest) is dict and
            set(manifest)==set(manifest_fields("0"*40,"0"*40)),
            "OWNER_EXEC_MANIFEST_FIELDS_HOLD")
    expected=manifest_fields(manifest["owner_action_git_blob"],
                             manifest["owner_overlay_git_blob"])
    require(manifest==expected,"OWNER_EXEC_EXACT_MANIFEST_HOLD")
    require(type(packet) is dict and
            set(packet)=={"schema","statement","issuer_signature_b64",
                          "reviewer_signature_b64"} and
            packet["schema"]==PACKET_SCHEMA,
            "OWNER_EXEC_PACKET_FIELDS_HOLD")
    statement=statement_for(manifest)
    require(packet["statement"]==statement,"OWNER_EXEC_SIGNED_SCOPE_HOLD")
    keys=[_b64(trust[k+"_public_b64"],32) for k in ("issuer","reviewer")]
    require(keys[0]!=keys[1],"OWNER_DISTINCT_SIGNING_ROLES_REQUIRED")
    signed=canonical(statement)
    try:
        for i,name in enumerate(("issuer","reviewer")):
            sig=_b64(packet[name+"_signature_b64"],64)
            Ed25519PublicKey.from_public_bytes(keys[i]).verify(sig,signed)
    except (InvalidSignature,ValueError,TypeError):
        raise ExecutionHold("OWNER_EXEC_SIGNATURE_INVALID") from None
    return {"status":"PASS","signed_scope":statement["approval_scope"],
            "authorized_actions":ALLOWED,
            "old_public_stop_allowed":False,
            "owner_os_reboot_allowed":False,
            "windows_task_change_allowed":False,
            "public_parallel_port":8879,"public_funnel_port":8443,
            "private_runtime_changed":False}


def _review_module():
    path=SCRIPTS/"cmp20_public_release_review.py"
    require(gitblob(safe_file(path,90000))==REVIEW_VERIFIER_BLOB,
            "ORIGINAL_REVIEW_VERIFIER_DRIFT")
    spec=importlib.util.spec_from_file_location("cmp20_review_before_exec",path)
    require(spec is not None and spec.loader is not None,"REVIEW_IMPORT_HOLD")
    obj=importlib.util.module_from_spec(spec)
    old=sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode=True
        spec.loader.exec_module(obj)
    finally:
        sys.dont_write_bytecode=old
    return obj


def review_and_source_gate():
    verifier=_review_module()
    status=verifier.inspect()
    require(status["status"]=="PASS" and
            status["verified_scope"]=="REVIEW_ONLY_NOT_EXECUTION" and
            status["owner_execution_authority"] is False,
            "CMP20_REVIEW_SIGNED_PROOF_HOLD")
    require(sha(safe_file(REVIEW_ROOT/"packet.json",8192))==REVIEW_PACKET_SHA,
            "CMP20_SIGNED_REVIEW_PACKET_SHA_CHANGED")
    require(sha(safe_file(UNSIGNED_STAGE/"manifest.json",8192))==STAGE_MANIFEST_SHA,
            "CMP20_REVIEWED_STAGE_SHA_CHANGED")
    require(gitblob(safe_file(UNSIGNED_STAGE/"003_web_server.py"))==PATCH_BLOB,
            "CMP20_REVIEWED_PATCH_CHANGED")


def inspect()->dict:
    require(os.name=="nt" and os.environ.get("COMPUTERNAME","").upper()=="YWSHTMR",
            "CMP20_OWNER_WINDOWS_ONLY")
    review_and_source_gate()
    safe_dir(TRUST_ROOT)
    trust=strict_json(safe_file(TRUST_ROOT/"trust.json",8192))
    manifest=strict_json(safe_file(TRUST_ROOT/"manifest.json",8192))
    packet=strict_json(safe_file(TRUST_ROOT/"packet.json",8192))
    verified=verify_packet(trust,manifest,packet)
    require(gitblob(safe_file(SCRIPTS/"cmp20_public_parallel_owner_action.py",100000))
            ==manifest["owner_action_git_blob"],
            "CMP20_EXECUTABLE_OWNER_ACTION_DRIFT")
    require(gitblob(safe_file(SCRIPTS/"cmp20_public_parallel_overlay.py",100000))
            ==manifest["owner_overlay_git_blob"],
            "CMP20_EXECUTABLE_OVERLAY_DRIFT")
    return {"schema":SCHEMA,**verified,
            "owner_source_and_signed_review_readback":"PASS",
            "new_release_deployed_by_verification":False}


def main()->int:
    if sys.argv[1:]!=["--verify"]:
        print(json.dumps({"schema":SCHEMA,"status":"HOLD","reason":"VERIFY_ONLY",
                          "execution_authority_granted_by_cli":False}))
        return 2
    try:
        print(json.dumps(inspect(),sort_keys=True))
        return 0
    except (ExecutionHold,OSError,ValueError,KeyError,TypeError) as exc:
        why=str(exc) if isinstance(exc,ExecutionHold) else "OWNER_EXEC_VERIFIER_HOLD"
        print(json.dumps({"schema":SCHEMA,"status":"HOLD","reason":why,
                          "execution_authority_granted_by_cli":False},
                         sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
