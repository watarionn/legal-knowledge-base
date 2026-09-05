from __future__ import annotations

from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


fullbuild = load("phase5_full_search_build_smoke", "010_full_search_index_build.py")
service = load("phase5_search_service_smoke", "011_search_service.py")

TARGET_REVISION = "428AC1000000067_20160603_000000000000000"
OTHER_REVISION = "503AC0000000004_20210203_000000000000000"
QUERY = "熊本地震災害関連義援金"


def main():
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg 3 is required") from exc
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")
    with psycopg.connect(dsn) as conn:
        build = fullbuild.run(
            conn, build_id="phase5-2-postgres-smoke", resume=False,
            limit=None, start_document_pk=None, progress_every=0,
        )
        hits = service.search_revision(conn, TARGET_REVISION, QUERY, limit=20)
        paragraph_one = service.search_revision(
            conn, TARGET_REVISION, QUERY, limit=20,
            anchor_tag_name="Paragraph", structural_num="1",
        )
        isolated = service.search_revision(conn, OTHER_REVISION, QUERY, limit=20)
        context_hits = service.search_revision(conn, TARGET_REVISION, "差押禁止", limit=20)
        ambiguous = service.search_as_of(
            conn, "900AC0000000002", date(2022, 6, 1), QUERY, limit=5
        )

        checks = {
            "build_passed": build["status"] == "passed",
            "zero_uncovered_sentence": build["uncovered_sentence_count"] == 0,
            "japanese_body_search_returns_hits": bool(hits),
            "revision_isolation": len(isolated) == 0,
            "paragraph_structural_filter": bool(paragraph_one) and all(
                h.anchor_tag_name == "Paragraph" and h.anchor_structural_num == "1"
                for h in paragraph_one
            ),
            "source_sha_backlink": bool(hits) and all(len(h.source_xml_sha256) == 64 for h in hits),
            "xml_path_backlink": bool(hits) and all(h.reconstructed_xml_path.startswith("/") for h in hits),
            "citation_reconstructed_from_phase4": bool(hits) and "熊本地震災害関連義援金" in hits[0].citation_text,
            "context_search_available": bool(context_hits),
            "ambiguous_as_of_blocks_search": ambiguous.status == "not-searchable" and len(ambiguous.hits) == 0,
        }
        status = "passed" if all(checks.values()) else "failed"
        result = {
            "schema_version": "1.0",
            "evidence_type": "phase5-lexical-structural-search-smoke",
            "postgresql_target": "16",
            "status": status,
            "checks": checks,
            "build": build,
            "examples": {
                "body_hit": hits[0].__dict__ if hits else None,
                "paragraph_one_hit_count": len(paragraph_one),
                "other_revision_hit_count": len(isolated),
                "context_hit_count": len(context_hits),
                "ambiguous_as_of": ambiguous.to_dict(),
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if status != "passed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
