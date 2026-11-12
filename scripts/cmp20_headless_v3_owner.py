"""CMP-20 owner-only staged V3 headless release and exact two-Task cutover.

Keys and signature never leave owner-private storage. An independently signed
new grant is required to CHANGE V2's scheduled authority; the old Ed25519 V2
packet does not authorize this migration. Exact preimages/backups or HOLD.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import cmp20_headless_v3_verify as signed
import cmp20_headless_v3_guard as runtime

CONSENT = {
    "--enroll": "ENROLL CMP20 HEADLESS V3 DUAL OWNER KEYS",
    "--issue": "ISSUE CMP20 HEADLESS V3 PURPOSE SIGNATURE",
}
PYTHON = r"C:\Python314\python.exe"
QA = Path(__file__).resolve().parent
PRIOR = signed.V2_RELEASE / "cmp20_public_guarded_owner_v2.py"

class CutoverHold(ValueError):
    pass

def require(test, why):
    if not test:
        raise CutoverHold(why)

def old_signed():
    signed.owner()
    prior = runtime.source_pinned(PRIOR, signed.V2_GUARD_BLOB)
    v = prior.verifier()
    require(v.inspect()["status"] == "PASS",
            "V3_OLD_SIGNED_RELEASE_NOT_VERIFIED")
    return prior

def helper():
    # V2's signed runtime release intentionally contains no signing helper.
    # Source-only V3 issuer must load the EXACT reviewed standalone helper
    # from its isolated owner QA directory; never mutate the sealed V2 set.
    source = QA / "cmp20_public_release_owner_signer.py"
    return runtime.source_pinned(
        source, "4199852e192349270096807af52d358ee89afe2b")

def reviewed_qa_sources(manifest=None):
    sources = {}
    for name in signed.SOURCES:
        raw = signed.safe_file(QA / name)
        sources[name] = signed.blob(raw)
    if manifest is not None:
        require(sources == manifest["source_blobs"],
                "V3_REVIEWED_QA_CHANGED")
    return sources

def public_b64(k: Ed25519PrivateKey):
    return base64.b64encode(k.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw)).decode("ascii")

def enroll():
    signed.owner()
    old_signed()
    reviewed_qa_sources()
    require(not signed.TRUST.exists(), "V3_TRUST_ALREADY_EXISTS")
    h = helper()
    signed.TRUST.mkdir(mode=0o700)
    h.protect_new(signed.TRUST)
    keys_path = signed.TRUST / "keys"
    keys_path.mkdir(mode=0o700)
    h.protect_new(keys_path)
    keys = {role: Ed25519PrivateKey.generate()
            for role in ("issuer", "reviewer")}
    require(public_b64(keys["issuer"]) != public_b64(keys["reviewer"]),
            "V3_KEYS_NOT_DISTINCT")
    for role, key in keys.items():
        raw = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        h.create_new(keys_path / (role + ".pem"), raw)
    trust = {"schema": signed.TRUST_SCHEMA, "purpose": signed.PURPOSE}
    for role in ("issuer", "reviewer"):
        trust[role + "_public_b64"] = public_b64(keys[role])
    h.create_new(signed.TRUST / "trust.json", signed.canonical(trust))
    return {"status": "V3_TWO_ROLE_KEYS_ENROLLED",
            "trust_sha256": signed.digest(signed.canonical(trust)),
            "public_key_export_only": True, "task_mutated": False}

def issue(pin: str):
    signed.owner()
    require(re.fullmatch("[0-9a-f]{64}", pin) is not None,
            "V3_INDEPENDENT_TRUST_PIN_REQUIRED")
    old_signed()
    require(not (signed.TRUST / "manifest.json").exists()
            and not (signed.TRUST / "packet.json").exists(),
            "V3_ALREADY_SIGNED")
    trust_raw = signed.safe_file(signed.TRUST / "trust.json", 8192)
    require(signed.digest(trust_raw) == pin,
            "V3_TRUST_PREIMAGE_CHANGED")
    trust = signed.strict_json(trust_raw)
    manifest = signed.manifest_fields(reviewed_qa_sources())
    data = signed.canonical(signed.statement(manifest))
    sigs = {}
    for role in ("issuer", "reviewer"):
        key = serialization.load_pem_private_key(
            signed.safe_file(signed.TRUST / "keys" /
                             (role + ".pem"), 8192), password=None)
        require(isinstance(key, Ed25519PrivateKey)
                and public_b64(key) == trust[role + "_public_b64"],
                "V3_SIGNER_PUBLIC_ROLE_CHANGED")
        sigs[role + "_signature_b64"] = base64.b64encode(
            key.sign(data)).decode("ascii")
    packet = {"schema": signed.PACKET_SCHEMA,
              "statement": signed.statement(manifest), **sigs}
    signed.check_packet(trust, manifest, packet)
    h = helper()
    h.create_new(signed.TRUST / "manifest.json",
                 signed.canonical(manifest))
    h.create_new(signed.TRUST / "packet.json",
                 signed.canonical(packet))
    signed.check_packet(
        signed.strict_json(signed.safe_file(signed.TRUST / "trust.json")),
        signed.strict_json(signed.safe_file(signed.TRUST / "manifest.json")),
        signed.strict_json(signed.safe_file(signed.TRUST / "packet.json")))
    return {"status": "V3_ED25519_TWO_ROLE_PACKET_ISSUED",
            "manifest_sha256": signed.digest(signed.canonical(manifest)),
            "packet_sha256": signed.digest(signed.canonical(packet)),
            "source_blobs": manifest["source_blobs"],
            "task_mutated": False, "old_release_unchanged": True}

def stage():
    signed.owner()
    old_signed()
    require(not signed.RELEASE.exists(), "V3_RELEASE_ALREADY_EXISTS")
    manifest = signed.strict_json(signed.safe_file(
        signed.TRUST / "manifest.json"))
    trust = signed.strict_json(signed.safe_file(signed.TRUST / "trust.json"))
    packet = signed.strict_json(signed.safe_file(signed.TRUST / "packet.json"))
    signed.check_packet(trust, manifest, packet)
    reviewed_qa_sources(manifest)
    h = helper()
    signed.RELEASE.mkdir(mode=0o700)
    h.protect_new(signed.RELEASE)
    for name in signed.SOURCES:
        h.create_new(signed.RELEASE / name, signed.safe_file(QA / name))
    output = signed.verify()
    require(output["status"] == "PASS", "V3_SIGNED_STAGE_READBACK_HOLD")
    return {"status": "V3_SIGNED_RELEASE_STAGED",
            "signed_readback": output["status"],
            "production_task_mutated": False}

def ps(command: str, env=None) -> str:
    process = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=30, shell=False,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False)
    require(process.returncode == 0 and len(process.stdout) <= 64000,
            "V3_FIXED_WINDOWS_TASK_READBACK_FAILED")
    return process.stdout.decode("utf-8-sig").strip()

def task_xml():
    """Proposed new disabled Task, never edits V2 on registration."""
    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)
    def sub(parent, kind, value=None):
        x = ET.SubElement(parent, "{" + ns + "}" + kind)
        if value is not None:
            x.text = value
        return x
    task = ET.Element("{" + ns + "}Task", {"version": "1.3"})
    regs = sub(task, "RegistrationInfo")
    sub(regs, "Description",
        "CMP20 owner two-role signed V3 windowless public only guardian")
    triggers = sub(task, "Triggers")
    daily = sub(triggers, "CalendarTrigger")
    repeat = sub(daily, "Repetition")
    sub(repeat, "Interval", "PT5M")
    sub(repeat, "Duration", "P1D")
    sub(repeat, "StopAtDurationEnd", "false")
    sub(daily, "StartBoundary", "2026-11-12T00:00:00")
    sub(daily, "Enabled", "true")
    by_day = sub(daily, "ScheduleByDay")
    sub(by_day, "DaysInterval", "1")
    login = sub(triggers, "LogonTrigger")
    sub(login, "Enabled", "true")
    sub(login, "UserId", signed.OWNER_SID)
    principals = sub(task, "Principals")
    owner = sub(principals, "Principal")
    owner.set("id", "Author")
    sub(owner, "UserId", signed.OWNER_SID)
    sub(owner, "LogonType", "InteractiveToken")
    sub(owner, "RunLevel", "LeastPrivilege")
    settings = sub(task, "Settings")
    for key, val in (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("AllowHardTerminate", "false"),
        ("StartWhenAvailable", "true"),
        ("Enabled", "false"),
        ("Hidden", "true"),
        ("ExecutionTimeLimit", "PT2M"),
        ("AllowStartOnDemand", "false"),
        ("Priority", "7"),
    ):
        sub(settings, key, val)
    actions = sub(task, "Actions")
    actions.set("Context", "Author")
    exe = sub(actions, "Exec")
    sub(exe, "Command", signed.PYTHONW)
    sub(exe, "Arguments", signed.ARGUMENTS)
    sub(exe, "WorkingDirectory", str(signed.RELEASE))
    return ET.tostring(task, encoding="unicode", xml_declaration=False)

def task_exists(name: str) -> bool:
    require(name in (signed.TASK_NAME, signed.OLD_TASK),
            "V3_UNKNOWN_TASK")
    return ps(
        "$t=Get-ScheduledTask -TaskName '" + name +
        "' -ErrorAction SilentlyContinue;if($null -eq $t){'NO'}else{'YES'}"
    ) == "YES"

def task_snapshot(name: str) -> dict:
    old = old_signed()
    with runtime.invisible_children():
        return runtime.task_info(old, name)

def register_disabled():
    signed.verify()
    require(not task_exists(signed.TASK_NAME),
            "V3_TASK_ALREADY_PRESENT")
    old = task_snapshot(signed.OLD_TASK)
    require(old["state"] == "Ready", "V3_OLD_TASK_NOT_READY")
    expected_old = dict(old, state="Disabled")
    runtime.checked_old_task(expected_old)
    xml = task_xml()
    require("<Command>" + signed.PYTHONW + "</Command>" in xml,
            "V3_TASK_XML_WRONG_EXECUTABLE")
    env = dict(os.environ)
    env["CMP20_V3_XML"] = xml
    command = ("$ErrorActionPreference='Stop';"
        "if(Get-ScheduledTask -TaskName '" + signed.TASK_NAME +
        "' -ErrorAction SilentlyContinue){throw 'V3_TASK_EXISTS'};"
        "Register-ScheduledTask -TaskName '" + signed.TASK_NAME +
        "' -Xml $env:CMP20_V3_XML -ErrorAction Stop|Out-Null;"
        "'V3_DISABLED_CREATED'")
    require(ps(command, env=env) == "V3_DISABLED_CREATED",
            "V3_REGISTER_NOT_CONFIRMED")
    new = task_snapshot(signed.TASK_NAME)
    runtime.check_new_task(new, require_ready=False)
    require(new["state"] == "Disabled", "V3_NEW_TASK_NOT_DISABLED")
    return {"status": "V3_FIXED_DISABLED_TASK_REGISTERED",
            "task": signed.TASK_NAME, "old_task": old["state"],
            "old_task_modified": False}

def cutover():
    signed.verify()
    new = task_snapshot(signed.TASK_NAME)
    old = task_snapshot(signed.OLD_TASK)
    require(new["state"] == "Disabled", "V3_CUTOVER_EXPECTS_DISABLED_NEW")
    runtime.check_new_task(new, require_ready=False)
    runtime.checked_old_task(dict(old, state="Disabled"))
    require(old["state"] == "Ready", "V3_OLD_NOT_READY_FOR_CUTOVER")
    guard = old_signed()
    with runtime.invisible_children():
        guard.require_old_and_private()
        ok, _ = guard.candidate_ok()
        require(ok and guard.proxy(guard.current_route()) == guard.NEW,
                "V3_HEALTHY_PUBLIC_NOT_ON_CANDIDATE")
        guard.https_public_pass()
    # Back up exact Task Scheduler XML before touching either Task. The backup
    # remains in protected, already signed release, never Git or a worktree.
    preimage = signed.RELEASE / "v2-task-preimage.xml"
    require(not preimage.exists() and not preimage.is_symlink(),
            "V3_TASK_BACKUP_ALREADY_EXISTS")
    script = ("$ErrorActionPreference='Stop';"
              "Export-ScheduledTask -TaskName '" + signed.OLD_TASK +
              "' -ErrorAction Stop")
    original_xml = ps(script)
    require(len(original_xml) < 100000, "V3_TASK_XML_TOO_BIG")
    data = original_xml.encode("utf-8")
    with preimage.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    require(signed.safe_file(preimage) == data, "V3_BACKUP_READBACK_HOLD")
    # Exact Task name, prior action and owner identity rechecked at CAS.
    old_now = task_snapshot(signed.OLD_TASK)
    new_now = task_snapshot(signed.TASK_NAME)
    require(old == old_now and new == new_now, "V3_TASK_PREIMAGE_CHANGED")
    command = (
        "$ErrorActionPreference='Stop';"
        "$old=Get-ScheduledTask -TaskName '" + signed.OLD_TASK + "';"
        "$new=Get-ScheduledTask -TaskName '" + signed.TASK_NAME + "';"
        "if($old.State -ne 'Ready' -or $new.State -ne 'Disabled'"
        " -or $old.Actions[0].Execute -cne 'C:\\Python314\\pythonw.exe')"
        "{throw 'V3_CAS_TASK_STATE_CHANGED'};"
        "Disable-ScheduledTask -TaskName '" + signed.OLD_TASK +
        "' -ErrorAction Stop | Out-Null;"
        "Enable-ScheduledTask -TaskName '" + signed.TASK_NAME +
        "' -ErrorAction Stop | Out-Null;'V3_CUTOVER_APPLIED'")
    require(ps(command) == "V3_CUTOVER_APPLIED",
            "V3_DISABLE_ENABLE_COMMAND_FAILED")
    runtime.checked_old_task(task_snapshot(signed.OLD_TASK))
    runtime.check_new_task(task_snapshot(signed.TASK_NAME),
                           require_ready=True)
    return {"status": "V3_SIGNED_TASK_CUTOVER_PENDING_NATURAL_TICK",
            "old_task_disabled": True, "new_task_enabled": True,
            "preimage_sha256": signed.digest(data),
            "no_daemon_killed": True, "no_console_popup_claimed": True}

def rollback():
    signed.verify()
    original = task_snapshot(signed.OLD_TASK)
    new = task_snapshot(signed.TASK_NAME)
    runtime.checked_old_task(original)
    runtime.check_new_task(new, require_ready=True)
    backup = signed.RELEASE / "v2-task-preimage.xml"
    require(b"<Command>" in signed.safe_file(backup, 100000),
            "V3_ROLLBACK_BACKUP_MISSING")
    # Return to the exact preimage pythonw V2 Task (still V2 action-drift
    # HOLD); no forced task stop or fallback to a visible console action.
    command = (
        "$ErrorActionPreference='Stop';"
        "Disable-ScheduledTask -TaskName '" + signed.TASK_NAME +
        "' -ErrorAction Stop|Out-Null;"
        "Enable-ScheduledTask -TaskName '" + signed.OLD_TASK +
        "' -ErrorAction Stop|Out-Null;'V3_ROLLBACK_APPLIED'"
    )
    require(ps(command) == "V3_ROLLBACK_APPLIED",
            "V3_ROLLBACK_FAILED")
    runtime.check_new_task(task_snapshot(signed.TASK_NAME),
                           require_ready=False)
    require(task_snapshot(signed.TASK_NAME)["state"] == "Disabled"
            and task_snapshot(signed.OLD_TASK)["state"] == "Ready",
            "V3_ROLLBACK_READBACK_HOLD")
    return {"status": "V3_ROLLED_BACK_TO_PRIOR_HEADLESS_V2_TASK",
            "no_python_console_reintroduced": True,
            "v2_guardian_pass_not_claimed": True}

def inspect():
    signed.owner()
    prior = old_signed()
    return {
        "status": "READ_ONLY_V3_SOURCES",
        "prior_v2_signed": True,
        "source_blobs": reviewed_qa_sources(),
        "v3_trust_exists": signed.TRUST.exists(),
        "v3_release_exists": signed.RELEASE.exists(),
        "existing_v2_task": task_snapshot(signed.OLD_TASK),
        "v3_task_present": task_exists(signed.TASK_NAME),
        "issued_permission": False,
    }

def main() -> int:
    modes = ("--inspect", "--enroll", "--issue", "--stage",
             "--register-disabled", "--cutover", "--rollback")
    if len(sys.argv) < 2 or sys.argv[1] not in modes:
        print(json.dumps({"status": "HOLD", "reason": "V3_FIXED_ACTION_ONLY"}))
        return 2
    action = sys.argv[1]
    try:
        if action in CONSENT:
            if action == "--enroll":
                require(sys.argv[2:] == ["--owner-consent", CONSENT[action]],
                        "V3_EXPLICIT_ENROLL_CONSENT_REQUIRED")
                result = enroll()
            else:
                require(len(sys.argv) == 5
                        and sys.argv[2:4] == ["--owner-consent", CONSENT[action]]
                        and re.fullmatch("[0-9a-f]{64}", sys.argv[4]),
                        "V3_EXPLICIT_SIGN_AND_PIN_REQUIRED")
                result = issue(sys.argv[4])
        else:
            require(len(sys.argv) == 2, "V3_NO_EXTRA_ARGS")
            result = {
                "--inspect": inspect,
                "--stage": stage,
                "--register-disabled": register_disabled,
                "--cutover": cutover,
                "--rollback": rollback,
            }[action]()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (signed.V3Hold, CutoverHold, OSError, KeyError,
            TypeError, ValueError, subprocess.TimeoutExpired) as error:
        reason = str(error) if isinstance(error, (signed.V3Hold, CutoverHold)) \
            else "V3_OWNER_FIXED_ACTION_FAILED"
        print(json.dumps({"status": "HOLD", "reason": reason,
                          "scope_auto_escalated": False}, sort_keys=True))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
