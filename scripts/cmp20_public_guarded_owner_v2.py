"""CMP20 fixed owner-signed V2 public guardian, exact Task and reversible Funnel.

The already signed V1 public patch/launcher remain immutable. V2 fixes
the inherited-pipe deadlock by launching detached PowerShell with stdout/stderr
DEVNULL, then separately proving real 8879 PID and HTTP. Exactly one NEW Task
may run on owner interactive-logon and five-minute daily repetition. A dead
candidate can be replaced while the original 8878 remains ready as fallback.
Never stops/modifies the original 8878 process/Task, private 8877 or DB.
"""
from __future__ import annotations

import base64
import contextlib
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

VERIFY_BLOB="3e58401b0882022e69ed9a2548d88ab73fcc4448"
HELPER_BLOB="4199852e192349270096807af52d358ee89afe2b"
OWNER_HOST="YWSHTMR"
RELEASE_ID="cmp20-public-demo-guarded-once-owner-v2"
TASK="RinkaLegalKBPublicGuardedOnceV2"
BASE=Path(os.environ.get("LOCALAPPDATA",""))/"RinkaMissionControl"
TRUST=BASE/"owner_approvals"/RELEASE_ID
RELEASE=BASE/"releases"/RELEASE_ID
V1=BASE/"releases"/"cmp20-public-demo-parallel-exec-v1"
OLD="http://127.0.0.1:8878"
NEW="http://127.0.0.1:8879"
HOST="ywshtmr.tail8fd68c.ts.net:8443"
CONSENT={
 "--enroll":"ENROLL CMP20 GUARDED V2 TASK ONLY EXECUTION KEYS",
 "--issue":"ISSUE CMP20 GUARDED V2 TASK ONLY EXECUTION PACKET",
}

class GuardianHold(ValueError):
    pass

def require(ok:bool,why:str):
    if not ok:
        raise GuardianHold(why)

