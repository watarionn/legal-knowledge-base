from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

PHASE4_DIR = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SMOKE = _load(
    "legal_kb_phase4_postgres_smoke", PHASE4_DIR / "010_postgres_import_smoke.py"
)


def run(database_url: str) -> dict:
    original = SMOKE.PG_IMPORT.insert_parsed_document

    def copy_insert(conn, parsed, **kwargs):
        kwargs["method"] = "copy"
        return original(conn, parsed, **kwargs)

    SMOKE.PG_IMPORT.insert_parsed_document = copy_insert
    try:
        result = SMOKE.run(database_url)
    finally:
        SMOKE.PG_IMPORT.insert_parsed_document = original

    result = dict(result)
    result["runner"] = "013_copy_import_smoke.py"
    result["postgres_insert_method"] = "copy"
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--result", type=Path)
    args = ap.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    result = run(args.database_url)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.result:
        args.result.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
