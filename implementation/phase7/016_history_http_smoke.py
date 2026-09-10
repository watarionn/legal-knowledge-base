from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    with urlopen(request, timeout=15) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def run(base_url: str) -> dict:
    base = base_url.rstrip("/")
    with urlopen(base + "/", timeout=10) as response:
        html_status = response.status
        html = response.read().decode("utf-8")
    health_status, health = _get_json(base + "/api/v1/health")
    query_status, query = _post_json(
        base + "/api/v1/query",
        {"question": "民法の第90条を確認したい", "as_of_date": "2026-09-10"},
    )
    current_status, current = _get_json(
        base + "/api/v1/laws/129AC0000000089/history?"
        + urlencode({"as_of_date": "2026-09-10"})
    )
    ambiguous_status, ambiguous = _get_json(
        base + "/api/v1/laws/129AC0000000089/history?"
        + urlencode({"as_of_date": "2023-04-01"})
    )
    missing_status, missing = _get_json(
        base + "/api/v1/laws/129AC0000000089/history?"
        + urlencode({"as_of_date": "2024-04-01"})
    )
    invalid_status, invalid = _get_json(
        base + "/api/v1/laws/129AC0000000089/history?"
        + urlencode({"as_of_date": "2026-02-30"})
    )

    selected = [r for r in current.get("revisions", []) if r.get("selected_for_as_of")]
    candidates = [r for r in ambiguous.get("revisions", []) if r.get("candidate_for_as_of")]
    checks = {
        "root_phase72": html_status == 200 and "Phase 7-2" in html and 'id="history-panel"' in html,
        "health_phase72": health_status == 200 and health.get("app_version") == "phase7-2-history",
        "query_resolved": query_status == 200 and query.get("status") == "evidence-only",
        "history_current_resolved": current_status == 200 and current.get("temporal_resolution", {}).get("status") == "resolved",
        "history_selected_once": len(selected) == 1,
        "history_selected_matches_query": (
            len(selected) == 1
            and selected[0].get("law_revision_id")
            == query.get("temporal_resolution", {}).get("selected_revision_id")
        ),
        "history_source_truth": current.get("source_truth") == "phase3-phase4",
        "ambiguous_preserved": (
            ambiguous_status == 200
            and ambiguous.get("temporal_resolution", {}).get("status") == "ambiguous"
            and len(candidates) == 2
            and not any(r.get("selected_for_as_of") for r in ambiguous.get("revisions", []))
        ),
        "missing_not_fallback": (
            missing_status == 200
            and missing.get("temporal_resolution", {}).get("status") == "resolved"
            and missing.get("temporal_resolution", {}).get("content_status") == "missing"
        ),
        "invalid_date_rejected": (
            invalid_status == 400
            and invalid.get("error", {}).get("code") == "INVALID_REQUEST"
        ),
    }
    return {
        "schema_version": "1.0",
        "runner": "016_history_http_smoke.py",
        "base_url_recorded": False,
        "source_truth": "phase3-phase4",
        "checks": checks,
        "observations": {
            "current_revision_count": current.get("revision_count"),
            "current_selected_revision_id": (
                selected[0].get("law_revision_id") if len(selected) == 1 else None
            ),
            "ambiguous_candidate_count": len(candidates),
            "historical_content_status": missing.get("temporal_resolution", {}).get("content_status"),
        },
        "status": "passed" if all(checks.values()) else "failed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--result")
    args = parser.parse_args()
    report = run(args.base_url)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.result:
        from pathlib import Path

        Path(args.result).write_text(text + "\n", encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
