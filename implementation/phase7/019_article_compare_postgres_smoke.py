from __future__ import annotations

from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
SERVICE_PATH = HERE / "017_article_compare_service.py"
spec = importlib.util.spec_from_file_location("phase7_article_compare_smoke_service", SERVICE_PATH)
assert spec and spec.loader
SERVICE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = SERVICE
spec.loader.exec_module(SERVICE)

LAW_ID = "129AC0000000089"
FROM_DATE = date(2026, 9, 10)
TO_DATE = date(2027, 7, 1)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
def main() -> None:
    database_url = os.environ.get("LEGAL_KB_DATABASE_URL")
    if not database_url:
        raise SystemExit("LEGAL_KB_DATABASE_URL is required")
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc

    started = time.perf_counter()
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
        summary = SERVICE.get_article_comparison(
            conn, LAW_ID, from_date=FROM_DATE, to_date=TO_DATE
        )
        detail = SERVICE.get_article_comparison(
            conn, LAW_ID, from_date=FROM_DATE, to_date=TO_DATE,
            article_num="891", scope_key="main",
        )
        ambiguous = SERVICE.get_article_comparison(
            conn, LAW_ID, from_date=FROM_DATE, to_date=TO_DATE,
            article_num="1",
        )
        blocked_temporal = SERVICE.get_article_comparison(
            conn, LAW_ID, from_date=date(2023, 4, 1), to_date=TO_DATE
        )
        blocked_content = SERVICE.get_article_comparison(
            conn, LAW_ID, from_date=date(2024, 4, 1), to_date=TO_DATE
        )

    require(summary["status"] == "ok", "full comparison did not resolve")
    require(summary["source_truth"] == "phase3-phase4", "source truth changed")
    require(summary["summary"]["left_duplicate_article_keys"] == {}, "left duplicate scope keys remain")
    require(summary["summary"]["right_duplicate_article_keys"] == {}, "right duplicate scope keys remain")
    require(summary["summary"]["left_missing_article_scope_count"] == 0, "left article scope missing")
    require(summary["summary"]["right_missing_article_scope_count"] == 0, "right article scope missing")
    require(detail["status"] == "ok", "specific comparison failed")
    require(detail["article"]["status"] == "changed", "main article 891 was not changed")
    require(detail["article"]["scope_key"] == "main", "main scope was not preserved")
    require(bool(detail["article"]["diff_segments"]), "specific diff is empty")
    require(ambiguous["status"] == "blocked-article-ambiguous", "ambiguous article was guessed")
    require(len(ambiguous["article"]["candidates"]) > 1, "ambiguous article candidates missing")
    require(blocked_temporal["status"] == "blocked-temporal", "ambiguous temporal side was not blocked")
    require(blocked_content["status"] == "blocked-content", "missing historical body was not blocked")
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    report = {
        "status": "passed",
        "law_id": LAW_ID,
        "from_date": FROM_DATE.isoformat(),
        "to_date": TO_DATE.isoformat(),
        "elapsed_ms": elapsed_ms,
        "counts": summary["summary"]["counts"],
        "changed_article_count": summary["summary"]["changed_article_count"],
        "warnings": summary["summary"]["warnings"],
        "article_891_status": detail["article"]["status"],
        "article_891_diff_segment_count": len(detail["article"]["diff_segments"]),
        "article_1_without_scope_status": ambiguous["article"]["status"],
        "article_1_candidate_count": len(ambiguous["article"]["candidates"]),
        "blocked_temporal_status": blocked_temporal["status"],
        "blocked_content_status": blocked_content["status"],
        "source_truth": summary["source_truth"],
        "database_url_recorded": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
