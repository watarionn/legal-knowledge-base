from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
SERVICE_PATH = HERE / "017_article_compare_service.py"
spec = importlib.util.spec_from_file_location("phase73_snapshot_service", SERVICE_PATH)
assert spec and spec.loader
SERVICE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = SERVICE
spec.loader.exec_module(SERVICE)


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    args = parser.parse_args()

    started = time.perf_counter()
    left_rows = load_jsonl(args.left)
    right_rows = load_jsonl(args.right)
    left = SERVICE.build_article_index(left_rows)
    right = SERVICE.build_article_index(right_rows)
    summary = SERVICE.compare_article_indexes(left, right)
    detail = SERVICE._specific_article("891", left, right, "main")
    ambiguous = SERVICE._specific_article("1", left, right, None)

    require(left["duplicate_article_keys"] == {}, "left duplicate scope keys remain")
    require(right["duplicate_article_keys"] == {}, "right duplicate scope keys remain")
    require(left["missing_article_scope_count"] == 0, "left article scope missing")
    require(right["missing_article_scope_count"] == 0, "right article scope missing")
    require(detail["status"] == "changed", "main article 891 was not changed")
    require(bool(detail["diff_segments"]), "article 891 diff is empty")
    require(ambiguous["status"] == "ambiguous", "article 1 was guessed without scope")
    require(len(ambiguous["candidates"]) > 1, "ambiguous candidates missing")

    report = {
        "status": "passed",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "left_node_count": len(left_rows),
        "right_node_count": len(right_rows),
        "left_article_count": left["article_count"],
        "right_article_count": right["article_count"],
        "left_duplicate_scope_keys": len(left["duplicate_article_keys"]),
        "right_duplicate_scope_keys": len(right["duplicate_article_keys"]),
        "left_missing_scope_count": left["missing_article_scope_count"],
        "right_missing_scope_count": right["missing_article_scope_count"],
        "counts": summary["counts"],
        "changed_article_count": summary["changed_article_count"],
        "warnings": summary["warnings"],
        "article_891_status": detail["status"],
        "article_891_diff_segment_count": len(detail["diff_segments"]),
        "article_1_without_scope_status": ambiguous["status"],
        "article_1_candidate_count": len(ambiguous["candidates"]),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
