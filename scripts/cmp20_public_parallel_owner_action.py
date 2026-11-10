"""CMP20 purpose-bounded, owner-signed public demo side-by-side cutover.

No original worktree writes, existing public process kills, private DB/DPAPI
reads from Python, Tailscale reset, or OS reboot. The original byte-pinned
PowerShell launcher remains the *only* source of owner-secured DPAPI environment.
The signed patched server runs only at 127.0.0.1:8879; public Funnel 8443 can be
atomically re-pointed with an exact revert to the healthy original :8878.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

SCHEMA="legal-kb.cmp20.public-parallel-cutover-owner.v1"
RELEASE_ID="cmp20-public-demo-parallel-exec-v1"
ROOT=Path(os.environ.get("LOCALAPPDATA",""))/"RinkaMissionControl"
RELEASE=ROOT/"releases"/RELEASE_ID
REVIEW_ROOT=ROOT/"owner_approvals"/"cmp20-public-demo-release-review"
APP=Path.home()/"Documents"/"LegalKB"/"public-demo-runtime"/"app-candidate"
ORIGINAL_LAUNCHER=APP.parent/"start-public-demo.ps1"
ORIGINAL_SERVER=APP/"implementation"/"phase7"/"003_web_server.py"
PATCH_STAGE=ROOT/"cmp20-server-retry-qa-20261110"/"cmp20-public-demo-unsigned-source-candidate-v1"
ORIGINAL_HEAD="4acdda5aac833a30189858ff1e43c34ada23c839"
ORIGINAL_LAUNCHER_SHA="fa806751be935fd93c4650a56171c9615c2ce3550acb222e233b038e0e32a77f"
OLD_SERVER_BLOB="a394f509b51fe598eb0f1852339ba7f21e2be9b4"
PATCH_BLOB="511f5070c8c3fac8e733b35cb897868dca77369c"
REVIEW_PACKET_SHA="6bee779804cb0e9ef516eb3d5898107fcc9fa0d17a38b3d6d38459ee12f19e88"
STAGE_SHA="9b8730abdfe399b9f8d9bf86e95fac0b9063236f214c306c439da4588b80374f"
OWNER_HOST="YWSHTMR"
HOST_PORT="ywshtmr.tail8fd68c.ts.net:8443"
OLD_TARGET="http://127.0.0.1:8878"
NEW_TARGET="http://127.0.0.1:8879"
PYTHON="C:\\Python314\\pythonw.exe"

# Filled from actual GitHub reviewed source blobs before executable enrollment.
OVERLAY_BLOB="4e07752f60d554987c9bd30dc513ae3af569ba57"
EXEC_VERIFIER_BLOB="253ef413c3b72f2de8b0d5df4ff68f478fca7bd8"
REVIEW_VERIFIER_BLOB="ae7f2cbd01dab3d6dd9823ce340be34ee95bbe3b"
REVIEW_SIGNER_BLOB="4199852e192349270096807af52d358ee89afe2b"


class CutoverHold(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise CutoverHold(reason)


def sha(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()


def gitblob(raw:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\x00"+raw).hexdigest()


def safe_dir(path:Path):
    require(path.is_dir() and not path.is_symlink() and
            not (hasattr(path,"is_junction") and path.is_junction()),
            "OWNER_DIRECTORY_MISSING_OR_REPARSE")


def safe_file(path:Path, max_size:int=200000)->bytes:
    require(path.is_file() and not path.is_symlink() and
            not (hasattr(path,"is_junction") and path.is_junction())
            and 0 < path.stat().st_size <= max_size,
            "OWNER_FILE_MISSING_OR_REPARSE")
    return path.read_bytes()


def pinned_module(path:Path,blob:str):
    require(gitblob(safe_file(path,100000))==blob,"CMP20_MODULE_SOURCE_CHANGED")
    spec=importlib.util.spec_from_file_location("cmp20_live_"+path.stem,path)
    require(spec is not None and spec.loader is not None,"CMP20_MODULE_IMPORT_HOLD")
    obj=importlib.util.module_from_spec(spec)
    prev=sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode=True
        spec.loader.exec_module(obj)
    finally:
        sys.dont_write_bytecode=prev
    return obj


def checked(argv:list[str],timeout:int=14)->bytes:
    p=subprocess.run(argv,stdin=subprocess.DEVNULL,capture_output=True,
                     timeout=timeout,check=False,shell=False)
    require(p.returncode==0 and len(p.stdout)<=120000,
            "CMP20_OWNER_COMMAND_HOLD")
    return p.stdout


def owner_source_check()->tuple[bytes,bytes]:
    require(os.name=="nt" and os.environ.get("COMPUTERNAME","").upper()==OWNER_HOST,
            "OWNER_WINDOWS_ONLY")
    for path in (ROOT, ROOT/"releases", APP, ORIGINAL_SERVER.parent, PATCH_STAGE):
        safe_dir(path)
    orig_launcher=safe_file(ORIGINAL_LAUNCHER,30000)
    require(sha(orig_launcher)==ORIGINAL_LAUNCHER_SHA,
            "ORIGINAL_PUBLIC_LAUNCHER_CHANGED")
    require(checked(["git","-C",str(APP),"rev-parse","HEAD"]).decode("utf-8-sig").strip()
            ==ORIGINAL_HEAD,"ORIGINAL_PUBLIC_HEAD_DRIFT")
    require(not checked(["git","-C",str(APP),"status","--porcelain=v1",
                         "--untracked-files=no"]).strip(),
            "ORIGINAL_PUBLIC_TRACKED_FILES_DIRTY")
    require(gitblob(safe_file(ORIGINAL_SERVER))==OLD_SERVER_BLOB,
            "ORIGINAL_PUBLIC_SERVER_DRIFT")
    require(sha(safe_file(PATCH_STAGE/"manifest.json",8192))==STAGE_SHA,
            "REVIEWED_SOURCE_STAGE_MANIFEST_CHANGED")
    patch=safe_file(PATCH_STAGE/"003_web_server.py")
    require(gitblob(patch)==PATCH_BLOB,"REVIEWED_PUBLIC_PATCH_BLOB_CHANGED")
    return orig_launcher,patch


def transformed_launcher(original:bytes)->bytes:
    """Exact seven substitutions; never decode/print owner DPAPI secret values."""
    content=original.decode("utf-8-sig").replace("\r\n","\n")
    replacement=[
        ("$logDir = Join-Path $runtime 'logs'",
         "$logDir = Join-Path $env:LOCALAPPDATA 'RinkaMissionControl\\releases\\"+RELEASE_ID+"\\logs'"),
        ("$env:LEGAL_KB_PORT = '8878'", "$env:LEGAL_KB_PORT = '8879'"),
        ("-LocalPort 8878","-LocalPort 8879"),
        ("*003_web_server.py*","*cmp20_public_parallel_overlay.py*"),
        ("-ArgumentList (Join-Path $app 'implementation\\phase7\\003_web_server.py')",
         "-ArgumentList (Join-Path $env:LOCALAPPDATA 'RinkaMissionControl\\releases\\"+RELEASE_ID+"\\cmp20_public_parallel_overlay.py')"),
        ("(Join-Path $runtime 'public-demo.pid')",
         "(Join-Path $env:LOCALAPPDATA 'RinkaMissionControl\\releases\\"+RELEASE_ID+"\\public-demo.pid')"),
        ("http://127.0.0.1:8878/api/v1/health",
         "http://127.0.0.1:8879/api/v1/health"),
    ]
    for old,new in replacement:
        require(content.count(old)==1,"UNEXPECTED_ORIGINAL_LAUNCHER_STRUCTURE")
        content=content.replace(old,new)
    anchor="$env:LEGAL_KB_PUBLIC_DEMO = '1'"
    require(content.count(anchor)==1,"UNEXPECTED_PUBLIC_ENV_ANCHOR")
    content=content.replace(anchor,anchor+"\n$env:PYTHONDONTWRITEBYTECODE = '1'")
    return content.encode("utf-8")


def output_manifest(launcher:bytes,overlay:bytes,patch:bytes)->dict:
    return {
      "schema":SCHEMA,"release_id":RELEASE_ID,
      "operation":"EXACT_OWNER_SIGNED_SIDE_BY_SIDE_PUBLIC_Funnel_8443",
      "owner_original_head":ORIGINAL_HEAD,
      "owner_original_launcher_sha256":ORIGINAL_LAUNCHER_SHA,
      "owner_original_server_git_blob":OLD_SERVER_BLOB,
      "review_only_packet_sha256":REVIEW_PACKET_SHA,
      "reviewed_unsigned_stage_sha256":STAGE_SHA,
      "reviewed_patch_git_blob":PATCH_BLOB,
      "overlay_source_git_blob":OVERLAY_BLOB,
      "launcher_sha256":sha(launcher),
      "overlay_sha256":sha(overlay),
      "patch_sha256":sha(patch),
      "previous_target":OLD_TARGET,"new_target":NEW_TARGET,
      "private_8877_unchanged":True,
      "original_public_8878_process_must_remain_running":True,
      "no_task_registration_or_reboot":True,
      "private_credentials_not_exported":True,
    }


def pinned_exec_gate():
    scripts=Path(__file__).resolve().parent
    obj=pinned_module(scripts/"cmp20_public_parallel_exec_verify.py",
                      EXEC_VERIFIER_BLOB)
    out=obj.inspect()
    require(out["status"]=="PASS" and
            out["authorized_actions"]==
            ["stage","start_parallel_8879","switch_public_8443","restore_public_8878"]
            and out["old_public_stop_allowed"] is False
            and out["owner_os_reboot_allowed"] is False,
            "EXECUTION_GRANT_NOT_PASS")
    return obj


def original_review_gate():
    scripts=Path(__file__).resolve().parent
    obj=pinned_module(scripts/"cmp20_public_release_review.py",REVIEW_VERIFIER_BLOB)
    result=obj.inspect()
    require(result["status"]=="PASS" and result["verified_scope"]==
            "REVIEW_ONLY_NOT_EXECUTION","REVIEW_PACKET_NOT_AUTHENTIC")
    require(sha(safe_file(REVIEW_ROOT/"packet.json",8192))==REVIEW_PACKET_SHA,
            "REVIEW_PACKET_CHANGED")


def protected_create(path:Path,raw:bytes,signer):
    with path.open("xb") as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    require(path.read_bytes()==raw,"SIGNED_RELEASE_FILE_WRITE_HOLD")
    signer.protect_new(path)


def verify_release()->dict:
    safe_dir(RELEASE)
    orig,patch=owner_source_check()
    overlay=safe_file(RELEASE/"cmp20_public_parallel_overlay.py")
    require(gitblob(overlay)==OVERLAY_BLOB,"PARALLEL_OVERLAY_CHANGED")
    launcher=transformed_launcher(orig)
    require(safe_file(RELEASE/"launch-public-parallel.ps1",30000)==launcher,
            "PARALLEL_LAUNCHER_CHANGED")
    require(safe_file(RELEASE/"003_web_server.py")==patch,
            "PARALLEL_RELEASE_PATCH_CHANGED")
    manifest=output_manifest(launcher,overlay,patch)
    raw=json.dumps(manifest,sort_keys=True,ensure_ascii=False,
                   separators=(",",":")).encode()
    require(safe_file(RELEASE/"manifest.json",16000)==raw,
            "PARALLEL_MANIFEST_CHANGED")
    return manifest


def stage_release():
    owner_source_check();original_review_gate();pinned_exec_gate()
    scripts=Path(__file__).resolve().parent
    signer=pinned_module(scripts/"cmp20_public_release_owner_signer.py",
                         REVIEW_SIGNER_BLOB)
    if RELEASE.exists():
        return {"status":"STAGED_EXISTING_VERIFIED","manifest":verify_release()}
    overlay=safe_file(scripts/"cmp20_public_parallel_overlay.py",100000)
    require(gitblob(overlay)==OVERLAY_BLOB,"OVERLAY_SOURCE_BLOB_DRIFT")
    original,patch=owner_source_check()
    launcher=transformed_launcher(original)
    manifest=output_manifest(launcher,overlay,patch)
    raw=json.dumps(manifest,ensure_ascii=False,sort_keys=True,
                   separators=(",",":")).encode()
    require(not RELEASE.exists(),"CMP20_RELEASE_NO_CLOBBER")
    RELEASE.mkdir(mode=0o700)
    signer.protect_new(RELEASE)
    for name,source in (
        ("003_web_server.py",patch),
        ("cmp20_public_parallel_overlay.py",overlay),
        ("launch-public-parallel.ps1",launcher),
        ("manifest.json",raw)):
        protected_create(RELEASE/name,source,signer)
    verify_release()
    return {"status":"SIGNED_PARALLEL_STAGE_VERIFIED",
            "manifest_sha256":sha(raw),"patch_git_blob":PATCH_BLOB}


def current_route()->dict:
    p=json.loads(checked(["tailscale.exe","serve","status","--json"],timeout=15))
    require(isinstance(p,dict) and type(p.get("Web")) is dict
            and type(p.get("AllowFunnel")) is dict
            and HOST_PORT in p["Web"]
            and p["AllowFunnel"].get(HOST_PORT) is True,
            "PUBLIC_FUNNEL_OWNER_STATUS_HOLD")
    root=p["Web"][HOST_PORT].get("Handlers",{}).get("/")
    require(type(root) is dict and isinstance(root.get("Proxy"),str),
            "PUBLIC_FUNNEL_HANDLER_HOLD")
    return p


def get_health(url:str)->dict:
    try:
        with urlopen(url,timeout=8) as result:
            require(result.status==200,"PUBLIC_HEALTH_NOT_200")
            raw=result.read(2049)
            require(len(raw)<=2048,"PUBLIC_HEALTH_OVERSIZED")
            return json.loads(raw)
    except (HTTPError,URLError,OSError,ValueError) as e:
        raise CutoverHold("PUBLIC_RUNTIME_HTTP_HOLD") from e


def service_health(port:int):
    health=get_health(f"http://127.0.0.1:{port}/api/v1/health")
    require(type(health) is dict and health.get("status")=="ok"
            and health.get("mode")=="public-demo"
            and health.get("app_version")=="phase8-public-demo",
            "PUBLIC_SERVICE_IDENTITY_CHANGED")


def inspect_public(source_port:int=8879):
    service_health(8878)
    private=get_health("http://127.0.0.1:8877/api/v1/health")
    require(private.get("status")=="ok","PRIVATE_SERVICE_UNHEALTHY")
    service_health(source_port)
    return {"status":"PASS","old_8878":"healthy",
            "new_8879":"healthy","private_8877":"healthy"}


def start_parallel():
    pinned_exec_gate();original_review_gate();verify_release()
    route=current_route()
    require(route["Web"][HOST_PORT]["Handlers"]["/"]["Proxy"]==OLD_TARGET,
            "START_REQUIRE_ORIGINAL_PUBLIC_FUNNEL")
    service_health(8878)
    private=get_health("http://127.0.0.1:8877/api/v1/health")
    require(private.get("status")=="ok","ORIGINAL_PRIVATE_UNHEALTHY")
    # The source-pinned original launcher reads DPAPI locally, starts only
    # the new :8879 process and saves PID without touching existing :8878.
    checked(["powershell.exe","-NoProfile","-NonInteractive",
             "-ExecutionPolicy","Bypass","-File",
             str(RELEASE/"launch-public-parallel.ps1")],timeout=90)
    inspect_public()
    require(current_route()["Web"][HOST_PORT]["Handlers"]["/"]["Proxy"]==
            OLD_TARGET,"PUBLIC_FUNNEL_CHANGED_DURING_STAGE")
    return {"status":"SIGNED_PARALLEL_STARTED_AND_VERIFIED",
            "old_public_8878":"healthy","new_public_8879":"healthy",
            "private_8877":"healthy","public_funnel_switched":False}


def change_route(expected:str,target:str):
    pinned_exec_gate();original_review_gate();verify_release()
    before=current_route()
    current=before["Web"][HOST_PORT]["Handlers"]["/"]["Proxy"]
    require(current==expected,"PUBLIC_FUNNEL_PREIMAGE_NOT_MATCHED")
    service_health(8878)
    private=get_health("http://127.0.0.1:8877/api/v1/health")
    require(private.get("status")=="ok","PRIVATE_SERVICE_UNHEALTHY")
    if target==NEW_TARGET:
        service_health(8879)
    changed=copy.deepcopy(before)
    changed["Web"][HOST_PORT]["Handlers"]["/"]["Proxy"]=target
    try:
        checked(["tailscale.exe","funnel","--bg","--yes",
                 "--https=8443",target],timeout=25)
        now=current_route()
        require(now==changed,"PUBLIC_FUNNEL_UNRELATED_OR_MISSING_ROUTE_CHANGE")
        exposed=get_health("https://ywshtmr.tail8fd68c.ts.net:8443/api/v1/health")
        require(exposed.get("status")=="ok" and
                exposed.get("mode")=="public-demo" and
                exposed.get("app_version")=="phase8-public-demo",
                "PUBLIC_NEW_FUNNEL_IDENTITY_HOLD")
        service_health(8878)
        private=get_health("http://127.0.0.1:8877/api/v1/health")
        require(private.get("status")=="ok","PRIVATE_SERVICE_UNHEALTHY")
        if target==NEW_TARGET:
            service_health(8879)
    except Exception:
        # Fail closed: restore the exact original preimage; never reset Serve.
        try:
            checked(["tailscale.exe","funnel","--bg","--yes",
                     "--https=8443",expected],timeout=25)
            require(current_route()==before,"FUNNEL_ROLLBACK_READBACK_HOLD")
        except Exception:
            raise CutoverHold("CRITICAL_FUNNEL_ROLLBACK_FAILED") from None
        raise CutoverHold("PUBLIC_FUNNEL_CUTOVER_RESTORED_ON_FAILURE") from None
    return {"status":"SIGNED_PUBLIC_FUNNEL_SWITCH_VERIFIED",
            "previous":expected,"current":target,
            "other_tailscale_routes_unchanged":True,
            "old_public_process_stopped":False,
            "os_reboot_performed":False}


def main():
    actions={"--stage","--start-parallel","--cutover","--rollback","--inspect"}
    if len(sys.argv)!=2 or sys.argv[1] not in actions:
        print(json.dumps({"schema":SCHEMA,"status":"HOLD",
                          "reason":"FIXED_ACTION_REQUIRED"}));return 2
    try:
        if sys.argv[1]=="--inspect":
            original_review_gate();pinned_exec_gate()
            out={"status":"PASS","release_stage_exists":RELEASE.exists(),
                 "stage_verified":bool(verify_release()) if RELEASE.exists() else False,
                 "current_public_target":current_route()["Web"][HOST_PORT]["Handlers"]["/"]["Proxy"]}
        elif sys.argv[1]=="--stage":
            out=stage_release()
        elif sys.argv[1]=="--start-parallel":
            out=start_parallel()
        elif sys.argv[1]=="--cutover":
            out=change_route(OLD_TARGET,NEW_TARGET)
        else:
            out=change_route(NEW_TARGET,OLD_TARGET)
        print(json.dumps({"schema":SCHEMA,**out},sort_keys=True));return 0
    except (CutoverHold,OSError,ValueError,TypeError,KeyError,
            subprocess.TimeoutExpired,RuntimeError) as e:
        reason=str(e) if isinstance(e,CutoverHold) else "CMP20_FIXED_OWNER_ACTION_HOLD"
        print(json.dumps({"schema":SCHEMA,"status":"HOLD","reason":reason,
                          "execution_authority_auto_escalated":False},sort_keys=True))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