def blob(data:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\x00"+data).hexdigest()

def sha(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def safe_file(path:Path,max_len:int=130000)->bytes:
    require(path.is_file() and not path.is_symlink()
            and not (hasattr(path,"is_junction") and path.is_junction())
            and 0<path.stat().st_size<=max_len,"GUARDIAN_FILE_MISSING_OR_REPARSE")
    return path.read_bytes()

def require_owner():
    require(os.name=="nt" and os.environ.get("COMPUTERNAME","").upper()==OWNER_HOST,
            "CMP20_OWNER_WINDOWS_ONLY")

def pinned_module(path:Path,expected:str):
    require(blob(safe_file(path))==expected,"GUARDIAN_PINNED_MODULE_DRIFT")
    spec=importlib.util.spec_from_file_location("cmp20_v2_"+path.stem,path)
    require(spec is not None and spec.loader is not None,"GUARDIAN_IMPORT_HOLD")
    m=importlib.util.module_from_spec(spec)
    previous=sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode=True
        spec.loader.exec_module(m)
    finally:
        sys.dont_write_bytecode=previous
    return m

def verifier():
    path=Path(__file__).resolve().parent/"cmp20_public_guarded_task_verify_v2.py"
    return pinned_module(path,VERIFY_BLOB)

def helper():
    path=Path(__file__).resolve().parent/"cmp20_public_release_owner_signer.py"
    return pinned_module(path,HELPER_BLOB)

def source_preflight(v):
    require_owner()
    require(sha(safe_file(v.V1_GRANT/"packet.json",8192))==v.V1_PACKET_SHA,
            "PRIOR_V1_EXEC_PACKET_CHANGED")
    require(sha(safe_file(v.V1_RELEASE/"manifest.json",16384))==
            v.V1_RELEASE_MANIFEST_SHA,"PRIOR_V1_STAGE_CHANGED")
    require(sha(safe_file(v.V1_RELEASE/"launch-public-parallel.ps1",30000))==
            v.V1_LAUNCHER_SHA,"PRIOR_PUBLIC_LAUNCHER_DRIFT")
    require(sha(safe_file(v.V1_RELEASE/"003_web_server.py"))==
            v.V1_PATCH_SHA,"PRIOR_PUBLIC_PATCH_DRIFT")
    scripts=Path(__file__).resolve().parent
    for name,digest in v.V1_SOURCE_BLOBS.items():
        require(blob(safe_file(scripts/name))==digest,
                "PRIOR_SIGNED_V1_SOURCE_DRIFT")
    m=pinned_module(scripts/"cmp20_public_parallel_exec_verify.py",
                    v.V1_SOURCE_BLOBS["cmp20_public_parallel_exec_verify.py"])
    result=m.inspect()
    require(result["status"]=="PASS" and
            result["old_public_stop_allowed"] is False and
            result["owner_os_reboot_allowed"] is False,
            "PRIOR_V1_AUTHORITY_NOT_PASS")

def public_b64(key:Ed25519PrivateKey)->str:
    k=key.public_key().public_bytes(serialization.Encoding.Raw,
                                     serialization.PublicFormat.Raw)
    return base64.b64encode(k).decode()

def enroll(v):
    require_owner()
    source_preflight(v)
    require(not TRUST.exists() and not TRUST.is_symlink(),"V2_TRUST_ALREADY_EXISTS")
    h=helper()
    require(v.BASE.joinpath("owner_approvals").is_dir(),"OWNER_APPROVALS_ROOT_HOLD")
    TRUST.mkdir(mode=0o700)
    h.protect_new(TRUST)
    kd=TRUST/"keys"
    kd.mkdir(mode=0o700)
    h.protect_new(kd)
    keys={name:Ed25519PrivateKey.generate() for name in ("issuer","reviewer")}
    require(public_b64(keys["issuer"])!=public_b64(keys["reviewer"]),
            "GUARDIAN_ROLES_NOT_DISTINCT")
    for name,key in keys.items():
        raw=key.private_bytes(serialization.Encoding.PEM,
                              serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption())
        h.create_new(kd/(name+".pem"),raw)
    trust={"schema":v.TRUST_SCHEMA,"purpose":v.PURPOSE,
           "issuer_public_b64":public_b64(keys["issuer"]),
           "reviewer_public_b64":public_b64(keys["reviewer"])}
    h.create_new(TRUST/"trust.json",v.canonical(trust))
    return {"status":"V2_TASK_PURPOSE_KEYS_ENROLLED",
            "trust_sha256":sha(v.canonical(trust)),
            "private_keys_exported":False,
            "task_registered":False,"process_modified":False}

def issue(v,pin:str):
    require_owner()
    source_preflight(v)
    require(type(pin) is str and re.fullmatch("[0-9a-f]{64}",pin) is not None,
            "INDEPENDENT_V2_TRUST_PIN_REQUIRED")
    require(not (TRUST/"manifest.json").exists() and
            not (TRUST/"packet.json").exists(),"V2_SIGN_ALREADY_ISSUED")
    raw=safe_file(TRUST/"trust.json",8192)
    require(sha(raw)==pin,"OWNER_TRUST_SHA_CHANGED")
    trust=v.strict_json(raw)
    manifest=v.manifest_fields(blob(safe_file(Path(__file__).resolve())),
                               blob(safe_file(Path(__file__).resolve().parent/
                                              "cmp20_public_guarded_task_verify_v2.py")))
    statement=v.statement_for(manifest)
    wire=v.canonical(statement)
    signatures={}
    for name in ("issuer","reviewer"):
        key_path=TRUST/"keys"/(name+".pem")
        key=serialization.load_pem_private_key(safe_file(key_path,8192),
                                                password=None)
        require(isinstance(key,Ed25519PrivateKey)
                and public_b64(key)==trust[name+"_public_b64"],
                "OWNER_TASK_KEY_ROLE_MISMATCH")
        signatures[name+"_signature_b64"]=base64.b64encode(key.sign(wire)).decode()
    packet={"schema":v.PACKET_SCHEMA,"statement":statement,**signatures}
    require(v.verify_packet(trust,manifest,packet)["status"]=="PASS",
            "ED25519_INDEPENDENT_PACKET_REJECTED")
    h=helper()
    h.create_new(TRUST/"manifest.json",v.canonical(manifest))
    h.create_new(TRUST/"packet.json",v.canonical(packet))
    require(v.verify_packet(
        v.strict_json(safe_file(TRUST/"trust.json")),
        v.strict_json(safe_file(TRUST/"manifest.json")),
        v.strict_json(safe_file(TRUST/"packet.json")))["status"]=="PASS",
        "ED25519_INDEPENDENT_PACKET_READBACK_HOLD")
    return {"status":"V2_SIGNED_TASK_PACKET_VERIFIED",
            "trust_sha256":pin,
            "manifest_sha256":sha(v.canonical(manifest)),
            "packet_sha256":sha(v.canonical(packet)),
            "authorized_actions":v.ALLOWED,
            "existing_task_change_authority":False,
            "old_public_stop_authority":False,
            "owner_os_reboot_authority":False,
            "private_keys_exported":False,
            "task_registered":False}

def stage(v):
    require_owner()
    source_preflight(v)
    trust=v.strict_json(safe_file(TRUST/"trust.json",8192))
    manifest=v.strict_json(safe_file(TRUST/"manifest.json",16384))
    packet=v.strict_json(safe_file(TRUST/"packet.json",16384))
    require(v.verify_packet(trust,manifest,packet)["status"]=="PASS",
            "V2_OWNER_SIGNED_PACKET_HOLD")
    scripts=Path(__file__).resolve().parent
    sources={
        "cmp20_public_guarded_owner_v2.py":
            safe_file(scripts/"cmp20_public_guarded_owner_v2.py"),
        "cmp20_public_guarded_task_verify_v2.py":
            safe_file(scripts/"cmp20_public_guarded_task_verify_v2.py"),
    }
    require(blob(sources["cmp20_public_guarded_owner_v2.py"])==
            manifest["guard_source_git_blob"] and
            blob(sources["cmp20_public_guarded_task_verify_v2.py"])==
            manifest["verifier_source_git_blob"],
            "V2_REVIEWED_SOURCE_CHANGED")
    for n,d in v.V1_SOURCE_BLOBS.items():
        sources[n]=safe_file(scripts/n)
        require(blob(sources[n])==d,"V1_REVIEWED_SOURCE_CHANGED")
    if RELEASE.exists():
        result=v.inspect()
        require(result["status"]=="PASS","EXISTING_V2_STAGE_DRIFT")
        return {"status":"V2_SIGNED_STAGE_EXISTING_PASS"}
    h=helper()
    RELEASE.mkdir(mode=0o700)
    h.protect_new(RELEASE)
    for name,raw in sources.items():
        h.create_new(RELEASE/name,raw)
    h.create_new(RELEASE/"guard.lock",b"0")
    result=v.inspect()
    require(result["status"]=="PASS","STAGED_V2_OWNER_INDEPENDENT_VERIFIER_HOLD")
    return {"status":"V2_SIGNED_GUARDIAN_STAGE_PASS",
            "guard_git_blob":manifest["guard_source_git_blob"],
            "verifier_git_blob":manifest["verifier_source_git_blob"],
            "signed_owner_packet_sha256":sha(safe_file(TRUST/"packet.json"))}

def shell(cmd:str,timeout:int=16)->str:
    # Small bounded PowerShell commands only; never use this with a detached
    # process, which could inherit the captured pipe and hang the parent.
    p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive",
                      "-Command",cmd],stdin=subprocess.DEVNULL,
                     stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                     timeout=timeout,shell=False,check=False)
    require(p.returncode==0 and 0<len(p.stdout)<=32768,
            "FIXED_POWERSHELL_OWNER_READBACK_HOLD")
    return p.stdout.decode("utf-8-sig").strip()

