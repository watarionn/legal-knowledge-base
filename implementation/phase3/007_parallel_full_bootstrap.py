#!/usr/bin/env python3
"""Resumable full-bootstrap runner for Phase 3.

This is a thin execution harness around 004_bootstrap_import.py. It keeps
parsing, temporal derivation, reconciliation, and persistence rules in the
canonical importer while adding conservative request pacing, per-law
parallelism, and resume-from-existing-database behavior.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Sequence

MODULE_PATH = Path(__file__).with_name("004_bootstrap_import.py")
spec = importlib.util.spec_from_file_location("phase3_bootstrap", MODULE_PATH)
bootstrap = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = bootstrap
spec.loader.exec_module(bootstrap)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resumable full bootstrap for legal_kb law/revision metadata"
    )
    parser.add_argument("--dsn", default=os.getenv("LEGAL_KB_DSN"))
    parser.add_argument("--base-url", default=bootstrap.BASE_URL)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=7)
    parser.add_argument("--retry-base-seconds", type=float, default=2.0)
    parser.add_argument("--max-laws", type=int, help="optional bounded integration run")
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--openapi-sha256")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--history-request-interval", type=float, default=0.6)
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument(
        "--no-resume-existing",
        action="store_true",
        help="re-fetch histories even when the restored database already contains that law",
    )
    args = parser.parse_args(argv)
    if not args.dsn:
        parser.error("--dsn or LEGAL_KB_DSN is required")
    if args.page_size < 1 or args.max_retries < 0:
        parser.error("invalid page/retry settings")
    if args.max_laws is not None and args.max_laws < 1:
        parser.error("--max-laws must be >= 1")
    if args.workers < 1 or args.workers > 8:
        parser.error("--workers must be between 1 and 8")
    if args.history_request_interval < 0:
        parser.error("--history-request-interval must be >= 0")
    if args.progress_every < 1:
        parser.error("--progress-every must be >= 1")
    if args.openapi_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", args.openapi_sha256):
        parser.error("--openapi-sha256 must be 64 hexadecimal characters")
    return args


def normalize_revision_for_storage(revision: dict[str, Any]) -> dict[str, Any]:
    """Normalize API absence markers only for canonical DB storage.

    The source assertion still receives the untouched API object. In particular,
    an empty amendment_law_id is not a valid 15-character law ID and therefore
    represents absence in the canonical relation column.
    """
    normalized = dict(revision)
    value = normalized.get("amendment_law_id")
    if isinstance(value, str) and not value.strip():
        normalized["amendment_law_id"] = None
    return normalized


def install_storage_normalizer() -> None:
    original = bootstrap.build_revision_row

    def build_revision_row(revision: dict[str, Any], law_id: str):
        return original(normalize_revision_for_storage(revision), law_id)

    bootstrap.build_revision_row = build_revision_row


def completed_law_ids(conn: Any) -> set[str]:
    """Return laws whose history import committed successfully in this DB."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT law_id FROM legal_kb.law_revision")
        return {row[0] for row in cur.fetchall()}


def pending_law_ids(law_ids: Sequence[str], completed: set[str]) -> list[str]:
    return [law_id for law_id in law_ids if law_id not in completed]


