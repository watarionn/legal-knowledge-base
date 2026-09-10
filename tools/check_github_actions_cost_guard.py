from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ACTIVE_SUFFIXES = {".yml", ".yaml"}
ACTIVE_RUN_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}


def active_workflow_files(repo_root: Path) -> list[str]:
    workflow_dir = repo_root / ".github" / "workflows"
    if not workflow_dir.exists():
        return []
    return sorted(
        str(path.relative_to(repo_root)).replace("\\", "/")
        for path in workflow_dir.iterdir()
        if path.is_file() and path.suffix.lower() in ACTIVE_SUFFIXES
    )


def _gh_json(args: list[str]) -> Any:
    completed = subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    text = completed.stdout.strip()
    return json.loads(text) if text else None


def github_guard_state(repository: str) -> dict[str, Any]:
    permission = _gh_json(["api", f"repos/{repository}/actions/permissions"])
    runs = _gh_json([
        "run", "list", "-R", repository, "--limit", "100",
        "--json", "databaseId,workflowName,status,conclusion,event,headSha",
    ]) or []
    active_runs = [
        run for run in runs if str(run.get("status", "")).lower() in ACTIVE_RUN_STATUSES
    ]
    return {
        "actions_enabled": bool(permission.get("enabled")),
        "active_runs": active_runs,
    }


def evaluate(repo_root: Path, repository: str | None = None) -> dict[str, Any]:
    workflows = active_workflow_files(repo_root)
    result: dict[str, Any] = {
        "repo_root": str(repo_root),
        "active_workflow_files": workflows,
        "active_workflow_count": len(workflows),
        "checks": {"no_active_workflow_yaml": not workflows},
    }
    if repository:
        remote = github_guard_state(repository)
        result.update(remote)
        result["checks"]["github_actions_disabled"] = not remote["actions_enabled"]
        result["checks"]["no_active_workflow_runs"] = not remote["active_runs"]
    result["status"] = "passed" if all(result["checks"].values()) else "blocked"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fail closed unless the repository GitHub Actions cost guard is active."
    )
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repository")
    args = parser.parse_args()

    try:
        result = evaluate(args.repo_root.resolve(), args.repository)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