def task_xml(v)->str:
    # Task Scheduler 1.3 XML: 1 logon trigger plus 5m daily repetition,
    # IgnoreNew, no task-level hard process termination, owner-only.
    t="http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("",t)
    def child(parent,tag,value=None):
        e=ET.SubElement(parent,"{"+t+"}"+tag)
        if value is not None:
            e.text=value
        return e
    root=ET.Element("{"+t+"}Task",{"version":"1.3"})
    regs=child(root,"RegistrationInfo")
    child(regs,"Description","CMP20 owner-signed public-only 8879 guarded recovery V2")
    triggers=child(root,"Triggers")
    daily=child(triggers,"CalendarTrigger")
    rep=child(daily,"Repetition")
    child(rep,"Interval","PT5M")
    child(rep,"Duration","P1D")
    child(rep,"StopAtDurationEnd","false")
    child(daily,"StartBoundary","2026-11-11T00:00:00")
    child(daily,"Enabled","true")
    byday=child(daily,"ScheduleByDay")
    child(byday,"DaysInterval","1")
    logon=child(triggers,"LogonTrigger")
    child(logon,"Enabled","true")
    child(logon,"UserId",v.OWNER_SID)
    principals=child(root,"Principals")
    principal=child(principals,"Principal",None)
    principal.set("id","Author")
    child(principal,"UserId",v.OWNER_SID)
    child(principal,"LogonType","InteractiveToken")
    child(principal,"RunLevel","LeastPrivilege")
    settings=child(root,"Settings")
    for name,val in [
        ("MultipleInstancesPolicy","IgnoreNew"),
        ("DisallowStartIfOnBatteries","false"),
        ("StopIfGoingOnBatteries","false"),
        ("AllowHardTerminate","false"),
        ("StartWhenAvailable","true"),
        ("RunOnlyIfNetworkAvailable","false"),
        ("Enabled","true"),
        ("Hidden","false"),
        ("ExecutionTimeLimit","PT2M"),
        ("Priority","7")]:
        child(settings,name,val)
    actions=child(root,"Actions")
    actions.set("Context","Author")
    exe=child(actions,"Exec")
    child(exe,"Command",v.OWNER_PYTHON)
    child(exe,"Arguments",v.manifest_fields("0"*40,"0"*40)["task_argument"])
    return ET.tostring(root,encoding="unicode",xml_declaration=False)

