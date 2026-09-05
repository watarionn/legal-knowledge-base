from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any

PHASE5_DIR = Path(__file__).resolve().parent
BASE_PATH = PHASE5_DIR / "008_full_search_benchmark.py"
RUNNER_VERSION = "phase5-full-search-benchmark-0.2"


def _load_base():
    spec = importlib.util.spec_from_file_location("legal_kb_phase5_full_search_benchmark_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_base()
DEFAULT_QUERIES = BASE.DEFAULT_QUERIES


def _delta(after: dict[str, int], before: dict[str, int]) -> dict[str, int]:
    return {key: int(after[key]) - int(before[key]) for key in after}


def run(database_url: str, queries: tuple[str, ...], repeats: int) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if not queries:
        raise ValueError("at least one query is required")

    conn = BASE._connect(database_url)
    try:
        initial_size = BASE._size_snapshot(conn)
        initial_counts = BASE._counts(conn)

        BASE._execute(conn, "TRUNCATE TABLE legal_kb.search_unit")
        empty_size = BASE._size_snapshot(conn)
        empty_counts = BASE._counts(conn)
        if empty_counts["search_units"] != 0:
            raise AssertionError("search_unit was not empty after TRUNCATE")

        inserted, rebuild_seconds = BASE._timed(
            lambda: int(BASE._scalar(conn, "SELECT legal_kb.rebuild_search_units(NULL)"))
        )
        _, analyze_seconds = BASE._timed(
            lambda: BASE._execute(conn, "ANALYZE legal_kb.search_unit")
        )

        after_size = BASE._size_snapshot(conn)
        after_counts = BASE._counts(conn)

        if inserted != after_counts["search_units"]:
            raise AssertionError(
                f"inserted/search_unit mismatch: {inserted} != {after_counts['search_units']}"
            )
        if after_counts["search_units"] != after_counts["eligible_nodes"]:
            raise AssertionError(
                "search unit accounting mismatch: "
                f"{after_counts['search_units']} != {after_counts['eligible_nodes']}"
            )

        revision_id = BASE._sample_revision(conn)
        lexical_global: dict[str, Any] = {}
        lexical_revision: dict[str, Any] = {}
        for query in queries:
            lexical_global[query] = BASE._benchmark_query(
                conn,
                "SELECT * FROM legal_kb.lexical_search(%s, NULL, 20)",
                (query,),
                repeats,
            )
            if revision_id is not None:
                lexical_revision[query] = BASE._benchmark_query(
                    conn,
                    "SELECT * FROM legal_kb.lexical_search(%s, %s, 20)",
                    (query, revision_id),
                    repeats,
                )

        structural = None
        if revision_id is not None:
            structural = BASE._benchmark_query(
                conn,
                "SELECT * FROM legal_kb.structural_search(%s, 'Article', NULL, NULL, 100)",
                (revision_id,),
                repeats,
            )

        return {
            "schema_version": "1.1",
            "runner": "013_full_search_benchmark_v2.py",
            "runner_version": RUNNER_VERSION,
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "postgres_version": BASE._scalar(conn, "SELECT version()"),
            "database": BASE._scalar(conn, "SELECT current_database()"),
            "queries": list(queries),
            "repeats": repeats,
            "counts_initial": initial_counts,
            "counts_empty_baseline": empty_counts,
            "counts_after": after_counts,
            "rebuild": {
                "inserted_search_units": inserted,
                "seconds": round(rebuild_seconds, 3),
                "analyze_seconds": round(analyze_seconds, 3),
            },
            "storage_initial": initial_size,
            "storage_empty_baseline": empty_size,
            "storage_after": after_size,
            "storage_build_delta": _delta(after_size, empty_size),
            "storage_replacement_delta": _delta(after_size, initial_size),
            "sample_revision_id": revision_id,
            "lexical_global": lexical_global,
            "lexical_revision": lexical_revision,
            "structural_article": structural,
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")

    queries = tuple(args.queries) if args.queries else DEFAULT_QUERIES
    result = run(args.database_url, queries, args.repeats)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
