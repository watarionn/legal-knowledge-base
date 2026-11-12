"""Owner-only exact signed CMP20 V3 candidate fault-drill completion v2.

Corrects a single V1 finish reader mismatch (original_public_pid versus the
actual sealed V3 old_public_pid). Both pre-fault/start and genuine natural V3
recovery receipts are immutable byte-pinned; NO candidate stop, no Task change.
"""
from __future__ import annotations
import base64
from datetime import datetime,timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import cmp20_v3_finish_verify_v2 as permit

QA=Path(__file__).resolve().parent
CONSENT_ENROLL="ENROLL CMP20 V3 EXACT FINISH V2 KEYS"
CONSENT_ISSUE="SIGN CMP20 V3 EXACT FINISH V2 PERMIT"
HELPER_BLOB="4199852e192349270096807af52d358ee89afe2b"
class Hold(ValueError):pass
def need(c,r):
    if not c:raise Hold(r)
def module(path,sha):
    need(permit.blob(permit.safe(path))==sha,"EXACT_DEPENDENCY_SOURCE_CHANGED")
    spec=importlib.util.spec_from_file_location("cmp20_finish_v2_"+path.stem,path)
    need(spec and spec.loader,"DEPENDENCY_UNIMPORTABLE")
    m=importlib.util.module_from_spec(spec)
    state=sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode=True
        spec.loader.exec_module(m)
    finally:sys.dont_write_bytecode=state
    return m
def helper():
    return module(QA/"cmp20_public_release_owner_signer.py",HELPER_BLOB)
def original():
    permit.original_signed()
    if str(permit.PREVIOUS) not in sys.path:
        sys.path.insert(0,str(permit.PREVIOUS))
    return module(permit.PREVIOUS/"cmp20_v3_candidate_drill_owner.py",
                  permit.PREVIOUS_OWNER_BLOB)
def sources(m=None):
    x={name:permit.blob(permit.safe(QA/name)) for name in permit.SOURCES}
    if m is not None:need(x==m["source_blobs"],"SIGNED_REVIEWED_SOURCE_CHANGED")
    return x