def task_status(v)->dict|None:
    cmd=(
      "$ErrorActionPreference='Stop';"
      "$t=Get-ScheduledTask -TaskName '"+TASK+"' -ErrorAction SilentlyContinue;"
      "if($null -eq $t){Write-Output 'null';exit 0};"
      "$i=Get-ScheduledTaskInfo -TaskName '"+TASK+"' -ErrorAction Stop;"
      "$tr=@($t.Triggers|ForEach-Object{[pscustomobject]@{"
      "type=$_.CimClass.CimClassName;"
      "enabled=[bool]$_.Enabled;"
      "interval=[string]$_.Repetition.Interval;"
      "duration=[string]$_.Repetition.Duration;"
      "start=[string]$_.StartBoundary}});"
      "[pscustomobject]@{"
      "state=[string]$t.State;"
      "principal=[string]$t.Principal.UserId;"
      "logon=[string]$t.Principal.LogonType;"
      "runlevel=[string]$t.Principal.RunLevel;"
      "action_count=@($t.Actions).Count;"
      "exe=[string]$t.Actions[0].Execute;"
      "args=[string]$t.Actions[0].Arguments;"
      "multi=[string]$t.Settings.MultipleInstances;"
      "hard=[bool]$t.Settings.AllowHardTerminate;"
      "triggers=$tr;"
      "lastresult=[int]$i.LastTaskResult;"
      "last=$i.LastRunTime.ToString('o');"
      "next=$i.NextRunTime.ToString('o');"
      "missed=[int]$i.NumberOfMissedRuns"
      "}|ConvertTo-Json -Compress -Depth 6"
    )
    return json.loads(shell(cmd,timeout=20))

def check_task(v,info:dict,require_enabled:bool=True):
    require(type(info) is dict and
            info.get("principal") in (os.environ.get("USERNAME"),v.OWNER_SID) and
            info.get("logon")=="Interactive" and
            info.get("runlevel")=="Limited" and
            info.get("action_count")==1 and
            info.get("exe","").lower()==v.OWNER_PYTHON.lower() and
            info.get("args")==v.manifest_fields("0"*40,"0"*40)["task_argument"]
            and info.get("multi")=="IgnoreNew" and info.get("hard") is False,
            "V2_TASK_PRINCIPAL_ACTION_OR_POLICY_CHANGED")
    triggers=info.get("triggers")
    if type(triggers) is dict:triggers=[triggers]
    require(type(triggers) is list and len(triggers)==2 and
            all(type(x) is dict and x.get("enabled") is True for x in triggers),
            "V2_TASK_TRIGGERS_CHANGED")
    types={t["type"] for t in triggers}
    require(types=={"MSFT_TaskDailyTrigger","MSFT_TaskLogonTrigger"},
            "V2_TASK_TRIGGER_TYPES_CHANGED")
    day=next(t for t in triggers if t["type"]=="MSFT_TaskDailyTrigger")
    require(day.get("interval")=="PT5M" and day.get("duration")=="P1D",
            "V2_TASK_REPETITION_CHANGED")
    if require_enabled:
        require(info.get("state") in ("Ready","Running"),"V2_GUARD_TASK_NOT_READY")
    return info

def register(v):
    v.inspect()
    known=task_status(v)
    if known is not None:
        check_task(v,known)
        return {"status":"SIGNED_V2_TASK_ALREADY_INSTALLED_PASS",
                "task_state":known["state"],"task_created":False}
    xml=task_xml(v)
    root=ET.fromstring(xml)
    require(root.tag.endswith("Task"),"INVALID_FIXED_TASK_XML")
    env=dict(os.environ)
    env["CMP20_FIXED_TASK_XML"]=xml
    script=(
      "$ErrorActionPreference='Stop';"
      "if(Get-ScheduledTask -TaskName '"+TASK+"' -ErrorAction SilentlyContinue)"
      "{throw 'V2_TASK_ALREADY_REGISTERED'};"
      "Register-ScheduledTask -TaskName '"+TASK+
      "' -Xml $env:CMP20_FIXED_TASK_XML -ErrorAction Stop|Out-Null;"
      "Write-Output 'V2_OWNER_TASK_CREATED'"
    )
    p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive",
                      "-Command",script],env=env,stdin=subprocess.DEVNULL,
                     capture_output=True,timeout=30,shell=False,check=False)
    require(p.returncode==0 and b"V2_OWNER_TASK_CREATED" in p.stdout,
            "V2_TASK_REGISTER_COMMAND_HOLD")
    info=task_status(v)
    check_task(v,info)
    return {"status":"SIGNED_V2_TASK_REGISTERED_READBACK_PASS",
            "task_name":TASK,"task_state":info["state"],
            "task_created":True}

