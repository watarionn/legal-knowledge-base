"""CMP20 owner-only immutable public overlay entrypoint.

The reviewed patched server bytes are SHA checked and compiled as though their
__file__ were the untouched original phase7 server, preserving existing local
service imports and public web asset paths. The original worktree remains clean.
Run ONLY from the separate signed CMP20 owner launcher, never for private8877.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

OWNER_HEAD = "4acdda5aac833a30189858ff1e43c34ada23c839"
OLD_BLOB = "a394f509b51fe598eb0f1852339ba7f21e2be9b4"
PATCH_BLOB = "511f5070c8c3fac8e733b35cb897868dca77369c"
RELEASE_ID = "cmp20-public-demo-parallel-exec-v1"
RELEASE = Path(os.environ.get("LOCALAPPDATA", "")) / "RinkaMissionControl" / "releases" / RELEASE_ID
ORIGINAL_APP = Path.home() / "Documents" / "LegalKB" / "public-demo-runtime" / "app-candidate"
ORIGINAL = ORIGINAL_APP / "implementation" / "phase7" / "003_web_server.py"
PATCH = RELEASE / "003_web_server.py"


def git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def require(value: bool, reason: str):
    if not value:
        raise RuntimeError(reason)


def source_bytes() -> bytes:
    require(os.name == "nt" and os.environ.get("COMPUTERNAME", "").upper() == "YWSHTMR",
            "CMP20_OWNER_WINDOWS_ONLY")
    require(os.environ.get("LEGAL_KB_PUBLIC_DEMO") == "1" and
            os.environ.get("LEGAL_KB_HOST") == "127.0.0.1" and
            os.environ.get("LEGAL_KB_PORT") == "8879" and
            not os.environ.get("LEGAL_KB_ANSWER_PROVIDER"),
            "CMP20_PUBLIC_MODE_ONLY")
    for path in (ORIGINAL_APP, ORIGINAL.parent, RELEASE):
        require(path.is_dir() and not path.is_symlink() and
                not (hasattr(path, "is_junction") and path.is_junction()),
                "CMP20_DIRECTORY_REPARSE_HOLD")
    for path in (ORIGINAL, PATCH):
        require(path.is_file() and not path.is_symlink() and
                not (hasattr(path, "is_junction") and path.is_junction())
                and 0 < path.stat().st_size <= 200000,
                "CMP20_SOURCE_REPARSE_HOLD")
    r = subprocess.run(["git", "-C", str(ORIGINAL_APP), "rev-parse", "HEAD"],
                       capture_output=True, timeout=8, check=False)
    require(r.returncode == 0 and
            r.stdout.decode("utf-8-sig").strip() == OWNER_HEAD,
            "CMP20_ORIGINAL_HEAD_DRIFT")
    r = subprocess.run(["git", "-C", str(ORIGINAL_APP),
                        "status", "--porcelain=v1", "--untracked-files=no"],
                       capture_output=True, timeout=8, check=False)
    require(r.returncode == 0 and r.stdout.strip() == b"",
            "CMP20_ORIGINAL_TRACKED_FILES_DIRTY")
    original = ORIGINAL.read_bytes()
    patch = PATCH.read_bytes()
    require(git_blob(original) == OLD_BLOB and git_blob(patch) == PATCH_BLOB,
            "CMP20_SOURCE_GIT_BLOB_CHANGED")
    return patch


def main():
    source = source_bytes()
    # Preserve imports/web assets from immutable original live release without
    # changing the original file. Private app remains an entirely separate PID.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ORIGINAL.parent))
    env = {
        "__name__": "__main__",
        "__file__": str(ORIGINAL),
        "__package__": None,
        "__builtins__": __builtins__,
    }
    exec(compile(source, str(ORIGINAL), "exec"), env)


if __name__ == "__main__":
    main()
