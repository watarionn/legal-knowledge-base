from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import time
from typing import Any, Callable

DEFAULT_QUERIES = (
    "国民",
    "法律",
    "政令",
    "附則",
)


def _connect(database_url: str):
    import psycopg

    return psycopg.connect(database_url, autocommit=True)


def _scalar(conn, sql: str, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return None if row is None else row[0]


def _row(conn, sql: str, params=()) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        names = [column.name for column in cur.description]
        values = cur.fetchone()
    return dict(zip(names, values))


def _size_snapshot(conn) -> dict[str, int]:
    row = _row(
        conn,
        """
        SELECT
          pg_database_size(current_database())::bigint AS database_bytes,
          pg_total_relation_size('legal_kb.search_unit'::regclass)::bigint AS search_unit_total_bytes,
          pg_relation_size('legal_kb.search_unit'::regclass)::bigint AS search_unit_heap_bytes,
          pg_indexes_size('legal_kb.search_unit'::regclass)::bigint AS search_unit_index_bytes
        """,
    )
    return {key: int(value) for key, value in row.items()}


def _counts(conn) -> dict[str, int]:
    row = _row(
        conn,
        """
        SELECT
          (SELECT count(*) FROM legal_kb.law_document
             WHERE parse_status IN ('succeeded', 'succeeded-with-warnings'))::bigint
             AS succeeded_documents,
          (SELECT count(*) FROM legal_kb.provision_node
             WHERE text_original IS NOT NULL
               AND legal_kb.normalize_search_text(text_original) <> '')::bigint
             AS eligible_nodes,
          (SELECT count(*) FROM legal_kb.search_unit)::bigint AS search_units,
          (SELECT count(DISTINCT document_pk) FROM legal_kb.search_unit)::bigint
             AS indexed_documents,
          (SELECT count(DISTINCT law_revision_id) FROM legal_kb.search_unit)::bigint
             AS indexed_revisions
        """,
    )
    return {key: int(value) for key, value in row.items()}


def _timed(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    value = call()
    return value, time.perf_counter() - started


def _latency_stats(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)
    p95_index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95))))
    return {
        "min_ms": round(min(ordered), 3),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "max_ms": round(max(ordered), 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
    }


def _benchmark_query(conn, sql: str, params: tuple, repeats: int) -> dict[str, Any]:
    samples_ms: list[float] = []
    row_count = 0
    for _ in range(repeats):
        started = time.perf_counter()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        samples_ms.append((time.perf_counter() - started) * 1000)
        row_count = len(rows)
    return {
        "returned_rows": row_count,
        "repeats": repeats,
        "latency": _latency_stats(samples_ms),
    }


def _sample_revision(conn) -> str | None:
    return _scalar(
        conn,
        """
        SELECT law_revision_id
        FROM legal_kb.search_unit
        GROUP BY law_revision_id
        ORDER BY count(*) DESC, law_revision_id
        LIMIT 1
        """,
    )


def run(database_url: str, queries: tuple[str, ...], repeats: int) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if not queries:
        raise ValueError("at least one query is required")

    conn = _connect(database_url)
    try:
        before_size = _size_snapshot(conn)
        before_counts = _counts(conn)

        inserted, rebuild_seconds = _timed(
            lambda: int(_scalar(conn, "SELECT legal_kb.rebuild_search_units(NULL)"))
        )
        analyze_result, analyze_seconds = _timed(
            lambda: _scalar(conn, "ANALYZE legal_kb.search_unit; SELECT 1")
        )
        del analyze_result

        after_size = _size_snapshot(conn)
        after_counts = _counts(conn)

        if inserted != after_counts["search_units"]:
            raise AssertionError(
                f"inserted/search_unit mismatch: {inserted} != {after_counts['search_units']}"
            )
        if after_counts["search_units"] != after_counts["eligible_nodes"]:
            raise AssertionError(
                "search unit accounting mismatch: "
                f"{after_counts['search_units']} != {after_counts['eligible_nodes']}"
            )

        revision_id = _sample_revision(conn)
        lexical_global = {}
        lexical_revision = {}
        for query in queries:
            lexical_global[query] = _benchmark_query(
                conn,
                "SELECT * FROM legal_kb.lexical_search(%s, NULL, 20)",
                (query,),
                repeats,
            )
            if revision_id is not None:
                lexical_revision[query] = _benchmark_query(
                    conn,
                    "SELECT * FROM legal_kb.lexical_search(%s, %s, 20)",
                    (query, revision_id),
                    repeats,
                )

        structural = None
        if revision_id is not None:
            structural = _benchmark_query(
                conn,
                "SELECT * FROM legal_kb.structural_search(%s, 'Article', NULL, NULL, 100)",
                (revision_id,),
                repeats,
            )

        return {
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "postgres_version": _scalar(conn, "SELECT version()"),
            "database": _scalar(conn, "SELECT current_database()"),
            "queries": list(queries),
            "repeats": repeats,
            "counts_before": before_counts,
            "counts_after": after_counts,
            "rebuild": {
                "inserted_search_units": inserted,
                "seconds": round(rebuild_seconds, 3),
                "analyze_seconds": round(analyze_seconds, 3),
            },
            "storage_before": before_size,
            "storage_after": after_size,
            "storage_delta": {
                key: after_size[key] - before_size[key]
                for key in after_size
            },
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
        args.result.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
