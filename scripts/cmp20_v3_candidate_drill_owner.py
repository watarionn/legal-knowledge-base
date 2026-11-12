"""Signed exact CMP20 V3 candidate-only fault and natural-recovery drill.

One-time owner only. Before ever stopping candidate8879, move public HTTPS to
the preserved original8878 and prove it healthy. V3's existing, unmodified
5-min Task alone must restore candidate. Then a separate signed completion
action restores the already-proven new public route. Never reboot or touch
the original/private worker, other Tasks or other Funnel routes.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone, timedelta
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import cmp20_v3_candidate_drill_verify as signed

QA=Path(__file__).resolve().parent
V3=signed.V3
PYTHON=r"C:\Python314\python.exe"
OWNER_HELPER_BLOB="4199852e192349270096807af52d358ee89afe2b"
V3_GUARD_BLOB="44d7ac23e5d30c80e9287e3e27ab443f326efd5b"
V3_VERIFY_BLOB="8caff01ddb6f8d3f8619ed5d628f04b51de84eb1"
CONSENT_ENROLL="ENROLL CMP20 V3 EXACT CANDIDATE DRILL KEYS"
CONSENT_SIGN="SIGN CMP20 V3 EXACT CANDIDATE DRILL PERMIT"

class Stop(Exception):pass
def need(v,reason):
    if not v:raise Stop(reason)

def module(path,blob):
    need(signed.blob(signed.safe(path))==blob,"PINNED_MODULE_CHANGED")
    spec=importlib.util.spec_from_file_location("cmp20_signed_drill_dependency_"+path.stem,path)
    need(spec and spec.loader,"SIGNER_IMPORT_MISSING")
    obj=importlib.util.module_from_spec(spec)
    old=sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode=True
        spec.loader.exec_module(obj)
    finally:sys.dont_write_bytecode=old
    return obj

def v3_runtime():
    signed.owner()
    s=module(V3/"cmp20_headless_v3_verify.py",V3_VERIFY_BLOB)
    need(s.verify()["status"]=="PASS","PRIOR_V3_SIGNED_VERIFICATION_FAILED")
    g=module(V3/"cmp20_headless_v3_guard.py",V3_GUARD_BLOB)
    need(signed.sha(signed.safe(signed.V3_PACKET,16384))==signed.V3_PACKET_SHA,
         "PRIOR_V3_PACKET_CHANGED")
    return s,g,g.source_pinned(g.V2,s.V2_GUARD_BLOB)

def signer_helper():
    return module(QA/"cmp20_public_release_owner_signer.py",OWNER_HELPER_BLOB)

def checked_sources(manifest=None):
    r={name:signed.blob(signed.safe(QA/name)) for name in signed.SOURCES}
    if manifest is not None:need(r==manifest["source_blobs"],"REVIEWED_SOURCE_CHANGED")
    return r

def pub(k):
    return base64.b64encode(k.public_key().public_bytes(
        serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()

def enroll():
    signed.owner()
    v3_runtime()
    checked_sources()
    need(not signed.TRUST.exists() and not signed.TRUST.is_symlink(),
         "DRILL_TRUST_ALREADY_EXISTS")
    h=signer_helper()
    signed.TRUST.mkdir(mode=0o700)
    h.protect_new(signed.TRUST)
    root=signed.TRUST/"keys"
    root.mkdir(mode=0o700)
    h.protect_new(root)
    roles={name:Ed25519PrivateKey.generate() for name in ("issuer","reviewer")}
    need(pub(roles["issuer"])!=pub(roles["reviewer"]),"IDENTICAL_ROLES")
    for name,k in roles.items():
        h.create_new(root/(name+".pem"),k.private_bytes(
            serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
    trust={"schema":signed.TRUST_SCHEMA,"purpose":signed.PURPOSE}
    for name,k in roles.items():trust[name+"_public_b64"]=pub(k)
    h.create_new(signed.TRUST/"trust.json",signed.canonical(trust))
    need(signed.sha(signed.safe(signed.TRUST/"trust.json"))==
         signed.sha(signed.canonical(trust)),"TRUST_READBACK_FAILED")
    return {"status":"DRILL_KEYS_ENROLLED","trust_sha256":signed.sha(signed.canonical(trust)),
            "no_task_or_public_mutation":True,"no_private_key_export":True}

def issue(trust_sha):
    signed.owner()
    need(type(trust_sha) is str and re.fullmatch(r"[0-9a-f]{64}",trust_sha),
         "INDEPENDENT_PIN_REQUIRED")
    v3_runtime()
    need(not (signed.TRUST/"manifest.json").exists() and
         not (signed.TRUST/"packet.json").exists(),"DRILL_PACKET_ALREADY_ISSUED")
    trust_raw=signed.safe(signed.TRUST/"trust.json",8192)
    need(signed.sha(trust_raw)==trust_sha,"TRUST_SHA_CHANGED")
    trust=signed.parsed(trust_raw)
    manifest=signed.fields(checked_sources())
    claim=signed.canonical(signed.claim(manifest))
    signatures={}
    for role in ("issuer","reviewer"):
        k=serialization.load_pem_private_key(
            signed.safe(signed.TRUST/"keys"/(role+".pem"),8192),password=None)
        need(isinstance(k,Ed25519PrivateKey) and pub(k)==trust[role+"_public_b64"],
             "DRILL_SIGNER_MISMATCH")
        signatures[role+"_signature_b64"]=base64.b64encode(k.sign(claim)).decode()
    packet={"schema":signed.PACKET_SCHEMA,"statement":signed.claim(manifest),
            **signatures}
    signed.verify_packet(trust,manifest,packet)
    h=signer_helper()
    h.create_new(signed.TRUST/"manifest.json",signed.canonical(manifest))
    h.create_new(signed.TRUST/"packet.json",signed.canonical(packet))
    signed.verify_packet(
        signed.parsed(signed.safe(signed.TRUST/"trust.json")),
        signed.parsed(signed.safe(signed.TRUST/"manifest.json")),
        signed.parsed(signed.safe(signed.TRUST/"packet.json")))
    return {"status":"DRILL_DUAL_ROLE_SIGNED","packet_sha256":signed.sha(signed.canonical(packet)),
            "manifest_sha256":signed.sha(signed.canonical(manifest)),
            "source_blobs":manifest["source_blobs"],"task_modified":False}

def stage():
    signed.owner()
    need(not signed.RELEASE.exists(),"DRILL_STAGE_ALREADY_EXISTS")
    trust=signed.parsed(signed.safe(signed.TRUST/"trust.json",8192))
    manifest=signed.parsed(signed.safe(signed.TRUST/"manifest.json",16384))
    packet=signed.parsed(signed.safe(signed.TRUST/"packet.json",16384))
    signed.verify_packet(trust,manifest,packet)
    checked_sources(manifest)
    h=signer_helper()
    signed.RELEASE.mkdir(mode=0o700)
    h.protect_new(signed.RELEASE)
    for name in signed.SOURCES:
        h.create_new(signed.RELEASE/name,signed.safe(QA/name))
    out=signed.verify()
    need(out["status"]=="PASS","SIGNED_DRILL_STAGE_VERIFY_FAILED")
    return {"status":"SIGNED_DRILL_STAGE_PASS","signer_roles":2,
            "task_mutated":False,"public_route_mutated":False}

def private_receipt(name,data):
    need(name in ("drill-start.json","drill-finish.json"),
         "RECEIPT_NAME_OUT_OF_SCOPE")
    path=signed.RELEASE/name
    need(not path.exists() and not path.is_symlink(),"RECEIPT_EXISTS")
    wire=signed.canonical(data)
    need(len(wire)<8192,"RECEIPT_TOO_BIG")
    with path.open("xb") as f:
        f.write(wire)
        f.flush()
        os.fsync(f.fileno())
    need(signed.safe(path,8192)==wire,"RECEIPT_READBACK_FAILED")
    # Source pinned ACL helper protects the private receipt against other user read.
    signer_helper().protect_new(path)
    need(signed.safe(path,8192)==wire,"PROTECTED_RECEIPT_READBACK_FAILED")
    return signed.sha(wire)

def task_info(g,v2):
    with g.invisible_children():
        old=g.task_info(v2,"RinkaLegalKBPublicGuardedOnceV2")
        new=g.task_info(v2,"RinkaLegalKBPublicGuardedOnceV3")
        g.checked_old_task(old)
        g.check_new_task(new,require_ready=True)
        need(new["state"]=="Ready","V3_NATURAL_TASK_NOT_READY")
        cmd=(
          "$ErrorActionPreference='Stop';"
          "$i=Get-ScheduledTaskInfo -TaskName 'RinkaLegalKBPublicGuardedOnceV3';"
          "[pscustomobject]@{"
          "at=(Get-Date).ToUniversalTime().ToString('o');"
          "last=$i.LastRunTime.ToUniversalTime().ToString('o');"
          "next=$i.NextRunTime.ToUniversalTime().ToString('o');"
          "result=[int]$i.LastTaskResult;"
          "missed=[int]$i.NumberOfMissedRuns"
          "}|ConvertTo-Json -Compress")
        return json.loads(v2.shell(cmd,timeout=25))

def clock(iso):
    return datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone(timezone.utc)

def signed_start_state(tick,now,route_new=True):
    need(tick["result"]==0 and tick["missed"]==0,
         "NATIVE_V3_TICK_NOT_PASS")
    need(timedelta(seconds=0)<=clock(now)-clock(tick["last"])<=timedelta(minutes=12),
         "STALE_TASK_TICK")
    if route_new:
        need(clock(tick["next"])-clock(now)>=timedelta(seconds=60),
             "NATURAL_TICK_IMMINENT_RETRY_LATER")

def drill():
    signed.verify()
    need(not (signed.RELEASE/"drill-start.json").exists(),
         "DRILL_ALREADY_STARTED")
    gsign,g,v2=v3_runtime()
    with g.invisible_children():
        tick=task_info(g,v2)
        signed_start_state(tick,tick["at"])
        with v2.exclusive():
            oldpid=v2.require_old_and_private()
            need(v2.proxy(v2.current_route())==v2.NEW,"CANDIDATE_NOT_PUBLIC_ROUTE")
            good,pid=v2.candidate_ok()
            need(good and type(pid) is int and pid>0,
                 "CANDIDATE_NOT_IDENTIFIED_HEALTHY")
            v2.https_public_pass()
            # Public redirect is completed BEFORE candidate-only controlled fault.
            v2.switch_route(v2.NEW,v2.OLD)
            need(v2.proxy(v2.current_route())==v2.OLD,
                 "SAFE_ORIGINAL_PUBLIC_FALLBACK_FAILED")
            v2.https_public_pass()
            need(v2.port_owner(8878)["pid"]==oldpid,
                 "ORIGINAL_PUBLIC_PID_CHANGED")
            try:
                stopped=v2.stop_candidate_only()
            except Exception:
                # Fail closed: keep HTTPS on healthy original; never force another worker.
                raise
            need(stopped==pid,"STOPPED_PID_NOT_SIGNED_CANDIDATE")
            need(v2.port_owner(8878)["pid"]==oldpid and
                 v2.proxy(v2.current_route())==v2.OLD,
                 "ORIGINAL_SAFE_FALLBACK_CHANGED")
            v2.https_public_pass()
            result={
                "schema":"legal-kb.cmp20.v3-signed-drill-start.v1",
                "status":"CANDIDATE_STOPPED_ORIGINAL_PUBLIC_HEALTHY",
                "signed":True,"owner":"YWSHTMR",
                "started_utc":datetime.now(timezone.utc).isoformat(),
                "drill_task":"RinkaLegalKBPublicGuardedOnceV3",
                "pre_fault_last_task_utc":tick["last"],
                "original_public_pid":oldpid,
                "candidate_stopped_pid":stopped,
                "expected_next_natural_task_utc":tick["next"],
                "route":"http://127.0.0.1:8878",
                "no_original_private_stop":True,
            }
            result["receipt_sha256"]=private_receipt("drill-start.json",result)
            return result

def check_after(start,tick,v3_receipt):
    need(start.get("schema")=="legal-kb.cmp20.v3-signed-drill-start.v1"
         and start.get("status")=="CANDIDATE_STOPPED_ORIGINAL_PUBLIC_HEALTHY"
         and start.get("signed") is True,"DRILL_START_PROOF_INVALID")
    need(tick.get("result")==0,"NATIVE_RECOVERY_TASK_FAILED")
    need(clock(tick["last"])>clock(start["started_utc"]),
         "NO_POST_FAULT_NATURAL_TICK")
    need(v3_receipt.get("schema")=="legal-kb.cmp20.headless-v3-tick.v1"
         and v3_receipt.get("status")=="PASS"
         and v3_receipt.get("source_signed") is True
         and v3_receipt.get("candidate_recovered") is True
         and v3_receipt.get("original_public_pid")==start["original_public_pid"]
         and v3_receipt.get("candidate_pid")!=start["candidate_stopped_pid"]
         and v3_receipt.get("candidate_8879_healthy") is True
         and v3_receipt.get("old_public_8878_healthy") is True
         and v3_receipt.get("private_8877_healthy") is True,
         "V3_SIGNED_NATURAL_RECOVERY_NOT_PROVEN")
    checked=clock(v3_receipt["checked_utc"])
    need(clock(tick["last"])-timedelta(seconds=10)<=checked<=
         clock(tick["last"])+timedelta(seconds=115),
         "NATIVE_V3_RECOVERY_RECEIPT_TIMING_MISMATCH")

def finish():
    signed.verify()
    need(not (signed.RELEASE/"drill-finish.json").exists(),
         "DRILL_ALREADY_COMPLETED")
    start=signed.parsed(signed.safe(signed.RELEASE/"drill-start.json",8192))
    proof=signed.parsed(signed.safe(V3/"last-pass.json",8192))
    gsign,g,v2=v3_runtime()
    with g.invisible_children():
        tick=task_info(g,v2)
        check_after(start,tick,proof)
        with v2.exclusive():
            oldpid=v2.require_old_and_private()
            need(oldpid==start["original_public_pid"],
                 "ORIGINAL_PUBLIC_PID_CHANGED")
            need(v2.proxy(v2.current_route())==v2.OLD,
                 "SAFE_ORIGINAL_ROUTE_CHANGED")
            ok,pid=v2.candidate_ok()
            need(ok and pid==proof["candidate_pid"] and
                 pid!=start["candidate_stopped_pid"],
                 "RECOVERED_CANDIDATE_IDENTITY_CHANGED")
            v2.https_public_pass()
            v2.switch_route(v2.OLD,v2.NEW)
            need(v2.proxy(v2.current_route())==v2.NEW,
                 "PUBLIC_RESTORE_TO_RECOVERED_CANDIDATE_FAILED")
            v2.https_public_pass()
            need(v2.port_owner(8878)["pid"]==oldpid,
                 "ORIGINAL_PUBLIC_PID_CHANGED_AFTER_RESTORE")
            result={
                "schema":"legal-kb.cmp20.v3-signed-drill-finish.v1",
                "status":"V3_NATURAL_CANDIDATE_RECOVERED_AND_PUBLIC_RESTORED",
                "source_signed":True,"owner":"YWSHTMR",
                "closed_utc":datetime.now(timezone.utc).isoformat(),
                "old_pid":oldpid,"stopped_candidate_pid":start["candidate_stopped_pid"],
                "recovered_pid":pid,
                "native_task_utc":tick["last"],"native_result":0,
                "natural_v3_receipt_sha256":signed.sha(
                    signed.safe(V3/"last-pass.json",8192)),
                "public_route":"http://127.0.0.1:8879",
                "no_original_private_stop":True,
                "no_task_modification":True,"no_os_reboot":True,
            }
            result["receipt_sha256"]=private_receipt("drill-finish.json",result)
            return result

def inspect():
    signed.owner()
    return {"status":"READ_ONLY_DRILL_SOURCE",
            "sources":checked_sources(),
            "trust_created":signed.TRUST.exists(),
            "release_staged":signed.RELEASE.exists(),
            "drill_started":(signed.RELEASE/"drill-start.json").exists(),
            "drill_completed":(signed.RELEASE/"drill-finish.json").exists()}

def main():
    args=sys.argv[1:]
    try:
        if args==["--inspect"]:r=inspect()
        elif args==["--enroll","--owner-consent",CONSENT_ENROLL]:r=enroll()
        elif len(args)==4 and args[:3]==["--issue","--owner-consent",CONSENT_SIGN]:r=issue(args[3])
        elif args==["--stage"]:r=stage()
        elif args==["--drill"]:r=drill()
        elif args==["--finish"]:r=finish()
        else:raise Stop("FIXED_SIGNED_OWNER_ACTION_ONLY")
        print(json.dumps(r,sort_keys=True));return 0
    except (Stop,signed.Hold,OSError,ValueError,KeyError,TypeError,
            subprocess.TimeoutExpired,RuntimeError,ImportError):
        print(json.dumps({"status":"HOLD","reason":"SIGNED_DRILL_EXACT_GATE_FAILED",
                          "scope_escalated":False},sort_keys=True));return 2

if __name__=="__main__":raise SystemExit(main())