def current_route()->dict:
    p=subprocess.run(["tailscale.exe","serve","status","--json"],
                     stdin=subprocess.DEVNULL,capture_output=True,
                     timeout=12,check=False,shell=False)
    require(p.returncode==0 and 0<len(p.stdout)<=150000,
            "ORIGINAL_FUNNEL_STATUS_UNREADABLE")
    obj=json.loads(p.stdout)
    require(type(obj) is dict and type(obj.get("Web")) is dict
            and type(obj.get("AllowFunnel")) is dict
            and obj["AllowFunnel"].get(HOST) is True
            and type(obj["Web"].get(HOST)) is dict,
            "PUBLIC_FUNNEL_UNAVAILABLE")
    target=obj["Web"][HOST].get("Handlers",{}).get("/",{}).get("Proxy")
    require(target in (OLD,NEW),"PUBLIC_FUNNEL_TARGET_OUTSIDE_FIXED_SCOPE")
    return obj

def proxy(obj:dict)->str:
    return obj["Web"][HOST]["Handlers"]["/"]["Proxy"]

def health(port:int,public:bool=True)->dict:
    from urllib.request import urlopen
    from urllib.error import URLError,HTTPError
    require(port in (8877,8878,8879),"UNAPPROVED_HEALTH_PORT")
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/v1/health",timeout=7) as r:
            require(r.status==200,"LOCAL_HEALTH_HTTP_NOT200")
            raw=r.read(4097)
            require(len(raw)<=4096,"LOCAL_HEALTH_RESPONSE_TOO_BIG")
            item=json.loads(raw)
    except (URLError,HTTPError,ValueError,OSError):
        raise GuardianHold("LOCAL_SERVICE_UNHEALTHY_"+str(port)) from None
    require(type(item) is dict and item.get("status")=="ok",
            "LOCAL_SERVICE_STATUS_BAD")
    if public:
        require(item.get("mode")=="public-demo" and
                item.get("app_version")=="phase8-public-demo",
                "PUBLIC_SERVER_IDENTITY_BAD")
    return item

def port_owner(port:int)->dict|None:
    require(port in (8878,8879),"GUARD_ONLY_PUBLIC_LISTENERS")
    cmd=(
      "$ErrorActionPreference='Stop';"
      "$a=@(Get-NetTCPConnection -LocalPort "+str(port)+
      " -State Listen -ErrorAction SilentlyContinue);"
      "if($a.Count -eq 0){Write-Output 'null';exit 0};"
      "if($a.Count -ne 1){throw 'MULTIPLE_PUBLIC_OWNERS'};"
      "$p=Get-CimInstance Win32_Process -Filter "
      "('ProcessId='+$a[0].OwningProcess) -ErrorAction Stop;"
      "[pscustomobject]@{address=[string]$a[0].LocalAddress;"
      "pid=[int]$a[0].OwningProcess;name=[string]$p.Name;"
      "cmd=[string]$p.CommandLine}|ConvertTo-Json -Compress"
    )
    item=json.loads(shell(cmd,timeout=15))
    if item is None:return None
    require(type(item) is dict and set(item)==
            {"address","pid","name","cmd"} and
            item["address"]=="127.0.0.1" and
            item["name"].lower()=="pythonw.exe" and
            type(item["pid"]) is int and item["pid"]>0 and
            type(item["cmd"]) is str,
            "PUBLIC_LISTENER_OWNER_INVALID")
    expected=(V1/"cmp20_public_parallel_overlay.py" if port==8879
              else v_old_source()).__str__().replace("/","\\").lower()
    require(item["cmd"].replace("/","\\").lower().count(expected)==1,
            "PUBLIC_LISTENER_UNTRUSTED_COMMAND")
    if port==8879:
        file=V1/"public-demo.pid"
        require(safe_file(file,24).decode("ascii").strip()==str(item["pid"]),
                "SIGNED_CANDIDATE_PID_RECEIPT_MISMATCH")
    return {"pid":item["pid"],"port":port}

