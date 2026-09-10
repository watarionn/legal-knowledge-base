from __future__ import annotations

from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent


def _load():
    path = HERE / "012_law_history_service.py"
    spec = importlib.util.spec_from_file_location("phase7_history_smoke_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SERVICE = _load()


def run(database_url: str) -> dict:
    import psycopg

    started = perf_counter()
    cases = []
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
        current = SERVICE.get_law_history(
            conn, "129AC0000000089", as_of_date=date(2026, 9, 10)
        )
        if current is None:
            raise RuntimeError("Civil Code history not found")
        cases.append({
            "name": "civil-current",
            "temporal_status": current["temporal_resolution"]["status"],
            "selected_revision_id": current["temporal_resolution"]["selected_revision_id"],
            "revision_count": current["revision_count"],
            "selected_count": sum(1 for r in current["revisions"] if r["selected_for_as_of"]),
            "candidate_count": sum(1 for r in current["revisions"] if r["candidate_for_as_of"]),
            "selected_content_status": next(
                r["content_status"] for r in current["revisions"] if r["selected_for_as_of"]
            ),
        })

        ambiguous = SERVICE.get_law_history(
            conn, "129AC0000000089", as_of_date=date(2023, 4, 1)
        )
        if ambiguous is None:
            raise RuntimeError("Civil Code ambiguous history not found")
        cases.append({
            "name": "civil-ambiguous",
            "temporal_status": ambiguous["temporal_resolution"]["status"],
            "selected_revision_id": ambiguous["temporal_resolution"]["selected_revision_id"],
            "candidate_count": sum(1 for r in ambiguous["revisions"] if r["candidate_for_as_of"]),
        })
        historical = SERVICE.get_law_history(
            conn, "129AC0000000089", as_of_date=date(2024, 4, 1)
        )
        if historical is None:
            raise RuntimeError("Civil Code historical history not found")
        cases.append({
            "name": "civil-historical-content",
            "temporal_status": historical["temporal_resolution"]["status"],
            "selected_revision_id": historical["temporal_resolution"]["selected_revision_id"],
            "content_status": historical["temporal_resolution"]["content_status"],
        })

    checks = {
        "current_resolved": cases[0]["temporal_status"] == "resolved",
        "current_selected_once": cases[0]["selected_count"] == 1,
        "current_content_available": cases[0]["selected_content_status"] == "available",
        "ambiguous_not_selected": (
            cases[1]["temporal_status"] == "ambiguous"
            and cases[1]["selected_revision_id"] is None
            and cases[1]["candidate_count"] >= 2
        ),
        "historical_missing_not_fallback": (
            cases[2]["temporal_status"] == "resolved"
            and cases[2]["content_status"] == "missing"
        ),
    }
    return {
        "schema_version": "1.0",
        "runner": Path(__file__).name,
        "database_url_recorded": False,
        "source_truth": "phase3-phase4",
        "cases": cases,
        "checks": checks,
        "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        "status": "passed" if all(checks.values()) else "failed",
    }

def main() -> None:
    database_url = os.environ.get("LEGAL_KB_DATABASE_URL")
    if not database_url:
        raise SystemExit("LEGAL_KB_DATABASE_URL is required")
    result = run(database_url)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
