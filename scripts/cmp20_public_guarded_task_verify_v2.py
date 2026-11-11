"""CMP20 guarded public 8879 Task V2: independent two-role Ed25519 verifier.

An owner-signed, source-specific V2 grant authorizes only a new fixed Windows
Task, guarded recovery of the already signed public-only candidate, automatic
public failback and exact public 8443 cutover. Original public/private processes,
DB, old Task, OS reboot and unrelated Serve routes are never authorized.
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

SCHEMA="legal-kb.cmp20.public-guarded-v2-exec-readback.v1"
TRUST_SCHEMA="legal-kb.cmp20.public-guarded-v2-trust.v1"
MANIFEST_SCHEMA="legal-kb.cmp20.public-guarded-v2-manifest.v1"
PACKET_SCHEMA="legal-kb.cmp20.public-guarded-v2-packet.v1"
PURPOSE="legal-kb.cmp20.owner-public-guarded-task-v2.v1"
RELEASE_ID="cmp20-public-demo-guarded-once-owner-v2"
TASK_NAME="RinkaLegalKBPublicGuardedOnceV2"
OWNER_HOST="YWSHTMR"
OWNER_SID="S-1-5-21-2008575412-695584821-1269537588-1001"
LOCAL=Path(os.environ.get("LOCALAPPDATA",""))
BASE=LOCAL/"RinkaMissionControl"
ROOT=BASE/"owner_approvals"/RELEASE_ID
RELEASE=BASE/"releases"/RELEASE_ID
V1_RELEASE=BASE/"releases"/"cmp20-public-demo-parallel-exec-v1"
V1_GRANT=BASE/"owner_approvals"/"cmp20-public-demo-parallel-exec-v1"
ORIGINAL=Path.home()/"Documents"/"LegalKB"/"public-demo-runtime"/"app-candidate"
OLD_SERVER=ORIGINAL/"implementation"/"phase7"/"003_web_server.py"
OLD_PUBLIC="http://127.0.0.1:8878"
NEW_PUBLIC="http://127.0.0.1:8879"
PUBLIC_HOST="ywshtmr.tail8fd68c.ts.net:8443"
OWNER_PYTHON="C:\\Python314\\python.exe"
V1_PACKET_SHA="85ff2a7d8fce2517e1ce41dd1b5c9307abb45e070832f4dbe32b9dd11c253904"
V1_RELEASE_MANIFEST_SHA="3e52a23072df61b774a5c06ecd37ea658222ddcccd8b4e186f7c29d2ae3a8346"
V1_LAUNCHER_SHA="cbb4bac8b80d5e5368a602ad8e8790158ea8fb5d330c028bf0d9fcad4f7ee763"
V1_PATCH_SHA="811089684c734609e3818a20104e80f5056758928e53e8ac5fa7321b8023a7f9"
V1_SOURCE_BLOBS={
 "cmp20_public_parallel_exec_verify.py":"253ef413c3b72f2de8b0d5df4ff68f478fca7bd8",
 "cmp20_public_parallel_owner_action.py":"1e1877226600ff2b4a17ff6497cb111b91b688ac",
 "cmp20_public_parallel_overlay.py":"4e07752f60d554987c9bd30dc513ae3af569ba57",
 "cmp20_public_release_review.py":"ae7f2cbd01dab3d6dd9823ce340be34ee95bbe3b",
}
ALLOWED=[
 "stage_exact_guarded_release",
 "register_exact_owner_interactive_task",
 "run_guarded_recovery_once",
 "exercise_candidate_only_fault_drill",
 "switch_public_8443_to_8879",
 "restore_public_8443_to_8878",
 "disable_exact_guarded_task",
]

class GuardHold(ValueError):
    pass

def require(ok,why):
    if not ok:
        raise GuardHold(why)

def sha(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()

def gitblob(raw:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\x00"+raw).hexdigest()

def canonical(obj:dict)->bytes:
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()

def safe_file(p:Path,max_size:int=120000)->bytes:
    require(p.is_file() and not p.is_symlink()
            and not (hasattr(p,"is_junction") and p.is_junction())
            and 0<p.stat().st_size<=max_size,"SIGNED_FILE_MISSING_OR_REPARSE")
    return p.read_bytes()

def safe_dir(p:Path):
    require(p.is_dir() and not p.is_symlink()
            and not (hasattr(p,"is_junction") and p.is_junction()),
            "SIGNED_DIRECTORY_MISSING_OR_REPARSE")

def strict_json(raw:bytes)->dict:
    def unique(pairs):
        d={}
        for k,v in pairs:
            require(k not in d,"SIGNED_JSON_DUPLICATE_KEY")
            d[k]=v
        return d
    def finite_float(s):
        f=float(s)
        require(math.isfinite(f),"SIGNED_JSON_NONFINITE_NUMBER")
        return f
    def reject_constant(_):
        raise GuardHold("SIGNED_JSON_INVALID_NUMBER")
    try:
        value=json.loads(raw.decode("utf-8"),object_pairs_hook=unique,
                         parse_float=finite_float,parse_constant=reject_constant)
    except (UnicodeError,json.JSONDecodeError,RecursionError):
        raise GuardHold("SIGNED_JSON_UNREADABLE") from None
    require(type(value) is dict,"SIGNED_JSON_OBJECT_REQUIRED")
    return value

def manifest_fields(guard_blob:str,verifier_blob:str)->dict:
    for h in (guard_blob,verifier_blob):
        require(type(h) is str and len(h)==40 and
                all(c in "0123456789abcdef" for c in h),
                "SIGNED_SOURCE_BLOB_FORMAT_HOLD")
    return {
        "schema":MANIFEST_SCHEMA,
        "purpose":PURPOSE,
        "release_id":RELEASE_ID,
        "owner_host":OWNER_HOST,
        "owner_sid":OWNER_SID,
        "task_name":TASK_NAME,
        "task_logon_type":"Interactive",
        "task_runlevel":"Limited",
        "task_repetition":"PT5M",
        "task_ignore_new":True,
        "task_allow_hard_terminate":False,
        "task_logon_trigger":True,
        "task_guard_command":OWNER_PYTHON,
        "task_argument":"-B "+str(RELEASE/"cmp20_public_guarded_owner_v2.py")+" --once",
        "v1_execution_packet_sha256":V1_PACKET_SHA,
        "v1_release_manifest_sha256":V1_RELEASE_MANIFEST_SHA,
        "v1_public_launcher_sha256":V1_LAUNCHER_SHA,
        "v1_patch_sha256":V1_PATCH_SHA,
        "guard_source_git_blob":guard_blob,
        "verifier_source_git_blob":verifier_blob,
        "v1_source_git_blobs":V1_SOURCE_BLOBS,
        "candidate_8879":"http://127.0.0.1:8879",
        "original_public_8878":OLD_PUBLIC,
        "private_8877":"READ_ONLY_NO_DATABASE_CHANGE",
        "public_funnel":PUBLIC_HOST,
        "authorized_actions":ALLOWED,
        "allow_stop_original_public":False,
        "allow_modify_existing_task":False,
        "allow_stop_other_process":False,
        "allow_change_private_database":False,
        "allow_windows_reboot":False,
        "allow_reset_tailscale":False,
        "allow_candidate_only_fault_injection":True,
        "require_original_public_fallback":True,
    }

def statement_for(m:dict)->dict:
    return {
        "purpose":PURPOSE,"release_id":RELEASE_ID,
        "task_name":TASK_NAME,
        "manifest_sha256":sha(canonical(m)),
        "guard_source_git_blob":m["guard_source_git_blob"],
        "verifier_source_git_blob":m["verifier_source_git_blob"],
        "authorized_actions":ALLOWED,
        "allow_modify_existing_task":False,
        "allow_stop_original_public":False,
        "allow_windows_reboot":False,
    }

def b64(s:str,n:int)->bytes:
    require(type(s) is str,"BAD_KEY_ENCODING")
    try:
        raw=base64.b64decode(s,validate=True)
    except (ValueError,TypeError):
        raise GuardHold("BAD_KEY_ENCODING") from None
    require(len(raw)==n,"BAD_KEY_LENGTH")
    return raw

def verify_packet(trust:dict,manifest:dict,packet:dict)->dict:
    require(type(trust) is dict and
            set(trust)=={"schema","purpose","issuer_public_b64","reviewer_public_b64"},
            "SIGNED_TRUST_FIELDS_HOLD")
    require(trust["schema"]==TRUST_SCHEMA and trust["purpose"]==PURPOSE,
            "SIGNED_TRUST_PURPOSE_HOLD")
    require(type(manifest) is dict and
            set(manifest)==set(manifest_fields("0"*40,"0"*40)),
            "SIGNED_MANIFEST_FIELDS_HOLD")
    require(manifest==manifest_fields(manifest["guard_source_git_blob"],
                                      manifest["verifier_source_git_blob"]),
            "SIGNED_MANIFEST_BROADENED_OR_DRIFTED")
    require(type(packet) is dict and
            set(packet)=={"schema","statement","issuer_signature_b64",
                          "reviewer_signature_b64"}
            and packet["schema"]==PACKET_SCHEMA,
            "SIGNED_PACKET_FIELDS_HOLD")
    required=statement_for(manifest)
    require(packet["statement"]==required,"SIGNED_PACKET_SCOPE_CHANGED")
    keys=[b64(trust[n+"_public_b64"],32) for n in ("issuer","reviewer")]
    require(keys[0]!=keys[1],"DISTINCT_ED25519_ROLES_REQUIRED")
    data=canonical(required)
    try:
        for i,n in enumerate(("issuer","reviewer")):
            Ed25519PublicKey.from_public_bytes(keys[i]).verify(
                b64(packet[n+"_signature_b64"],64),data)
    except (InvalidSignature,ValueError,TypeError):
        raise GuardHold("ED25519_SIGNATURE_INVALID") from None
    return {"status":"PASS","purpose":PURPOSE,"allowed_actions":ALLOWED,
            "existing_task_change_authority":False,
            "old_public_stop_authority":False,
            "os_reboot_authority":False}

def verify_owner_source_and_v1():
    require(os.name=="nt" and os.environ.get("COMPUTERNAME","").upper()==OWNER_HOST,
            "OWNER_YWSHTMR_ONLY")
    safe_dir(V1_RELEASE)
    safe_dir(V1_GRANT)
    require(sha(safe_file(V1_GRANT/"packet.json",8192))==V1_PACKET_SHA,
            "V1_EXECUTION_PACKET_CHANGED")
    require(sha(safe_file(V1_RELEASE/"manifest.json",16384))==
            V1_RELEASE_MANIFEST_SHA,"V1_SIGNED_RELEASE_CHANGED")
    require(sha(safe_file(V1_RELEASE/"launch-public-parallel.ps1",30000))==
            V1_LAUNCHER_SHA,"V1_PUBLIC_LAUNCHER_CHANGED")
    require(sha(safe_file(V1_RELEASE/"003_web_server.py"))==
            V1_PATCH_SHA,"V1_REVIEWED_SERVER_CHANGED")
    safe_dir(RELEASE)
    for n,h in V1_SOURCE_BLOBS.items():
        require(gitblob(safe_file(RELEASE/n,100000))==h,
                "V1_IMMUTABLE_SOURCE_CHANGED")
    script=RELEASE/"cmp20_public_parallel_exec_verify.py"
    spec=importlib.util.spec_from_file_location("cmp20_v1_guarded_ownership",script)
    require(spec is not None and spec.loader is not None,"V1_IMPORT_HOLD")
    m=importlib.util.module_from_spec(spec)
    prev=sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode=True
        spec.loader.exec_module(m)
    finally:
        sys.dont_write_bytecode=prev
    v1=m.inspect()
    require(v1["status"]=="PASS" and
            v1["old_public_stop_allowed"] is False and
            v1["owner_os_reboot_allowed"] is False,
            "V1_EXECUTION_SIGNATURE_HOLD")

def inspect()->dict:
    require(os.name=="nt" and os.environ.get("COMPUTERNAME","").upper()==OWNER_HOST,
            "OWNER_YWSHTMR_ONLY")
    safe_dir(ROOT)
    trust=strict_json(safe_file(ROOT/"trust.json",8192))
    manifest=strict_json(safe_file(ROOT/"manifest.json",16384))
    packet=strict_json(safe_file(ROOT/"packet.json",16384))
    v=verify_packet(trust,manifest,packet)
    safe_dir(RELEASE)
    require(gitblob(safe_file(RELEASE/"cmp20_public_guarded_owner_v2.py",120000))
            ==manifest["guard_source_git_blob"],"GUARDED_TASK_SOURCE_CHANGED")
    require(gitblob(safe_file(RELEASE/"cmp20_public_guarded_task_verify_v2.py",120000))
            ==manifest["verifier_source_git_blob"],"GUARDED_VERIFIER_SOURCE_CHANGED")
    verify_owner_source_and_v1()
    return {"schema":SCHEMA,**v,
            "signed_release_and_prior_ed25519_proof":"PASS",
            "private_database_unchanged":True,
            "task_registered_by_verification":False}

def main()->int:
    if sys.argv[1:]!=["--verify"]:
        print(json.dumps({"schema":SCHEMA,"status":"HOLD","reason":"VERIFY_ONLY"}))
        return 2
    try:
        print(json.dumps(inspect(),sort_keys=True));return 0
    except (GuardHold,OSError,ValueError,KeyError,TypeError) as e:
        why=str(e) if isinstance(e,GuardHold) else "OWNER_V2_SIGNED_VERIFIER_HOLD"
        print(json.dumps({"schema":SCHEMA,"status":"HOLD","reason":why},sort_keys=True))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