def v_old_source()->Path:
    return Path.home()/"Documents"/"LegalKB"/"public-demo-runtime"/"app-candidate"/"implementation"/"phase7"/"003_web_server.py"

def require_old_and_private()->int:
    o=port_owner(8878)
    require(o is not None,"ORIGINAL_8878_WORKER_MISSING")
    health(8878)
    health(8877,public=False)
    return o["pid"]

def candidate_ok()->tuple[bool,int|None]:
    o=port_owner(8879)
    if o is None:
        return False,None
    try:
        health(8879)
    except GuardianHold:
        return False,o["pid"]
    return True,o["pid"]

def https_public_pass():
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError,URLError
    root="https://ywshtmr.tail8fd68c.ts.net:8443"
    try:
        with urlopen(Request(root+"/",method="GET"),timeout=8) as r:
            require(r.status==200 and
                    bool(r.headers.get("Content-Security-Policy")) and
                    r.headers.get("X-Content-Type-Options","").lower()=="nosniff"
                    and r.headers.get("X-Frame-Options","").upper()=="DENY",
                    "PUBLIC_HTTPS_HEADERS_DRIFT")
            r.read(128)
        with urlopen(Request(root+"/api/v1/health",method="GET"),timeout=8) as r:
            item=json.loads(r.read(4097))
            require(r.status==200 and item.get("status")=="ok"
                    and item.get("mode")=="public-demo",
                    "PUBLIC_HTTPS_HEALTH_HOLD")
        try:
            with urlopen(Request(root+"/api/v1/favorites",method="GET"),
                         timeout=8) as r:
                require(r.status==404,"PUBLIC_PRIVATE_ROUTE_EXPOSED")
        except HTTPError as e:
            require(e.code==404,"PUBLIC_PRIVATE_ROUTE_BAD_STATUS")
    except (URLError,OSError,ValueError):
        raise GuardianHold("PUBLIC_HTTPS_READ_HOLD") from None

def switch_route(expected:str,target:str)->dict:
    require((expected,target) in ((OLD,NEW),(NEW,OLD)),
            "ROUTE_SWITCH_SCOPE_DENIED")
    before=current_route()
    require(proxy(before)==expected,"ROUTE_PREIMAGE_CHANGED")
    require_old_and_private()
    if target==NEW:
        good,_=candidate_ok()
        require(good,"CANDIDATE_NOT_HEALTHY_FOR_PUBLIC")
    p=subprocess.run(["tailscale.exe","funnel","--bg","--yes",
                      "--https=8443",target],
                     stdin=subprocess.DEVNULL,capture_output=True,
                     check=False,timeout=24,shell=False)
    require(p.returncode==0,"PUBLIC_FUNNEL_SWITCH_FAILED")
    after=current_route()
    expected_status=json.loads(json.dumps(before))
    expected_status["Web"][HOST]["Handlers"]["/"]["Proxy"]=target
    require(after==expected_status,"UNRELATED_FUNNEL_STATUS_CHANGED")
    try:
        https_public_pass()
        require_old_and_private()
        if target==NEW:
            good,_=candidate_ok()
            require(good,"CANDIDATE_DIED_ON_PUBLIC_SWITCH")
    except Exception:
        # Preserve known-good original first, and do not claim successful move.
        try:
            p=subprocess.run(["tailscale.exe","funnel","--bg","--yes",
                              "--https=8443",expected],
                             stdin=subprocess.DEVNULL,capture_output=True,
                             check=False,timeout=24,shell=False)
            require(p.returncode==0 and current_route()==before,
                    "CRITICAL_ROUTE_RESTORE_READBACK_HOLD")
        except Exception:
            raise GuardianHold("CRITICAL_PUBLIC_FUNNEL_ROLLBACK_FAILED") from None
        raise GuardianHold("PUBLIC_SWITCH_FAILED_AND_RESTORED") from None
    return {"status":"SIGNED_V2_ROUTE_SWITCH_PASS",
            "previous":expected,"current":target}

def launch_without_capture()->dict:
    """Avoid V1 hung controller: DETACHED child never inherits PIPE descriptors."""
    require(sha(safe_file(V1/"launch-public-parallel.ps1",30000))==
            verifier().V1_LAUNCHER_SHA,"V1_PUBLIC_START_SCRIPT_CHANGED")
    p=subprocess.run(
        ["powershell.exe","-NoProfile","-NonInteractive",
         "-ExecutionPolicy","Bypass","-File",
         str(V1/"launch-public-parallel.ps1")],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,timeout=65,check=False,shell=False)
    require(p.returncode==0,"V2_PARALLEL_LAUNCHER_DID_NOT_EXIT_ZERO")
    good,pid=candidate_ok()
    require(good and pid is not None,"V2_PARALLEL_CANDIDATE_NOT_VERIFIED")
    return {"status":"V2_PARALLEL_CHILD_AND_CONTROLLER_PASS",
            "candidate_pid":pid,
            "launcher_returncode":0,
            "inherited_pipe_capture":False}

