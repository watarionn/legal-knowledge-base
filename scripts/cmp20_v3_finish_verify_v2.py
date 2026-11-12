"""Separate exact corrective owner permit for CMP20 V3 signed fault closeout.

The initial V1 drill safely proved natural candidate recovery but its --finish
reader used the wrong receipt key. This version only restores public
HTTPS8443 old8878 -> already recovered candidate8879 after pinning original
signed stop proof and exact 15:15 V3 recovery bytes. It never repeats fault.
"""
from __future__ import annotations
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

BASE=Path(os.environ.get("LOCALAPPDATA",""))/"RinkaMissionControl"
ID="cmp20-v3-candidate-finish-owner-v2"
TRUST=BASE/"owner_approvals"/ID
RELEASE=BASE/"releases"/ID
PREVIOUS=BASE/"releases"/"cmp20-v3-candidate-drill-owner-v1"
PREVIOUS_PACKET=BASE/"owner_approvals"/"cmp20-v3-candidate-drill-owner-v1"/"packet.json"
PREVIOUS_PACKET_SHA="3f85a01b1030d4dc6645fe52d7792a9c13a60b02cdbbcae722ae6a7a2354a8d0"
PREVIOUS_VERIFY_BLOB="4d09991e9d8e624eb67ca4f7d96962fb843228f9"
PREVIOUS_OWNER_BLOB="0935d5bee16e6c445b1dbcc4ef1739c45e075c35"
START_SHA="99ec7c2f0ab8d0d83cdf15c6d4bf0df6683ae3489de8c00d5d7c3cca32eb3d8b"
RECOVERED_SHA="11d6b4de644c0e6169d0b82e625ac6624b289d34bf96e2efb61855394db2191b"
OWNER="YWSHTMR"
OWNER_SID="S-1-5-21-2008575412-695584821-1269537588-1001"
PURPOSE="legal-kb.cmp20.owner-exact-8878-to-recovered-8879-finish-v2"
SOURCES=("cmp20_v3_finish_verify_v2.py","cmp20_v3_finish_owner_v2.py")
T_SCHEMA="legal-kb.cmp20.v3-finish-trust.v2"
M_SCHEMA="legal-kb.cmp20.v3-finish-manifest.v2"
P_SCHEMA="legal-kb.cmp20.v3-finish-packet.v2"

class Hold(ValueError):pass
def need(c,reason):
    if not c:raise Hold(reason)