def pub(k):
    return base64.b64encode(k.public_key().public_bytes(
        serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
def enroll():
    permit.owner()
    permit.evidence()
    sources()
    need(not permit.TRUST.exists() and not permit.TRUST.is_symlink(),
         "FINISH_TRUST_ALREADY_EXISTS")
    h=helper()
    permit.TRUST.mkdir(mode=0o700)
    h.protect_new(permit.TRUST)
    folder=permit.TRUST/"keys"
    folder.mkdir(mode=0o700)
    h.protect_new(folder)
    keys={name:Ed25519PrivateKey.generate() for name in ("issuer","reviewer")}
    need(pub(keys["issuer"])!=pub(keys["reviewer"]),"TWO_ROLES_IDENTICAL")
    for name,k in keys.items():
        h.create_new(folder/(name+".pem"),k.private_bytes(
            serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
    trust={"schema":permit.T_SCHEMA,"purpose":permit.PURPOSE}
    for name,k in keys.items():trust[name+"_public_b64"]=pub(k)
    h.create_new(permit.TRUST/"trust.json",permit.canonical(trust))
    return {"status":"FINISH_TWO_ROLE_KEYS_ENROLLED",
            "trust_sha256":permit.sha(permit.canonical(trust)),
            "no_owner_process_or_task_mutation":True}
def issue(pin):
    permit.owner()
    need(type(pin) is str and re.fullmatch("[0-9a-f]{64}",pin),
         "INDEPENDENT_TRUST_PIN_REQUIRED")
    permit.evidence()
    need(not (permit.TRUST/"manifest.json").exists()
         and not (permit.TRUST/"packet.json").exists(),"FINISH_PACKET_EXISTS")
    trust_raw=permit.safe(permit.TRUST/"trust.json",8192)
    need(permit.sha(trust_raw)==pin,"INDEPENDENT_TRUST_PIN_DRIFT")
    trust=permit.parsed(trust_raw)
    manifest=permit.fields(sources())
    wire=permit.canonical(permit.claim(manifest))
    signed={}
    for role in ("issuer","reviewer"):
        key=serialization.load_pem_private_key(
            permit.safe(permit.TRUST/"keys"/(role+".pem"),8192),password=None)
        need(isinstance(key,Ed25519PrivateKey) and pub(key)==trust[role+"_public_b64"],
             "OWNER_SIGNER_ROLE_DRIFT")
        signed[role+"_signature_b64"]=base64.b64encode(key.sign(wire)).decode()
    packet={"schema":permit.P_SCHEMA,"statement":permit.claim(manifest),**signed}
    permit.verify_packet(trust,manifest,packet)
    h=helper()
    h.create_new(permit.TRUST/"manifest.json",permit.canonical(manifest))
    h.create_new(permit.TRUST/"packet.json",permit.canonical(packet))
    permit.verify_packet(
        permit.parsed(permit.safe(permit.TRUST/"trust.json",8192)),
        permit.parsed(permit.safe(permit.TRUST/"manifest.json",16384)),
        permit.parsed(permit.safe(permit.TRUST/"packet.json",16384)))
    return {"status":"FINISH_V2_TWO_ROLE_SIGNED",
            "manifest_sha256":permit.sha(permit.canonical(manifest)),
            "packet_sha256":permit.sha(permit.canonical(packet)),
            "source_blobs":manifest["source_blobs"]}
def stage():
    permit.owner()
    need(not permit.RELEASE.exists(),"FINISH_RELEASE_EXISTS")
    trust=permit.parsed(permit.safe(permit.TRUST/"trust.json",8192))
    manifest=permit.parsed(permit.safe(permit.TRUST/"manifest.json",16384))
    packet=permit.parsed(permit.safe(permit.TRUST/"packet.json",16384))
    permit.verify_packet(trust,manifest,packet)
    sources(manifest)
    h=helper()
    permit.RELEASE.mkdir(mode=0o700)
    h.protect_new(permit.RELEASE)
    for name in permit.SOURCES:
        h.create_new(permit.RELEASE/name,permit.safe(QA/name))
    report=permit.verify()
    need(report["status"]=="PASS","INDEPENDENT_FINISH_VERIFY_FAILED")
    return {"status":"FINISH_V2_PROTECTED_STAGE_PASS",
            "task_changed":False,"route_changed":False}
def check_recovered(start,recovered,tick):
    need(start.get("schema")=="legal-kb.cmp20.v3-signed-drill-start.v1"
         and start.get("status")=="CANDIDATE_STOPPED_ORIGINAL_PUBLIC_HEALTHY"
         and start.get("signed") is True
         and start.get("original_public_pid")==12736
         and start.get("candidate_stopped_pid")==9900,
         "SIGNED_ORIGINAL_FAULT_RECEIPT_MISMATCH")
    need(recovered.get("schema")=="legal-kb.cmp20.headless-v3-tick.v1"
         and recovered.get("status")=="PASS"
         and recovered.get("source_signed") is True
         and recovered.get("candidate_recovered") is True
         and recovered.get("old_public_pid")==12736
         and recovered.get("candidate_pid")==15972
         and recovered.get("candidate_8879_healthy") is True
         and recovered.get("old_public_8878_healthy") is True
         and recovered.get("private_8877_healthy") is True,
         "SIGNED_V3_RECEIPT_FIELD_OR_IDENTITY_CHANGED")
    need(tick.get("result")==0 and tick.get("missed")==0,
         "CURRENT_NATIVE_V3_TASK_NOT_PASS")
    natural=datetime.fromisoformat(recovered["checked_utc"].replace("Z","+00:00"))
    start_time=datetime.fromisoformat(start["started_utc"].replace("Z","+00:00"))
    last=datetime.fromisoformat(tick["last"].replace("Z","+00:00"))
    need(natural>start_time and
         last>=natural.replace(microsecond=0)-__import__("datetime").timedelta(seconds=10),
         "SIGNED_V3_NATURAL_RECOVERY_TIME_MISMATCH")

def finish():
    permit.verify()
    need(not (permit.RELEASE/"finish-result.json").exists(),
         "FINISH_RECEIPT_ALREADY_EXISTS")
    start,recovered=permit.evidence()
    previous=original()
    _,g,v2=previous.v3_runtime()
    with g.invisible_children():
        tick=previous.task_info(g,v2)
        check_recovered(start,recovered,tick)
        with v2.exclusive():
            oldpid=v2.require_old_and_private()
            need(oldpid==12736 and oldpid==start["original_public_pid"],
                 "ORIGINAL_PID_DRIFT")
            need(v2.proxy(v2.current_route())==v2.OLD,
                 "EXPECTED_SAFE_ORIGINAL_ROUTE_CHANGED")
            healthy,pid=v2.candidate_ok()
            need(healthy and pid==15972 and pid==recovered["candidate_pid"],
                 "REAL_RECOVERED_CANDIDATE_PID_DRIFT")
            v2.https_public_pass()
            v2.switch_route(v2.OLD,v2.NEW)
            need(v2.proxy(v2.current_route())==v2.NEW,
                 "EXACT_PUBLIC_ROUTE_RESTORE_FAILED")
            v2.https_public_pass()
            need(v2.port_owner(8878)["pid"]==oldpid,
                 "ORIGINAL_PUBLIC_PID_CHANGED")
            v2.require_old_and_private()
            receipt={
                "schema":"legal-kb.cmp20.v3-fault-drill-signed-finish-v2.v1",
                "status":"PASS",
                "source_signed":True,
                "owner":"YWSHTMR",
                "completed_utc":datetime.now(timezone.utc).isoformat(),
                "drill_start_sha256":permit.START_SHA,
                "signed_recovered_v3_receipt_sha256":permit.RECOVERED_SHA,
                "previous_drill_grant_sha256":permit.PREVIOUS_PACKET_SHA,
                "original_public_pid":oldpid,
                "signed_candidate_stopped_pid":9900,
                "recovered_candidate_pid":pid,
                "natural_v3_task_last_utc":tick["last"],
                "native_v3_last_result":0,
                "public_route":"http://127.0.0.1:8879",
                "private_8877_preserved":True,
                "original_8878_preserved":True,
                "candidate_8879_healthy":True,
                "public_8443_healthy":True,
                "no_task_modifications":True,
                "no_new_reboot":True}
            h=helper()
            h.create_new(permit.RELEASE/"finish-result.json",permit.canonical(receipt))
            need(permit.parsed(permit.safe(permit.RELEASE/"finish-result.json",8192))==
                 receipt,"PROTECTED_FINISH_RECEIPT_READBACK_FAILED")
            return {**receipt,"finish_receipt_sha256":permit.sha(permit.canonical(receipt))}
def inspect():
    permit.owner()
    return {"status":"SOURCE_ONLY_FINISH_V2","blobs":sources(),
            "trust_exists":permit.TRUST.exists(),
            "release_exists":permit.RELEASE.exists(),
            "finish_receipt_exists":(permit.RELEASE/"finish-result.json").exists()}
def main():
    args=sys.argv[1:]
    try:
        if args==["--inspect"]:out=inspect()
        elif args==["--enroll","--owner-consent",CONSENT_ENROLL]:out=enroll()
        elif len(args)==4 and args[:3]==["--issue","--owner-consent",CONSENT_ISSUE]:out=issue(args[3])
        elif args==["--stage"]:out=stage()
        elif args==["--finish"]:out=finish()
        else:raise Hold("FIXED_SIGNED_PURPOSE_ONLY")
        print(json.dumps(out,sort_keys=True));return 0
    except (Hold,permit.Hold,ValueError,OSError,KeyError,TypeError,ImportError):
        print(json.dumps({"status":"HOLD","reason":"SIGNED_FINISH_V2_GATE_FAILED",
                          "not_authorized_to_widen":True},sort_keys=True));return 2
if __name__=="__main__":raise SystemExit(main())
