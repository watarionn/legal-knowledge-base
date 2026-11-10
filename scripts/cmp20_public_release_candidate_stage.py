"""CMP-20 guarded, UNSIGNED public-demo patch candidate stage.

The only allowed mutation is a new exact-bound staging subdirectory beneath
the isolated owner QA workspace. This is NOT a production deployment, Task
enrollment, credential operation, signed executable release or user-session
reboot. Existing public/private runtime trees remain untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SCHEMA="legal-kb.cmp20.public-demo-unsigned-source-candidate.v1"
OWNER_HEAD="4acdda5aac833a30189858ff1e43c34ada23c839"
SOURCE_MAIN_COMMIT="14d5d6dae5ca1b238a78860b0e473ebbd795415d"
LAUNCHER_SHA="fa806751be935fd93c4650a56171c9615c2ce3550acb222e233b038e0e32a77f"
OLD_BLOB="a394f509b51fe598eb0f1852339ba7f21e2be9b4"
NEW_FILES={
    "003_web_server.py":"511f5070c8c3fac8e733b35cb897868dca77369c",
    "082_public_demo_socket_retry_test.py":"ab157e90a4725d1b8923bc0a68cacdd95b82d5c5",
}
QA=Path(os.environ.get("LOCALAPPDATA",""))/"RinkaMissionControl"/"cmp20-server-retry-qa-20261110"
OWNER=Path.home()/"Documents"/"LegalKB"/"public-demo-runtime"
APP=OWNER/"app-candidate"
SOURCE=QA/"phase7"
DEST=QA/"cmp20-public-demo-unsigned-source-candidate-v1"
TMP=QA/"cmp20-public-demo-stage-temporary-v1"

class CandidateHold(ValueError):
    pass

def require(ok,reason):
    if not ok:raise CandidateHold(reason)

def gitblob(raw):
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\x00"+raw).hexdigest()

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def safe_dir(path:Path):
    require(path.is_dir() and not path.is_symlink()
            and (not hasattr(path,"is_junction") or not path.is_junction()),
            "REPARSE_OR_MISSING_DIRECTORY_HOLD")

def safe_file(path:Path, max_bytes=150000):
    require(path.is_file() and not path.is_symlink()
            and (not hasattr(path,"is_junction") or not path.is_junction())
            and 0<path.stat().st_size<=max_bytes,
            "REPARSE_OR_MISSING_SOURCE_HOLD")
    return path.read_bytes()

def owner_snapshot():
    require(os.name=="nt","OWNER_WINDOWS_ONLY")
    for p in (QA,SOURCE,OWNER,APP):
        safe_dir(p)
    launcher=safe_file(OWNER/"start-public-demo.ps1")
    require(sha(launcher)==LAUNCHER_SHA,"OWNER_LAUNCHER_SHA_HOLD")
    def git(*a):
        p=subprocess.run(["git","-C",str(APP),*a],capture_output=True,
                         stdin=subprocess.DEVNULL,timeout=10,check=False)
        require(p.returncode==0 and len(p.stdout)<=4096,
                "OWNER_GIT_READONLY_HOLD")
        return p.stdout.decode("utf-8-sig").strip()
    require(git("rev-parse","HEAD")==OWNER_HEAD,
            "OWNER_DEPLOYED_HEAD_DRIFT")
    require(git("status","--porcelain=v1","--untracked-files=no")=="",
            "OWNER_DIRTY_WORKTREE_HOLD")
    old=safe_file(APP/"implementation"/"phase7"/"003_web_server.py")
    require(gitblob(old)==OLD_BLOB,"OWNER_DEPLOYED_SERVER_BLOB_DRIFT")
    expected=set(NEW_FILES)
    patch={name:safe_file(SOURCE/name) for name in NEW_FILES}
    require(set(patch)==expected,"INVALID_PATCH_FILE_COUNT")
    for n,digest in NEW_FILES.items():
        require(gitblob(patch[n])==digest,"NEW_PATCH_SOURCE_BLOB_HOLD")
    return patch

def manifest_for(patch:dict[str,bytes])->dict:
    require(set(patch)==set(NEW_FILES),"INVALID_PATCH_FILE_SET")
    for name,digest in NEW_FILES.items():
        require(gitblob(patch[name])==digest,"NEW_PATCH_SOURCE_BLOB_HOLD")
    return {
        "schema":SCHEMA,
        "operation":"IMMUTABLE_UNSIGNED_NONEXECUTABLE_PATCH_STAGE_ONLY",
        "owner_head_preimage":OWNER_HEAD,
        "owner_server_original_git_blob":OLD_BLOB,
        "source_main_reviewed_commit":SOURCE_MAIN_COMMIT,
        "owner_task_action_sha256_preimage":LAUNCHER_SHA,
        "patch_files_git_blob":dict(sorted(NEW_FILES.items())),
        "patch_files_sha256":{n:sha(patch[n]) for n in sorted(NEW_FILES)},
        "source_only_qa":{"run_at":"owner Windows 2026-11-10",
                          "test_files":27,"tests_passed":207,"tests_failed":0,
                          "live_server_replaced":False},
        "privileges":{"owner_signature_present":False,
                      "task_registration_authorized":False,
                      "task_enable_authorized":False,
                      "process_stop_authorized":False,
                      "production_release_authorized":False,
                      "funnel_change_authorized":False,
                      "db_or_secret_access_authorized":False,
                      "shared_reboot_authorized_now":False},
    }

def stage_create_only(patch, temporary:Path,destination:Path):
    safe_dir(temporary.parent)
    require(not temporary.exists() and not destination.exists(),
            "OWNER_PATCH_STAGE_ALREADY_EXISTS")
    manifest=manifest_for(patch)
    raw=json.dumps(manifest,sort_keys=True,ensure_ascii=False,
                   separators=(",",":")).encode("utf-8")
    temporary.mkdir(mode=0o700)
    for name in sorted(NEW_FILES):
        p=temporary/name
        with p.open("xb") as f:
            f.write(patch[name]);f.flush();os.fsync(f.fileno())
        require(p.read_bytes()==patch[name],"PATCH_FILE_READBACK_HOLD")
    with (temporary/"manifest.json").open("xb") as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    require((temporary/"manifest.json").read_bytes()==raw,
            "PATCH_MANIFEST_READBACK_HOLD")
    require(not destination.exists(),"DESTINATION_RACE_HOLD")
    temporary.rename(destination)
    require((destination/"manifest.json").read_bytes()==raw,
            "PATCH_FINAL_MANIFEST_READBACK_HOLD")
    return sha(raw)

def inspect():
    patch=owner_snapshot()
    result={"schema":SCHEMA,"status":"READY_UNSIGNED_SOURCE_ONLY",
            "stage_exists":DEST.exists(),"production_authorized":False,
            "patch_files":len(patch),"source_main_commit":SOURCE_MAIN_COMMIT,
            "owner_git_head":OWNER_HEAD,
            "owner_source_patch_blobs_match":True,
            "task_or_runtime_mutated":False}
    return result

def main():
    if sys.argv[1:] not in (["--inspect"],["--stage"]):
        print(json.dumps({"schema":SCHEMA,"status":"HOLD",
                          "reason":"FIXED_INSPECT_OR_UNSIGNED_STAGE_ONLY"},sort_keys=True))
        return 2
    try:
        patch=owner_snapshot()
        if sys.argv[1]=="--inspect":
            print(json.dumps({"schema":SCHEMA,"status":"READY_UNSIGNED_SOURCE_ONLY",
                              "stage_exists":DEST.exists(),
                              "execution_authority":False,
                              "task_or_runtime_mutated":False},sort_keys=True))
            return 0
        digest=stage_create_only(patch,TMP,DEST)
        print(json.dumps({"schema":SCHEMA,"status":"STAGED_UNSIGNED_NONEXECUTABLE",
                          "manifest_sha256":digest,"patch_file_count":len(patch),
                          "execution_authority":False,
                          "task_or_runtime_mutated":False},sort_keys=True))
        return 0
    except (CandidateHold,OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired) as e:
        reason=str(e) if isinstance(e,CandidateHold) else "OWNER_SOURCE_READBACK_FAILED"
        print(json.dumps({"schema":SCHEMA,"status":"HOLD","reason":reason,
                          "execution_authority":False,
                          "task_or_runtime_mutated":False},sort_keys=True))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
