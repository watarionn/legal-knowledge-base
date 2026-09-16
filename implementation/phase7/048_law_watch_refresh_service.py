from __future__ import annotations

from datetime import date, datetime, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
PHASE3_DIR = HERE.parent / "phase3"
WORKSPACE_ID = "local"
REFRESH_LOCK_KEY = 7606004


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PHASE3 = _load("legal_kb_phase76d_phase3", PHASE3_DIR / "004_bootstrap_import.py")
WATCH = _load("legal_kb_phase76d_watch", HERE / "038_law_watch_service.py")
CONTENT = _load("legal_kb_phase76d_content", HERE / "053_law_watch_content_refresh.py")


class WatchStateNotConfiguredError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_refresh_run_id() -> str:
    now = utcnow()
    return f"api-v2-watch-refresh-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def enabled_watch_law_ids(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT law_id
            FROM legal_kb.application_law_watch
            WHERE workspace_id = %s AND enabled = true
            ORDER BY law_id
        """, (WORKSPACE_ID,))
        return [str(row[0]) for row in cur.fetchall()]


def try_refresh_lock(conn: Any) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (REFRESH_LOCK_KEY,))
        row = cur.fetchone()
    return bool(row and row[0])


def release_refresh_lock(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (REFRESH_LOCK_KEY,))


def _phase3_args(
    raw_dir: Path,
    *,
    base_url: str,
    timeout: float,
    max_retries: int,
    retry_base_seconds: float,
) -> Any:
    return SimpleNamespace(
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_base_seconds=retry_base_seconds,
        raw_dir=raw_dir,
    )


def _refresh_report(
    *,
    run_id: str | None,
    status: str,
    law_ids: list[str],
    revision_observations: int = 0,
    failed: dict[str, str] | None = None,
) -> dict[str, Any]:
    failed = failed or {}
    return {
        "refresh_status": status,
        "ingestion_run_id": run_id,
        "requested_law_count": len(law_ids),
        "law_ids": law_ids,
        "revision_observations_processed": revision_observations,
        "failed_law_ids": sorted(failed),
        "failure_messages": failed,
    }


def refresh_watched_laws_conn(
    conn: Any,
    raw_dir: Path,
    *,
    importer: Any = PHASE3,
    content_refresher: Any = CONTENT,
    jsonb_type: Any | None = None,
    base_url: str = PHASE3.BASE_URL,
    timeout: float = 60.0,
    max_retries: int = 5,
    retry_base_seconds: float = 1.0,
) -> dict[str, Any]:
    if not isinstance(raw_dir, Path):
        raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    importer.assert_schema(conn)
    law_ids = enabled_watch_law_ids(conn)
    if not law_ids:
        return _refresh_report(run_id=None, status="no-watches", law_ids=[])
    if not try_refresh_lock(conn):
        return _refresh_report(run_id=None, status="busy", law_ids=law_ids)

    run_id: str | None = None
    failed: dict[str, str] = {}
    revisions_seen = 0
    content_documents_imported = 0
    content_api_fetches = 0
    content_chunks_generated = 0
    args = _phase3_args(
        raw_dir, base_url=base_url, timeout=timeout,
        max_retries=max_retries, retry_base_seconds=retry_base_seconds,
    )
    try:
        if jsonb_type is None:
            from psycopg.types.json import Jsonb as jsonb_type  # type: ignore
        run_id = make_refresh_run_id()
        importer.insert_run(conn, run_id, None)
        for law_id in law_ids:
            try:
                revision_count = importer.import_revisions(
                    args, conn, run_id, law_id, jsonb_type,
                )
                content = content_refresher.refresh_missing_watch_content(
                    conn, law_id=law_id, run_id=run_id, raw_dir=raw_dir,
                    base_url=base_url, timeout=timeout,
                    max_retries=max_retries, retry_base_seconds=retry_base_seconds,
                )
                revisions_seen += revision_count
                content_documents_imported += int(content.get("imported_document_count", 0))
                content_api_fetches += int(content.get("api_fetch_count", 0))
                content_chunks_generated += int(content.get("chunk_count_generated", 0))
            except Exception as exc:
                conn.rollback()
                failed[law_id] = type(exc).__name__

        for law_id in list(failed):
            time.sleep(max(retry_base_seconds, 1.0))
            try:
                revision_count = importer.import_revisions(
                    args, conn, run_id, law_id, jsonb_type,
                )
                content = content_refresher.refresh_missing_watch_content(
                    conn, law_id=law_id, run_id=run_id, raw_dir=raw_dir,
                    base_url=base_url, timeout=timeout,
                    max_retries=max_retries, retry_base_seconds=retry_base_seconds,
                )
                revisions_seen += revision_count
                content_documents_imported += int(content.get("imported_document_count", 0))
                content_api_fetches += int(content.get("api_fetch_count", 0))
                content_chunks_generated += int(content.get("chunk_count_generated", 0))
                failed.pop(law_id, None)
            except Exception as exc:
                conn.rollback()
                failed[law_id] = type(exc).__name__

        manifest_sha256 = importer.run_manifest_hash(conn, run_id)
        warnings, errors = importer.issue_counts(conn, run_id)
        status = "partial" if failed else "succeeded"
        importer.finish_run(conn, run_id, status, warnings, errors + len(failed))
        report = _refresh_report(
            run_id=run_id,
            status=status,
            law_ids=law_ids,
            revision_observations=revisions_seen,
            failed=failed,
        )
        report.update({
            "input_manifest_sha256": manifest_sha256,
            "content_documents_imported": content_documents_imported,
            "content_api_fetch_count": content_api_fetches,
            "content_chunks_generated": content_chunks_generated,
            "warning_issue_count": warnings,
            "error_issue_count": errors,
            "raw_dir_recorded": False,
            "source_truth": "phase3-egov-api-v2",
        })
        return report
    except Exception as exc:
        conn.rollback()
        if run_id is not None:
            try:
                importer.finish_run(conn, run_id, "failed", 0, 1)
            except Exception:
                conn.rollback()
        report = _refresh_report(
            run_id=run_id, status="failed", law_ids=law_ids,
        )
        report["fatal_error"] = type(exc).__name__
        report["source_truth"] = "phase3-egov-api-v2"
        return report
    finally:
        try:
            release_refresh_lock(conn)
        except Exception:
            conn.rollback()


def run_refresh_cycle(
    database_url: str,
    raw_dir: Path,
    *,
    evaluation_date: date | None = None,
    connect: Callable[[str], Any] | None = None,
    importer: Any = PHASE3,
    watch: Any = WATCH,
    content_refresher: Any = CONTENT,
    jsonb_type: Any | None = None,
    base_url: str = PHASE3.BASE_URL,
    timeout: float = 60.0,
    max_retries: int = 5,
    retry_base_seconds: float = 1.0,
) -> dict[str, Any]:
    if not database_url:
        raise ValueError("database_url is required")
    if raw_dir is None:
        raise ValueError("raw_dir is required")
    if evaluation_date is None:
        evaluation_date = date.today()
    if connect is None:
        import psycopg  # type: ignore
        connect = psycopg.connect

    with connect(database_url) as refresh_conn:
        if not watch.watch_state_ready(refresh_conn):
            raise WatchStateNotConfiguredError(
                "Phase 7-6 law watch schema is not configured"
            )
        refresh = refresh_watched_laws_conn(
            refresh_conn, Path(raw_dir), importer=importer,
            content_refresher=content_refresher,
            jsonb_type=jsonb_type, base_url=base_url, timeout=timeout,
            max_retries=max_retries, retry_base_seconds=retry_base_seconds,
        )
    result = {
        "api_version": "1",
        "evaluation_date": evaluation_date.isoformat(),
        "refresh": refresh,
        "evaluated": False,
        "evaluation_results": [],
    }
    if refresh["refresh_status"] != "succeeded":
        result["evaluation_skipped_reason"] = f"refresh-{refresh['refresh_status']}"
        return result

    with connect(database_url) as evaluation_conn:
        if not watch.watch_state_ready(evaluation_conn):
            raise RuntimeError("Phase 7-6 law watch schema is not configured")
        evaluation_results = watch.evaluate_all_watches(
            evaluation_conn, evaluation_date=evaluation_date,
        )
    result["evaluated"] = True
    result["evaluation_results"] = evaluation_results
    result["evaluation_result_count"] = len(evaluation_results)
    result["source_truth"] = "phase3-phase5"
    return result
