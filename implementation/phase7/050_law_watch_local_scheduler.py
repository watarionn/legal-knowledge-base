from __future__ import annotations

import argparse
from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent


def _load_refresh():
    path = HERE / "048_law_watch_refresh_service.py"
    spec = importlib.util.spec_from_file_location("legal_kb_phase76d_scheduler_refresh", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


REFRESH = _load_refresh()
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60
MIN_INTERVAL_SECONDS = 60 * 60


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Local Phase 7-6d watched-law refresh scheduler")
    parser.add_argument("--database-url", default=os.environ.get("LEGAL_KB_DATABASE_URL"))
    parser.add_argument("--raw-dir", type=Path, default=os.environ.get("LEGAL_KB_WATCH_RAW_DIR"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--interval-seconds", type=int,
        default=int(os.environ.get("LEGAL_KB_WATCH_REFRESH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)),
    )
    parser.add_argument("--evaluation-date", type=parse_date)
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("--database-url or LEGAL_KB_DATABASE_URL is required")
    if args.raw_dir is None:
        parser.error("--raw-dir or LEGAL_KB_WATCH_RAW_DIR is required")
    if not args.once and args.interval_seconds < MIN_INTERVAL_SECONDS:
        parser.error("--interval-seconds must be at least 3600")
    return args


def run_once(args) -> dict:
    return REFRESH.run_refresh_cycle(
        args.database_url,
        Path(args.raw_dir),
        evaluation_date=args.evaluation_date,
    )


def exit_code(result: dict) -> int:
    status = result.get("refresh", {}).get("refresh_status")
    if status in {"succeeded", "no-watches"}:
        return 0
    if status == "busy":
        return 3
    return 2


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.once:
        result = run_once(args)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return exit_code(result)

    while True:
        try:
            result = run_once(args)
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
        except Exception as exc:
            print(json.dumps({"scheduler_error": type(exc).__name__}), flush=True)
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
