"""CMP-20 read-only, fail-closed public-demo runtime recovery diagnosis.

The live Phase8 public demo is launched by an existing Windows logon Task.
That launcher exits after starting a detached pythonw child, so a Task
LastTaskResult=0 does not imply that the server is still alive.

This script does NOT stop/start a process or Task, write logs or receipts,
read secrets, modify PostgreSQL, repair Tailscale/Funnel, or install a monitor.
It only classifies a currently healthy public endpoint or a candidate for a
future, independently authorized restart action.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

SCHEMA = "legal-kb.cmp20.owner-public-recovery-inspection.v1"
TASK_NAME = "LegalKB Public Demo Runtime"
PUBLIC_PORT = 8878
PRIVATE_PORT = 8877
PUBLIC_PROXY = "http://127.0.0.1:8878"
OWNER_RELEASE_HEAD = "4acdda5aac833a30189858ff1e43c34ada23c839"
LAUNCHER_SHA256 = "fa806751be935fd93c4650a56171c9615c2ce3550acb222e233b038e0e32a77f"
PUBLIC_HEALTH = "http://127.0.0.1:8878/api/v1/health"
PRIVATE_HEALTH = "http://127.0.0.1:8877/api/v1/health"
BASE = Path.home() / "Documents" / "LegalKB" / "public-demo-runtime"
APP = BASE / "app-candidate"
LAUNCHER = BASE / "start-public-demo.ps1"
SCRIPT = APP / "implementation" / "phase7" / "003_web_server.py"

class InspectionHold(ValueError):
    """A specific, not implicitly actionable, runtime preflight failure."""


def demand(ok: bool, reason: str) -> None:
    if not ok:
        raise InspectionHold(reason)


def command(argv: list[str], timeout: float = 10) -> str:
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, shell=False,
                            check=False)
    demand(result.returncode == 0 and len(result.stdout) <= 65536, "OWNER_READONLY_COMMAND_HOLD")
    return result.stdout.decode("utf-8-sig", errors="strict").strip()


def owner_files() -> dict:
    demand(os.name == "nt", "OWNER_WINDOWS_ONLY")
    for path in (BASE, APP, LAUNCHER, SCRIPT):
        demand(path.exists() and not path.is_symlink()
               and not (hasattr(path, "is_junction") and path.is_junction()),
               "OWNER_RUNTIME_PATH_MISSING_OR_REPARSE")
    demand(LAUNCHER.is_file() and SCRIPT.is_file(), "OWNER_RUNTIME_FILE_MISSING")
    demand(hashlib.sha256(LAUNCHER.read_bytes()).hexdigest() == LAUNCHER_SHA256,
           "OWNER_PUBLIC_LAUNCHER_SHA_CHANGED")
    demand(command(["git", "-C", str(APP), "rev-parse", "HEAD"]) == OWNER_RELEASE_HEAD,
           "PUBLIC_RUNTIME_RELEASE_HEAD_CHANGED")
    demand(command(["git", "-C", str(APP), "status", "--porcelain=v1",
                    "--untracked-files=no"]) == "", "PUBLIC_RUNTIME_GIT_DIRTY")
    return {"source_git_head_pinned": True, "launcher_sha256_pinned": True}


def windows_task_and_port() -> dict:
    # Fixed, no-write Windows commands. No environment-provided input is
    # interpolated into these PowerShell scripts.
    script = (
        "$ErrorActionPreference='Stop';"
        "$t=Get-ScheduledTask -TaskName 'LegalKB Public Demo Runtime' -ErrorAction Stop;"
        "$a=@($t.Actions);"
        "if($a.Count -ne 1){throw 'TASK_ACTION_COUNT'};"
        "$listen=@(Get-NetTCPConnection -State Listen -LocalPort 8878 "
        "-ErrorAction SilentlyContinue);"
        "$listeners=@();"
        "foreach($l in $listen){"
        "$pr=Get-CimInstance Win32_Process -Filter "
        "('ProcessId='+$l.OwningProcess) -ErrorAction SilentlyContinue;"
        "$listeners+=@{ip=[string]$l.LocalAddress;pid=[int]$l.OwningProcess;"
        "name=[string]$pr.Name;cmd=[string]$pr.CommandLine}};"
        "@{task_name=[string]$t.TaskName;task_state=[string]$t.State;"
        "task_executable=[string]$a[0].Execute;"
        "task_args=[string]$a[0].Arguments;listener=@($listeners)}"
        "|ConvertTo-Json -Depth 6 -Compress"
    )
    data = json.loads(command(["powershell.exe", "-NoProfile", "-NonInteractive",
                               "-Command", script], timeout=15))
    demand(isinstance(data, dict) and set(data) ==
           {"task_name", "task_state", "task_executable", "task_args", "listener"},
           "OWNER_TASK_STATUS_SCHEMA_CHANGED")
    return data


def serve_proxy() -> dict:
    raw = json.loads(command(["tailscale.exe", "serve", "status", "--json"], timeout=10))
    web = raw.get("Web")
    demand(isinstance(web, dict), "TAILSCALE_SERVE_SCHEMA_HOLD")
    matched = [
        (name, conf) for name, conf in web.items()
        if name.endswith(":8443")
    ]
    demand(len(matched) == 1 and isinstance(matched[0][1], dict),
           "TAILSCALE_FUNNEL_PORT_HOLD")
    handlers = matched[0][1].get("Handlers")
    demand(isinstance(handlers, dict) and isinstance(handlers.get("/"), dict)
           and handlers["/"].get("Proxy") == PUBLIC_PROXY,
           "TAILSCALE_FUNNEL_ROUTE_CHANGED")
    return {"funnel_target_pinned": True}


def get_health(url: str) -> dict | None:
    try:
        with urlopen(url, timeout=3) as res:
            if res.status != 200:
                return None
            raw = res.read(4096)
            demand(len(raw) <= 2048, "OWNER_HEALTH_RESPONSE_OVERSIZED")
            obj = json.loads(raw)
            demand(isinstance(obj, dict), "OWNER_HEALTH_RESPONSE_INVALID")
            return obj
    except (OSError, ValueError, URLError, HTTPError):
        return None


def classify(task: dict, public_health: dict | None,
             private_health: dict | None) -> dict:
    """Pure decision boundary. Unknown or altered owner state is never restarted."""
    demand(task.get("task_name") == TASK_NAME, "OTHER_TASK_HOLD")
    exe = str(task.get("task_executable", "")).replace("/", "\\").lower()
    args = str(task.get("task_args", "")).replace("/", "\\").lower()
    launcher = str(LAUNCHER).replace("/", "\\").lower()
    demand(exe.endswith("\\powershell.exe") and
           args.count(launcher) == 1 and
           "-file" in args, "OWNER_TASK_ACTION_CHANGED")
    demand(task.get("task_state") in ("Ready", "Running"),
           "OWNER_TASK_DISABLED_OR_UNKNOWN")
    demand(isinstance(private_health, dict) and
           private_health.get("status") == "ok",
           "PRIVATE_APP_NOT_HEALTHY")
    ports = task.get("listener")
    demand(isinstance(ports, list) and len(ports) <= 1,
           "PUBLIC_PORT_MULTIPLE_LISTENERS")
    if ports:
        p = ports[0]
        demand(isinstance(p, dict) and p.get("ip") == "127.0.0.1",
               "PUBLIC_PORT_WRONG_BINDING")
        name = str(p.get("name", "")).lower()
        cmd = str(p.get("cmd", "")).replace("/", "\\").lower()
        expected = str(SCRIPT).replace("/", "\\").lower()
        demand(name == "pythonw.exe" and
               cmd.count(expected) == 1,
               "PUBLIC_PORT_OTHER_OWNER")
        demand(isinstance(public_health, dict) and
               public_health.get("status") == "ok" and
               public_health.get("mode") == "public-demo" and
               public_health.get("app_version") == "phase8-public-demo",
               "PUBLIC_PROCESS_PRESENT_BUT_UNHEALTHY")
        return {"status": "HEALTHY", "recovery_candidate": False,
                "owner_process_verified": True,
                "public_health_verified": True}
    demand(public_health is None, "PUBLIC_HEALTH_WITHOUT_VERIFIABLE_LISTENER")
    demand(task["task_state"] == "Ready", "TASK_RUNNING_WITHOUT_LISTENER")
    return {"status": "RECOVERY_CANDIDATE_NOT_AUTHORIZED",
            "recovery_candidate": True,
            "owner_process_verified": False,
            "public_health_verified": False}


def inspect() -> dict:
    pin = owner_files()
    task = windows_task_and_port()
    route = serve_proxy()
    result = classify(task, get_health(PUBLIC_HEALTH), get_health(PRIVATE_HEALTH))
    return {"schema": SCHEMA, **pin, **route, **result,
            "read_only": True, "task_triggered": False,
            "process_terminated": False, "keys_read": False,
            "owner_execution_authority": False,
            "shared_reboot_performed": False}


def main() -> int:
    if sys.argv[1:] != ["--inspect"]:
        print(json.dumps({"schema": SCHEMA, "status": "HOLD",
                          "reason": "READONLY_INSPECT_ONLY",
                          "owner_execution_authority": False}, sort_keys=True))
        return 2
    try:
        result = inspect()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (InspectionHold, OSError, ValueError, TypeError, KeyError,
            subprocess.TimeoutExpired, UnicodeError) as exc:
        code = str(exc) if isinstance(exc, InspectionHold) else "OWNER_READONLY_INSPECTION_FAILED"
        print(json.dumps({"schema": SCHEMA, "status": "HOLD",
                          "reason": code,
                          "recovery_candidate": False, "read_only": True,
                          "owner_execution_authority": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
