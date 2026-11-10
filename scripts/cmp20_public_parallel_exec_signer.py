"""Create-only two-role CMP20 owner signing for narrow parallel public execution.

Distinct owner keys and purpose from REVIEW_ONLY approval. This module
ENROLLS or ISSUES only; it has no stage/start/Funnel/Task/reboot operations.
The independent verifier is required to accept the real signed packet.
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

ROOT=Path(os.environ.get("LOCALAPPDATA",""))/"RinkaMissionControl"
APPROVALS=ROOT/"owner_approvals"
EXEC_ROOT=APPROVALS/"cmp20-public-demo-parallel-exec-v1"
SCRIPTS=Path(__file__).resolve().parent
REVIEW_SIGNER_BLOB="4199852e192349270096807af52d358ee89afe2b"
EXEC_VERIFIER_BLOB="253ef413c3b72f2de8b0d5df4ff68f478fca7bd8"
ACTION_BLOB="d73135326792889fdf62b235744e6af2f3288ecc"
OVERLAY_BLOB="4e07752f60d554987c9bd30dc513ae3af569ba57"
CONSENT={
 "enroll-execution":"ENROLL CMP20 PUBLIC PARALLEL EXECUTION ONLY KEYS",
 "issue-execution":"ISSUE CMP20 PUBLIC PARALLEL EXECUTION ONLY PACKET",
}


class SignHold(ValueError):
    pass


def require(ok,why):
    if not ok:
        raise SignHold(why)


def sha(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()


def gitblob(raw:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\x00"+raw).hexdigest()


def pinned(path:Path,blob:str):
    require(path.is_file() and not path.is_symlink() and
            gitblob(path.read_bytes())==blob,"SIGNED_OPERATOR_SOURCE_DRIFT")
    spec=importlib.util.spec_from_file_location("cmp20_exec_sign_"+path.stem,path)
    require(spec is not None and spec.loader is not None,
            "SIGNED_OPERATOR_IMPORT_HOLD")
    obj=importlib.util.module_from_spec(spec)
    before=sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode=True
        spec.loader.exec_module(obj)
    finally:
        sys.dont_write_bytecode=before
    return obj


def modules():
    helper=pinned(SCRIPTS/"cmp20_public_release_owner_signer.py",REVIEW_SIGNER_BLOB)
    verifier=pinned(SCRIPTS/"cmp20_public_parallel_exec_verify.py",EXEC_VERIFIER_BLOB)
    require(gitblob((SCRIPTS/"cmp20_public_parallel_owner_action.py").read_bytes())
            ==ACTION_BLOB,"OWNER_CUTOVER_ACTION_SOURCE_DRIFT")
    require(gitblob((SCRIPTS/"cmp20_public_parallel_overlay.py").read_bytes())
            ==OVERLAY_BLOB,"OWNER_OVERLAY_SOURCE_DRIFT")
    return helper,verifier


def public_b64(key:Ed25519PrivateKey)->str:
    pub=key.public_key().public_bytes(serialization.Encoding.Raw,
                                       serialization.PublicFormat.Raw)
    return base64.b64encode(pub).decode()


def setup(helper,verifier):
    require(not EXEC_ROOT.exists() and not EXEC_ROOT.is_symlink(),
            "OWNER_EXEC_ROOT_ALREADY_EXISTS")
    require(APPROVALS.is_dir() and not APPROVALS.is_symlink(),
            "OWNER_APPROVALS_ROOT_HOLD")
    verifier.review_and_source_gate()
    EXEC_ROOT.mkdir(mode=0o700)
    helper.protect_new(EXEC_ROOT)
    keys_dir=EXEC_ROOT/"keys"
    keys_dir.mkdir(mode=0o700)
    helper.protect_new(keys_dir)
    keys={k:Ed25519PrivateKey.generate() for k in ("issuer","reviewer")}
    require(public_b64(keys["issuer"])!=public_b64(keys["reviewer"]),
            "OWNER_DISTINCT_EXEC_KEYS_REQUIRED")
    trust={
        "schema":verifier.TRUST_SCHEMA,
        "purpose":verifier.PURPOSE,
        "issuer_public_b64":public_b64(keys["issuer"]),
        "reviewer_public_b64":public_b64(keys["reviewer"]),
    }
    for role,key in keys.items():
        raw=key.private_bytes(serialization.Encoding.PEM,
                              serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption())
        helper.create_new(keys_dir/(role+".pem"),raw)
    helper.create_new(EXEC_ROOT/"trust.json",verifier.canonical(trust))
    pin=sha((EXEC_ROOT/"trust.json").read_bytes())
    return {"status":"EXECUTION_KEYS_ENROLLED_PURPOSE_ONLY",
            "trust_sha256":pin,"action_git_blob":ACTION_BLOB,
            "scope":verifier.PURPOSE,
            "private_keys_exported":False,
            "release_executed":False,"task_changed":False}


def issue(helper,verifier,trust_pin:str):
    require(type(trust_pin) is str and
            re.fullmatch(r"[0-9a-f]{64}",trust_pin) is not None,
            "EXECUTION_INDEPENDENT_TRUST_PIN_REQUIRED")
    require(EXEC_ROOT.is_dir() and not EXEC_ROOT.is_symlink(),
            "EXECUTION_ROOT_MISSING_OR_REPARSE")
    require((EXEC_ROOT/"keys").is_dir() and
            not (EXEC_ROOT/"keys").is_symlink(),
            "EXECUTION_KEYS_DIR_MISSING_OR_REPARSE")
    raw=(EXEC_ROOT/"trust.json").read_bytes()
    require(sha(raw)==trust_pin,"EXECUTION_TRUST_CHANGED")
    trust=verifier.strict_json(raw)
    require(trust["schema"]==verifier.TRUST_SCHEMA
            and trust["purpose"]==verifier.PURPOSE,
            "EXECUTION_TRUST_PURPOSE_CHANGED")
    require(not (EXEC_ROOT/"manifest.json").exists()
            and not (EXEC_ROOT/"packet.json").exists(),
            "EXECUTION_PACKET_ALREADY_ISSUED")
    verifier.review_and_source_gate()
    manifest=verifier.manifest_fields(ACTION_BLOB,OVERLAY_BLOB)
    statement=verifier.statement_for(manifest)
    signed=verifier.canonical(statement)
    keys={}
    for name in ("issuer","reviewer"):
        path=EXEC_ROOT/"keys"/(name+".pem")
        require(path.is_file() and not path.is_symlink() and
                0<path.stat().st_size<=8192,
                "EXECUTION_PRIVATE_ROLE_KEY_UNSAFE")
        key=serialization.load_pem_private_key(path.read_bytes(),password=None)
        require(isinstance(key,Ed25519PrivateKey) and
                public_b64(key)==trust[name+"_public_b64"],
                "EXECUTION_PRIVATE_ROLE_KEY_MISMATCH")
        keys[name]=key
    packet={"schema":verifier.PACKET_SCHEMA,"statement":statement}
    for name,key in keys.items():
        packet[name+"_signature_b64"]=base64.b64encode(key.sign(signed)).decode()
    verdict=verifier.verify_packet(trust,manifest,packet)
    require(verdict["status"]=="PASS" and
            verdict["old_public_stop_allowed"] is False
            and verdict["owner_os_reboot_allowed"] is False,
            "INDEPENDENT_OWNER_EXECUTION_VERIFIER_HOLD")
    helper.create_new(EXEC_ROOT/"manifest.json",verifier.canonical(manifest))
    helper.create_new(EXEC_ROOT/"packet.json",verifier.canonical(packet))
    result=verifier.inspect()
    require(result["status"]=="PASS" and
            result["windows_task_change_allowed"] is False,
            "EXECUTION_FINAL_READBACK_HOLD")
    return {"status":"SIGNED_EXACT_PARALLEL_EXEC_PACKET_VERIFIED",
            "trust_sha256":trust_pin,
            "manifest_sha256":sha(verifier.canonical(manifest)),
            "packet_sha256":sha(verifier.canonical(packet)),
            "authorized_actions":verdict["authorized_actions"],
            "old_public_process_stop_allowed":False,
            "windows_task_change_allowed":False,
            "private_db_access_allowed":False,
            "os_reboot_allowed":False,
            "private_keys_exported":False,
            "public_route_switched":False}


def main()->int:
    parser=argparse.ArgumentParser(description="CMP20 distinct owner signed parallel execution")
    parser.add_argument("action",choices=sorted(CONSENT))
    parser.add_argument("--owner-consent")
    parser.add_argument("--independent-trust-pin")
    a=parser.parse_args()
    try:
        require(os.name=="nt" and os.environ.get("COMPUTERNAME","").upper()=="YWSHTMR",
                "CMP20_OWNER_WINDOWS_ONLY")
        require(a.owner_consent==CONSENT[a.action],
                "OWNER_EXECUTION_CONSENT_REQUIRED")
        helper,verifier=modules()
        if a.action=="enroll-execution":
            require(a.independent_trust_pin is None,"UNEXPECTED_ENROLL_TRUST_PIN")
            output=setup(helper,verifier)
        else:
            output=issue(helper,verifier,a.independent_trust_pin)
        print(json.dumps(output,sort_keys=True))
        return 0
    except (SignHold,OSError,ValueError,TypeError,KeyError,
            subprocess.SubprocessError) as exc:
        why=str(exc) if isinstance(exc,SignHold) else "CMP20_SIGNER_HOLD"
        print(json.dumps({"status":"HOLD","reason":why,
                          "production_cutover_executed":False},sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
