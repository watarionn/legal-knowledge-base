from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

PHASE5_DIR = Path(__file__).resolve().parent
BASE_PATH = PHASE5_DIR / "010_full_search_pipeline.py"
HARDENING_DDL = PHASE5_DIR / "012_search_literal_hardening.sql"
BENCHMARK_V2 = PHASE5_DIR / "013_full_search_benchmark_v2.py"
RUNNER_VERSION = "phase5-full-search-pipeline-0.2"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load("legal_kb_phase5_full_search_pipeline_base", BASE_PATH)
ORIGINAL_LOAD = BASE._load
BASE.DDL_FILES = (*BASE.DDL_FILES, HARDENING_DDL)
BASE.RUNNER_VERSION = RUNNER_VERSION


def _patched_load(name: str, path: Path):
    if path.name == "008_full_search_benchmark.py":
        return _load("legal_kb_phase5_full_search_benchmark_v2", BENCHMARK_V2)
    return ORIGINAL_LOAD(name, path)


BASE._load = _patched_load


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run hardened Phase 3 -> Phase 4 -> Phase 5.2 full search benchmark"
    )
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("LEGAL_KB_DSN") or os.environ.get("DATABASE_URL"),
    )
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

    result = BASE.run_pipeline(
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

    result["runner"] = "015_full_search_pipeline_hardened.py"
    result["runner_version"] = RUNNER_VERSION
    result["search_literal_hardening_ddl"] = HARDENING_DDL.name
    result["benchmark_runner"] = BENCHMARK_V2.name
    BASE.write_json(args.work_dir / "phase5-full-search-pipeline.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