def sha(b):return hashlib.sha256(b).hexdigest()
def blob(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def safe(path,limit=120000):
    need(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=limit,"SOURCE_MISSING_UNSAFE")
    return path.read_bytes()
def parsed(b):
    def pairs(items):
        o={}
        for k,v in items:
            need(k not in o,"DUPLICATE_JSON_KEY")
            o[k]=v
        return o
    try:r=json.loads(b.decode("utf-8"),object_pairs_hook=pairs,
                     parse_constant=lambda _:(_ for _ in ()).throw(Hold("NAN_DENIED")))
    except (UnicodeError,ValueError,RecursionError):
        raise Hold("INVALID_JSON") from None
    need(type(r) is dict,"JSON_OBJECT_REQUIRED")
    return r
def owner():
    need(os.name=="nt" and os.getenv("COMPUTERNAME","").upper()==OWNER
         and os.getenv("USERNAME","").casefold()=="watar","WRONG_OWNER")

def fields(blobs):
    need(type(blobs) is dict and set(blobs)==set(SOURCES),"REVIEWED_SOURCES_CHANGED")
    need(all(type(b) is str and len(b)==40 and
         all(ch in "0123456789abcdef" for ch in b) for b in blobs.values()),
         "BAD_GIT_BLOB")
    return {
      "schema":M_SCHEMA,"purpose":PURPOSE,"release":ID,"host":OWNER,
      "sid":OWNER_SID,"source_blobs":blobs,
      "previous_signed_packet_sha256":PREVIOUS_PACKET_SHA,
      "previous_verifier_git_blob":PREVIOUS_VERIFY_BLOB,
      "previous_owner_git_blob":PREVIOUS_OWNER_BLOB,
      "signed_start_receipt_sha256":START_SHA,
      "signed_v3_natural_recovery_receipt_sha256":RECOVERED_SHA,
      "original_public_pid":12736,
      "stopped_candidate_pid":9900,
      "recovered_candidate_pid":15972,
      "exact_public_route_from":"http://127.0.0.1:8878",
      "exact_public_route_to":"http://127.0.0.1:8879",
      "task":"RinkaLegalKBPublicGuardedOnceV3",
      "allowed":["enroll_new_private_two_role_keys","issue_exact_source_bound_packet",
                 "stage_immutable_owner_release","restore_public_only_after_signed_recovery"],
      "forbidden":["stop_any_process","modify_any_windows_task",
                   "edit_signed_v2_v3_drill_v1","reboot_os","write_private_8877",
                   "modify_other_routes","skip_native_signed_recovery_proof"],
    }
def claim(m):return {"schema":P_SCHEMA,"purpose":PURPOSE,"release":ID,
                     "manifest_sha256":sha(canonical(m))}
def b64(data,size):
    need(type(data) is str,"NOT_BASE64_STRING")
    try:r=base64.b64decode(data,validate=True)
    except (ValueError,TypeError):raise Hold("INVALID_BASE64") from None
    need(len(r)==size,"BASE64_LENGTH_BAD")
    return r
def verify_packet(trust,manifest,packet):
    need(type(trust) is dict and set(trust)=={"schema","purpose","issuer_public_b64","reviewer_public_b64"}
         and trust["schema"]==T_SCHEMA and trust["purpose"]==PURPOSE,"TRUST_CHANGED")
    need(type(manifest) is dict and manifest==fields(manifest.get("source_blobs")),
         "MANIFEST_SCOPE_CHANGED")
    need(type(packet) is dict and
         set(packet)=={"schema","statement","issuer_signature_b64","reviewer_signature_b64"}
         and packet["schema"]==P_SCHEMA and packet["statement"]==claim(manifest),
         "PACKET_SCOPE_CHANGED")
    pubs=[b64(trust[role+"_public_b64"],32) for role in ("issuer","reviewer")]
    need(pubs[0]!=pubs[1],"SAME_OWNER_SIGNER")
    msg=canonical(claim(manifest))
    for i,role in enumerate(("issuer","reviewer")):
        try:Ed25519PublicKey.from_public_bytes(pubs[i]).verify(
            b64(packet[role+"_signature_b64"],64),msg)
        except (InvalidSignature,ValueError,TypeError):
            raise Hold("SIGNATURE_INVALID") from None

def original_signed():
    owner()
    need(sha(safe(PREVIOUS_PACKET,16384))==PREVIOUS_PACKET_SHA,"PRIOR_DRILL_GRANT_CHANGED")
    need(blob(safe(PREVIOUS/"cmp20_v3_candidate_drill_verify.py"))==
         PREVIOUS_VERIFY_BLOB,"PRIOR_DRILL_VERIFIER_CHANGED")
    p=PREVIOUS/"cmp20_v3_candidate_drill_verify.py"
    spec=importlib.util.spec_from_file_location("cmp20_pinned_drill_verifier",p)
    need(spec and spec.loader,"PRIOR_VERIFIER_NOT_IMPORTABLE")
    mod=importlib.util.module_from_spec(spec)
    before=sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode=True
        spec.loader.exec_module(mod)
    finally:sys.dont_write_bytecode=before
    need(mod.verify()["status"]=="PASS","PRIOR_DRILL_SIGNATURE_HOLD")
    need(blob(safe(PREVIOUS/"cmp20_v3_candidate_drill_owner.py"))==
         PREVIOUS_OWNER_BLOB,"PRIOR_DRILL_OWNER_CHANGED")
    return mod

def evidence():
    prior=original_signed()
    start_path=PREVIOUS/"drill-start.json"
    recovery_path=PREVIOUS/"verified-natural-recovery-20261112.json"
    need(sha(safe(start_path,8192))==START_SHA,"DRILL_START_EVIDENCE_DRIFT")
    need(sha(safe(recovery_path,8192))==RECOVERED_SHA,
         "NATIVE_RECOVERY_BYTES_NOT_PRESERVED")
    return parsed(safe(start_path,8192)),parsed(safe(recovery_path,8192))

def verify():
    owner()
    evidence()
    need(TRUST.is_dir() and RELEASE.is_dir() and
         not TRUST.is_symlink() and not RELEASE.is_symlink(),
         "NEW_FINISH_SIGNED_STAGE_MISSING")
    trust=parsed(safe(TRUST/"trust.json",8192))
    manifest=parsed(safe(TRUST/"manifest.json",16384))
    packet=parsed(safe(TRUST/"packet.json",16384))
    verify_packet(trust,manifest,packet)
    for name,git_sha in manifest["source_blobs"].items():
        need(blob(safe(RELEASE/name))==git_sha,"NEW_FINISH_SOURCE_DRIFT")
    return {"status":"PASS","purpose":PURPOSE,"independent_owner_signers":2,
            "signed_prior_drill":"PASS","original_signed_v3_recovery":"PASS",
            "task_and_services_modified":False}
def main():
    if sys.argv[1:]!=["--verify"]:
        print(json.dumps({"status":"HOLD","reason":"READ_ONLY_VERIFY_ONLY"}));return 2
    try:
        print(json.dumps(verify(),sort_keys=True));return 0
    except (Hold,OSError,TypeError,ValueError,KeyError,ImportError):
        print(json.dumps({"status":"HOLD","reason":"SIGNED_FINISH_SCOPE_OR_PROOF_INVALID"}));return 2
if __name__=="__main__":raise SystemExit(main())