def stop_candidate_only()->int:
    candidate=port_owner(8879)
    require(candidate is not None,"NO_VERIFIED_8879_TO_STOP")
    pid=candidate["pid"]
    require_old_and_private()
    # Exact signed candidate identity and public-demo.pid already checked.
    command="$ErrorActionPreference='Stop';$p=Get-CimInstance Win32_Process -Filter 'ProcessId="+str(pid)+"';if($null -eq $p){throw 'CANDIDATE_ALREADY_EXITED'};if($p.Name -ne 'pythonw.exe' -or $p.CommandLine -notlike '*cmp20_public_parallel_overlay.py*'){throw 'CANDIDATE_IDENTITY_CHANGED'};Stop-Process -Id "+str(pid)+" -Force -ErrorAction Stop;Write-Output 'CANDIDATE_ONLY_STOPPED'"
    require("CANDIDATE_ONLY_STOPPED" in shell(command,timeout=15),
            "SIGNED_CANDIDATE_ONLY_STOP_HOLD")
    return pid

def receipt(value:dict):
    wire=json.dumps(value,sort_keys=True,separators=(",",":")).encode()
    path=RELEASE/"last-guarded-once.json"
    require(len(wire)<8192 and not path.is_symlink(),
            "GUARDIAN_RECEIPT_UNSAFE")
    tmp=RELEASE/"last-guarded-once.json.new"
    require(not tmp.exists() and not tmp.is_symlink(),"PREVIOUS_RECEIPT_WRITE_INCOMPLETE")
    with tmp.open("xb") as f:
        f.write(wire);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

@contextlib.contextmanager
def exclusive():
    import msvcrt
    path=RELEASE/"guard.lock"
    require(safe_file(path,8)==b"0","GUARDIAN_LOCK_SOURCE_CHANGED")
    with path.open("r+b") as f:
        try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            raise GuardianHold("GUARDIAN_ALREADY_EXECUTING") from None
        try:yield
        finally:msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)

def guarded_once(v)->dict:
    v.inspect()
    check_task(v,task_status(v))
    with exclusive():
        oldpid=require_old_and_private()
        before=current_route()
        prior_target=proxy(before)
        good,pid=candidate_ok()
        recovered=False
        failback=False
        if not good:
            if prior_target==NEW:
                switch_route(NEW,OLD)
                failback=True
            if pid is not None:
                stop_candidate_only()
                # Socket release may lag a bounded few seconds.
                for _ in range(12):
                    if port_owner(8879) is None:break
                    time.sleep(0.5)
                require(port_owner(8879) is None,"CANDIDATE_PORT_STILL_BUSY")
            launched=launch_without_capture()
            pid=launched["candidate_pid"]
            recovered=True
            if prior_target==NEW:
                switch_route(OLD,NEW)
        require(port_owner(8878)["pid"]==oldpid,
                "ORIGINAL_PUBLIC_PID_CHANGED")
        good,actual=candidate_ok()
        require(good and actual==pid,"NEW_PUBLIC_UNHEALTHY_AFTER_TICK")
        require_old_and_private()
        target=proxy(current_route())
        require(target==prior_target,"UNEXPECTED_PUBLIC_ROUTE_AFTER_RECOVERY")
        https_public_pass()
        result={
            "schema":"legal-kb.cmp20.guarded-once-owner-receipt.v1",
            "status":"PASS",
            "owner_host":OWNER_HOST,
            "checked_utc":datetime.now(timezone.utc).isoformat(),
            "source_signed":True,
            "task_source_grant":"V2_ED25519_TWO_ROLES",
            "old_public_pid":oldpid,
            "candidate_pid":actual,
            "candidate_recovered":recovered,
            "public_fallback_used":failback,
            "public_route":target,
            "private_8877":"healthy",
            "old_public_8878":"healthy",
            "new_public_8879":"healthy",
            "no_old_pid_kill":True,
            "no_os_reboot":True,
        }
        receipt(result)
        return result

