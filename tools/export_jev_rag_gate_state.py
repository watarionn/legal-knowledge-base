#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1] / "implementation" / "phase7"
TARGET = HERE / "057_jev_rag_gate_export.py"
spec = importlib.util.spec_from_file_location("jev_rag_gate_export", TARGET)
assert spec is not None and spec.loader is not None
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    response = json.loads(args.input.read_text(encoding="utf-8-sig"))
    export = MODULE.build_shadow_export(response)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(export, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "contract": export["contract"],
        "mode": export["mode"],
        "evidence_count": len(export["evidence"]),
        "answer_content_exported": export["answer_content_exported"],
        "authority": export["authority"],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