def close_interrupted_runs(conn: Any) -> list[str]:
    """Mark restored 'running' runs as partial before starting a new resume run."""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE legal_kb.ingestion_run
               SET completed_at=COALESCE(completed_at, now()),
                   result_status='partial',
                   errors_count=COALESCE(errors_count, 0) + 1
               WHERE result_status='running'
               RETURNING ingestion_run_id"""
        )
        rows = [row[0] for row in cur.fetchall()]
    conn.commit()
    return rows


def import_one(
    args: argparse.Namespace,
    psycopg: Any,
    Jsonb: Any,
    run_id: str,
    law_id: str,
) -> tuple[str, int, str | None]:
    try:
        if args.history_request_interval:
            time.sleep(args.history_request_interval)
        with psycopg.connect(args.dsn) as conn:
            count = bootstrap.import_revisions(args, conn, run_id, law_id, Jsonb)
        return law_id, count, None
    except Exception as exc:  # keep the full run alive and retry later
        return law_id, 0, f"{type(exc).__name__}: {exc}"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    install_storage_normalizer()
    psycopg, Jsonb = bootstrap.import_psycopg()
    run_id = bootstrap.make_run_id()
    started_at = bootstrap.utcnow()
    failed: dict[str, str] = {}
    revisions_seen = 0

    with psycopg.connect(args.dsn) as control:
        bootstrap.assert_schema(control)
        interrupted_run_ids = close_interrupted_runs(control)
        existing_before_run = completed_law_ids(control)
        bootstrap.insert_run(control, run_id, args.openapi_sha256)
        try:
            law_ids = bootstrap.fetch_laws(args, control, run_id, Jsonb)
            total = len(law_ids)
            completed = set() if args.no_resume_existing else existing_before_run
            pending = pending_law_ids(law_ids, completed)
            skipped = total - len(pending)
            print(
                f"laws enumerated: {total}; resume-skipped={skipped}; pending={len(pending)}",
                file=sys.stderr,
            )

            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(import_one, args, psycopg, Jsonb, run_id, law_id): law_id
                    for law_id in pending
                }
                processed = 0
                for future in concurrent.futures.as_completed(futures):
                    law_id, count, error = future.result()
                    processed += 1
                    revisions_seen += count
                    if error is not None:
                        failed[law_id] = error
                    if processed % args.progress_every == 0 or processed == len(pending):
                        print(
                            f"histories: {processed}/{len(pending)} pending laws; "
                            f"revisions={revisions_seen}; first-pass-failures={len(failed)}; "
                            f"resume-skipped={skipped}",
                            file=sys.stderr,
                        )

            if failed:
                print(
                    f"retrying {len(failed)} failed laws sequentially",
                    file=sys.stderr,
                )
            for law_id in list(failed):
                time.sleep(max(args.retry_base_seconds, args.history_request_interval, 1.0))
                try:
                    revisions_seen += bootstrap.import_revisions(
                        args, control, run_id, law_id, Jsonb
                    )
                    failed.pop(law_id, None)
                except Exception as exc:
                    control.rollback()
                    failed[law_id] = f"{type(exc).__name__}: {exc}"

            partial_by_cap = args.max_laws is not None
            unresolved_rows = (
                0
                if partial_by_cap
                else bootstrap.record_unresolved_refs(control, run_id, Jsonb)
            )
            manifest_sha256 = bootstrap.run_manifest_hash(control, run_id)
            warnings, errors = bootstrap.issue_counts(control, run_id)
            status = "partial" if partial_by_cap or failed else "succeeded"
            bootstrap.finish_run(
                control, run_id, status, warnings, errors + len(failed)
            )
            report = {
                "schema_version": "1.0",
                "run_id": run_id,
                "parser_version": bootstrap.PARSER_VERSION,
                "runner": "phase3-resumable-full-bootstrap-1.1",
                "workers": args.workers,
                "history_request_interval_seconds": args.history_request_interval,
                "resume_existing": not args.no_resume_existing,
                "interrupted_run_ids_closed": interrupted_run_ids,
                "resume_skipped_law_count": skipped,
                "pending_law_count_at_start": len(pending),
                "base_url": args.base_url,
                "started_at": started_at.isoformat(),
                "completed_at": bootstrap.utcnow().isoformat(),
                "result_status": status,
                "requested_law_count": total,
                "revision_observations_processed_this_run": revisions_seen,
                "failed_law_ids": sorted(failed),
                "failure_messages": failed,
                "unresolved_amendment_reference_rows": unresolved_rows,
                "warning_issue_count": warnings,
                "error_issue_count": errors,
                "database_counts": bootstrap.database_counts(control),
                "bounded_run_cap": args.max_laws,
                "raw_dir": str(args.raw_dir) if args.raw_dir else None,
                "openapi_sha256": args.openapi_sha256,
                "input_manifest_sha256": manifest_sha256,
            }
            bootstrap.write_report(args.report, report)
            return 0 if not failed else 2
        except Exception as exc:
            control.rollback()
            bootstrap.finish_run(control, run_id, "failed", 0, 1)
            bootstrap.write_report(
                args.report,
                {
                    "schema_version": "1.0",
                    "run_id": run_id,
                    "parser_version": bootstrap.PARSER_VERSION,
                    "runner": "phase3-resumable-full-bootstrap-1.1",
                    "workers": args.workers,
                    "history_request_interval_seconds": args.history_request_interval,
                    "resume_existing": not args.no_resume_existing,
                    "interrupted_run_ids_closed": interrupted_run_ids,
                    "base_url": args.base_url,
                    "started_at": started_at.isoformat(),
                    "completed_at": bootstrap.utcnow().isoformat(),
                    "result_status": "failed",
                    "fatal_error": f"{type(exc).__name__}: {exc}",
                },
            )
            raise


if __name__ == "__main__":
    raise SystemExit(main())