def activate(v):
    v.inspect()
    check_task(v,task_status(v))
    with exclusive():
        require(proxy(current_route())==OLD,"PERMANENT_ACTIVATION_NEEDS_OLD_ROUTE")
        original=require_old_and_private()
        good,pid=candidate_ok()
        require(good and pid is not None,"CANDIDATE_NOT_HEALTHY_FOR_ACTIVATE")
        switched=switch_route(OLD,NEW)
        require(port_owner(8878)["pid"]==original,"OLD_OWNER_DRIFTED")
        return {"status":"SIGNED_V2_PERMANENT_PUBLIC_ROUTE_ACTIVATED",
                **switched,"v2_guard_task_registered":True,
                "candidate_pid":pid,"postboot_unverified":True}

def restore(v):
    v.inspect()
    with exclusive():
        current=proxy(current_route())
        if current==OLD:return {"status":"SIGNED_V2_ALREADY_ORIGINAL_ROUTE"}
        return switch_route(NEW,OLD)

def drill_stop(v):
    v.inspect()
    check_task(v,task_status(v))
    with exclusive():
        require(proxy(current_route())==OLD,"CANDIDATE_DRILL_REQUIRES_OLD_PUBLIC_ROUTE")
        pid=stop_candidate_only()
        return {"status":"SIGNED_V2_CANDIDATE_ONLY_FAULT_INJECTED",
                "stopped_candidate_pid":pid,
                "original_route_unchanged":True,
                "new_task_must_prove_recovery":True}

def disable(v):
    v.inspect()
    with exclusive():
        require(proxy(current_route())==OLD,"TASK_DISABLE_REQUIRES_ORIGINAL_FUNNEL")
        info=task_status(v)
        check_task(v,info)
        shell("$ErrorActionPreference='Stop';Disable-ScheduledTask -TaskName '"+
              TASK+"' -ErrorAction Stop|Out-Null;Write-Output 'FIXED_V2_DISABLED'")
        new=task_status(v)
        check_task(v,new,False)
        require(new["state"]=="Disabled","V2_DISABLE_READBACK_FAILED")
        return {"status":"SIGNED_V2_EXACT_TASK_DISABLED","task_name":TASK,
                "original_public_8878_preserved":True}

def inspect_only(v):
    verdict=v.inspect()
    t=task_status(v)
    if t is not None:check_task(v,t,False)
    route=current_route()
    good,pid=candidate_ok()
    return {"status":"PASS","signed_v2":verdict["status"],
            "task_registered":t is not None,
            "task_state":t["state"] if t else "ABSENT",
            "task_last_result":t["lastresult"] if t else None,
            "task_last_run":t["last"] if t else None,
            "public_route":proxy(route),
            "candidate_8879_healthy":good,
            "candidate_pid":pid,
            "signed_v1_unchanged":True,
            "no_execution_from_inspection":True}

def main()->int:
    actions={"--enroll","--issue","--stage","--register","--once",
             "--activate","--restore","--drill-stop","--disable","--inspect"}
    if len(sys.argv)<2 or sys.argv[1] not in actions:
        print(json.dumps({"status":"HOLD","reason":"FIXED_V2_ACTION_REQUIRED"}))
        return 2
    action=sys.argv[1]
    try:
        require_owner()
        v=verifier()
        if action in CONSENT:
            require(len(sys.argv)==4 and sys.argv[2]=="--owner-consent"
                    and sys.argv[3]==CONSENT[action],
                    "EXPLICIT_OWNER_V2_SIGNING_CONSENT_REQUIRED") if action=="--enroll" else None
            if action=="--enroll":
                out=enroll(v)
            else:
                require(len(sys.argv)==6 and sys.argv[2]=="--owner-consent"
                        and sys.argv[3]==CONSENT[action]
                        and sys.argv[4]=="--independent-trust-pin",
                        "EXPLICIT_V2_SIGNING_PIN_CONSENT_REQUIRED")
                out=issue(v,sys.argv[5])
        else:
            require(len(sys.argv)==2,"NO_EXTRA_V2_ACTION_ARGUMENTS")
            if action=="--stage":out=stage(v)
            elif action=="--register":out=register(v)
            elif action=="--once":out=guarded_once(v)
            elif action=="--activate":out=activate(v)
            elif action=="--restore":out=restore(v)
            elif action=="--drill-stop":out=drill_stop(v)
            elif action=="--disable":out=disable(v)
            else:out=inspect_only(v)
        print(json.dumps(out,sort_keys=True))
        return 0
    except (GuardianHold,OSError,RuntimeError,ValueError,KeyError,TypeError,
            subprocess.TimeoutExpired) as e:
        reason=str(e) if isinstance(e,GuardianHold) else "CMP20_V2_FIXED_ACTION_HOLD"
        print(json.dumps({"status":"HOLD","reason":reason,
                          "scope_auto_escalated":False},sort_keys=True))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
