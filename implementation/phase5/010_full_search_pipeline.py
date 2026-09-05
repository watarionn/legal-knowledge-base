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
REPO_ROOT = PHASE5_DIR.parent.parent
PHASE3_DIR = REPO_ROOT / "implementation" / "phase3"
PHASE4_DIR = REPO_ROOT / "implementation" / "phase4"
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "validation" / "xml_snapshot_manifest.public.json"
DDL_FILES = (
    PHASE3_DIR / "001_law_history_schema.sql",
    PHASE4_DIR / "001_xml_structure_schema.sql",
    PHASE5_DIR / "001_temporal_resolution_schema.sql",
    PHASE5_DIR / "006_lexical_structural_search_schema.sql",
)
ARCHIVE_NAMES = tuple(f"all_xml_{i:02d}.zip" for i in range(1, 5))
RUNNER_VERSION = "phase5-full-search-pipeline-0.1"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_archive_dir(archive_dir: Path) -> list[Path]:
    paths = [archive_dir / name for name in ARCHIVE_NAMES]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing XML archives: " + ", ".join(missing))
    return paths


def build_phase3_args(
    database_url: str,
    raw_dir: Path,
    report_path: Path,
    workers: int,
    history_request_interval: float,
) -> list[str]:
    return [
        "--dsn", database_url,
        "--raw-dir", str(raw_dir),
        "--report", str(report_path),
        "--workers", str(workers),
        "--history-request-interval", str(history_request_interval),
        "--progress-every", "100",
    ]


def apply_ddl(database_url: str) -> str:
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW server_version_num")
            version_num = int(cur.fetchone()[0])
            if version_num < 160000:
                raise RuntimeError(f"PostgreSQL 16+ required; server_version_num={version_num}")
            cur.execute("SELECT version()")
            version = str(cur.fetchone()[0])
        for path in DDL_FILES:
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
    return version


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_pipeline(
    *,
    archive_dir: Path,
    database_url: str,
    work_dir: Path,
    workers: int,
    history_request_interval: float,
    benchmark_repeats: int,
    skip_ddl: bool,
    skip_phase3: bool,
    skip_phase4: bool,
) -> dict[str, Any]:
    if workers < 1 or workers > 8:
        raise ValueError("workers must be between 1 and 8")
    if history_request_interval < 0:
        raise ValueError("history_request_interval must be >= 0")
    if benchmark_repeats < 1:
        raise ValueError("benchmark_repeats must be >= 1")

    validate_archive_dir(archive_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = work_dir / "phase3-raw"
    phase3_report = work_dir / "phase3-full.json"
    phase4_report = work_dir / "phase4-full-relational-import.json"
    phase5_report = work_dir / "phase5-full-search-benchmark.json"
    pipeline_report = work_dir / "phase5-full-search-pipeline.json"

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "runner": "010_full_search_pipeline.py",
        "runner_version": RUNNER_VERSION,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "archive_dir": str(archive_dir),
        "manifest": str(DEFAULT_MANIFEST),
        "archive_names": list(ARCHIVE_NAMES),
        "database_url_recorded": False,
        "work_dir": str(work_dir),
        "steps": {},
    }

    try:
        if skip_ddl:
            result["steps"]["ddl"] = {"status": "skipped"}
        else:
            version = apply_ddl(database_url)
            result["steps"]["ddl"] = {"status": "succeeded", "postgres_version": version}

        if skip_phase3:
            result["steps"]["phase3"] = {"status": "skipped"}
        else:
            phase3 = _load("legal_kb_phase3_full_bootstrap", PHASE3_DIR / "007_parallel_full_bootstrap.py")
            rc = int(phase3.main(build_phase3_args(
                database_url, raw_dir, phase3_report, workers, history_request_interval
            )))
            if rc != 0:
                raise RuntimeError(f"Phase 3 bootstrap returned {rc}")
            phase3_data = json.loads(phase3_report.read_text(encoding="utf-8"))
            result["steps"]["phase3"] = {
                "status": phase3_data.get("result_status"),
                "report": str(phase3_report),
                "database_counts": phase3_data.get("database_counts"),
                "resume_skipped_law_count": phase3_data.get("resume_skipped_law_count"),
            }

        if skip_phase4:
            result["steps"]["phase4"] = {"status": "skipped"}
        else:
            phase4 = _load("legal_kb_phase4_full_import", PHASE4_DIR / "011_full_relational_import.py")
            run_id = "phase4-full-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            phase4_data = phase4.run(
                archive_dir=archive_dir,
                manifest_path=DEFAULT_MANIFEST,
                database_url=database_url,
                result_path=phase4_report,
                run_id=run_id,
                batch_size=25000,
                progress_every=100,
                preflight_only=False,
                max_documents=None,
                fail_fast=False,
            )
            if int(phase4_data.get("failed_document_count", 0)) != 0:
                raise RuntimeError("Phase 4 full import reported failed documents")
            result["steps"]["phase4"] = {
                "status": phase4_data.get("status"),
                "report": str(phase4_report),
                "inserted_document_count": phase4_data.get("inserted_document_count"),
                "skipped_existing_document_count": phase4_data.get("skipped_existing_document_count"),
                "deferred_unreconciled_document_count": phase4_data.get("deferred_unreconciled_document_count"),
                "inserted_node_count": phase4_data.get("inserted_node_count"),
            }

        phase5 = _load("legal_kb_phase5_full_benchmark", PHASE5_DIR / "008_full_search_benchmark.py")
        phase5_data = phase5.run(database_url, tuple(phase5.DEFAULT_QUERIES), benchmark_repeats)
        write_json(phase5_report, phase5_data)
        result["steps"]["phase5_benchmark"] = {
            "status": "succeeded",
            "report": str(phase5_report),
            "counts_after": phase5_data.get("counts_after"),
            "rebuild": phase5_data.get("rebuild"),
            "storage_after": phase5_data.get("storage_after"),
        }
        result["status"] = "succeeded"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        write_json(pipeline_report, result)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 3 -> Phase 4 -> Phase 5.2 full search benchmark")
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--database-url", default=os.environ.get("LEGAL_KB_DSN") or os.environ.get("DATABASE_URL"))
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--history-request-interval", type=float, default=0.6)
    parser.add_argument("--benchmark-repeats", type=int, default=5)
    parser.add_argument("--skip-ddl", action="store_true")
    parser.add_argument("--skip-phase3", action="store_true")
    parser.add_argument("--skip-phase4", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("LEGAL_KB_DSN, DATABASE_URL, or --database-url is required")

    result = run_pipeline(
        archive_dir=args.archive_dir,
        database_url=args.database_url,
        work_dir=args.work_dir,
        workers=args.workers,
        history_request_interval=args.history_request_interval,
        benchmark_repeats=args.benchmark_repeats,
        skip_ddl=args.skip_ddl,
        skip_phase3=args.skip_phase3,
        skip_phase4=args.skip_phase4,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
