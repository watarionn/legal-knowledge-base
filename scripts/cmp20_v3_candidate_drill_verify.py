"""Independent owner two-role signed CMP20 V3 canary-drill grant verifier.

No Task control, arbitrary commands, OS reboot, original public stop or
private DB authority. Owner-only exact V3 signed release and exact 8879 PID.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

BASE=Path(os.environ.get("LOCALAPPDATA",""))/"RinkaMissionControl"
ID="cmp20-v3-candidate-drill-owner-v1"
TRUST=BASE/"owner_approvals"/ID
RELEASE=BASE/"releases"/ID
V3=BASE/"releases"/"cmp20-headless-guard-owner-v3"
V3_PACKET=BASE/"owner_approvals"/"cmp20-headless-guard-owner-v3"/"packet.json"
V3_PACKET_SHA="e8e4439b62a2d03d6703f62581887cd3e2bb8d48f578e64859beba76b95d5c2c"
OWNER="YWSHTMR"
SID="S-1-5-21-2008575412-695584821-1269537588-1001"
PURPOSE="legal-kb.cmp20.owner-exact-candidate-8879-fault-drill-v1"
SOURCES=("cmp20_v3_candidate_drill_verify.py","cmp20_v3_candidate_drill_owner.py")
TRUST_SCHEMA="legal-kb.cmp20.v3-drill-trust.v1"
MANIFEST_SCHEMA="legal-kb.cmp20.v3-drill-manifest.v1"
PACKET_SCHEMA="legal-kb.cmp20.v3-drill-packet.v1"
ALLOWED=("create_two_new_private_ed25519_keys","issue_exact_scope_packet",
         "stage_immutable_verified_drill_only",
         "fallback_exact_public_8443_new8879_to_old8878",
         "stop_exact_signed_candidate_8879_only_after_old_https_pass",
         "observe_only_natural_v3_task_recovery",
         "restore_public_8443_old8878_to_new8879_after_proven_recovery")
FORBIDDEN=("stop_original_8878","write_private_8877_or_db",
           "modify_any_windows_task","stop_unrelated_process",
           "reboot_os","change_unrelated_routes","modify_signed_v2_or_v3")

class Hold(ValueError):
    pass

def need(ok,reason):
    if not ok:raise Hold(reason)

def sha(b):return hashlib.sha256(b).hexdigest()
def blob(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def canonical(d):return json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()

def safe(path,limit=120000):
    need(path.is_file() and not path.is_symlink()
         and not (hasattr(path,"is_junction") and path.is_junction())
         and 0<path.stat().st_size<=limit,"UNSAFE_SOURCE_FILE")
    return path.read_bytes()

def parsed(raw):
    def pairs(p):
        r={}
        for k,v in p:
            need(k not in r,"DUPLICATE_JSON")
            r[k]=v
        return r
    try:
        d=json.loads(raw.decode("utf-8"),object_pairs_hook=pairs,
                     parse_constant=lambda _:(_ for _ in ()).throw(Hold("NONFINITE")))
    except (ValueError,UnicodeError,RecursionError):
        raise Hold("MALFORMED_JSON") from None
    need(type(d) is dict,"JSON_OBJECT_REQUIRED")
    return d

def owner():
    need(os.name=="nt" and os.getenv("COMPUTERNAME","").upper()==OWNER
         and os.getenv("USERNAME","").casefold()=="watar",
         "NOT_OWNER_WINDOWS")

def fields(sources):
    need(type(sources) is dict and set(sources)==set(SOURCES),
         "SOURCE_MANIFEST_FILES_CHANGED")
    need(all(type(v) is str and len(v)==40 and
             all(c in "0123456789abcdef" for c in v)
             for v in sources.values()),"SOURCE_SHA_INVALID")
    return {
        "schema":MANIFEST_SCHEMA,"purpose":PURPOSE,
        "owner_host":OWNER,"owner_sid":SID,
        "release_id":ID,"source_blobs":sources,
        "prior_v3_packet_sha256":V3_PACKET_SHA,
        "prior_v3_verifier_blob":"8caff01ddb6f8d3f8619ed5d628f04b51de84eb1",
        "prior_v3_guard_blob":"44d7ac23e5d30c80e9287e3e27ab443f326efd5b",
        "task":"RinkaLegalKBPublicGuardedOnceV3",
        "pythonw":r"C:\Python314\pythonw.exe",
        "public_https_port":8443,"candidate_port":8879,
        "original_port":8878,"private_port":8877,
        "natural_tick_window_minutes":12,
        "allowed_actions":list(ALLOWED),"forbidden_actions":list(FORBIDDEN),
    }

def claim(manifest):
    return {"schema":PACKET_SCHEMA,"purpose":PURPOSE,"release_id":ID,
            "manifest_sha256":sha(canonical(manifest))}

def decode(x,length):
    need(type(x) is str,"B64_NOT_STRING")
    try:r=base64.b64decode(x,validate=True)
    except (ValueError,TypeError):raise Hold("INVALID_BASE64") from None
    need(len(r)==length,"B64_LENGTH_CHANGED")
    return r

def verify_packet(trust,manifest,packet):
    need(type(trust) is dict and set(trust)=={"schema","purpose","issuer_public_b64","reviewer_public_b64"}
         and trust["schema"]==TRUST_SCHEMA and trust["purpose"]==PURPOSE,
         "TRUST_PURPOSE_CHANGED")
    need(type(manifest) is dict and manifest==fields(manifest.get("source_blobs")),
         "MANIFEST_SCOPE_CHANGED")
    need(type(packet) is dict and
         set(packet)=={"schema","statement","issuer_signature_b64","reviewer_signature_b64"}
         and packet["schema"]==PACKET_SCHEMA and packet["statement"]==claim(manifest),
         "PACKET_SCOPE_CHANGED")
    pubs=[decode(trust[x+"_public_b64"],32) for x in ("issuer","reviewer")]
    need(pubs[0]!=pubs[1],"ROLES_NOT_DISTINCT")
    wire=canonical(claim(manifest))
    for i,role in enumerate(("issuer","reviewer")):
        try:Ed25519PublicKey.from_public_bytes(pubs[i]).verify(decode(packet[role+"_signature_b64"],64),wire)
        except (InvalidSignature,ValueError,TypeError):raise Hold("ED25519_ROLE_DENIED") from None

def verify():
    owner()
    need(sha(safe(V3_PACKET,16384))==V3_PACKET_SHA,"PRIOR_V3_PACKET_DRIFT")
    need(TRUST.is_dir() and RELEASE.is_dir() and not TRUST.is_symlink()
         and not RELEASE.is_symlink(),"OWNER_SIGNED_STAGE_MISSING")
    trust=parsed(safe(TRUST/"trust.json",8192))
    manifest=parsed(safe(TRUST/"manifest.json",16384))
    packet=parsed(safe(TRUST/"packet.json",16384))
    verify_packet(trust,manifest,packet)
    for name,git_sha in manifest["source_blobs"].items():
        need(blob(safe(RELEASE/name))==git_sha,"INSTALLED_SOURCE_DRIFT")
    # Independently validate genuine V3 release; no V3 source modifications.
    sys.path.insert(0,str(V3))
    import cmp20_headless_v3_verify as v3
    need(v3.verify()["status"]=="PASS","PRIOR_V3_SIGNED_VERIFY_HOLD")
    return {"status":"PASS","purpose":PURPOSE,"independent_roles":2,
            "v3_signed_release":"PASS","task_mutated":False}

def main():
    if sys.argv[1:]!=["--verify"]:
        print(json.dumps({"status":"HOLD","reason":"READ_ONLY_VERIFY_ONLY"}));return 2
    try:r=verify();print(json.dumps(r,sort_keys=True));return 0
    except (Hold,OSError,TypeError,ValueError,KeyError,ImportError):
        print(json.dumps({"status":"HOLD","reason":"SIGNED_DRILL_GRANT_INVALID"}));return 2

if __name__=="__main__":raise SystemExit(main())
