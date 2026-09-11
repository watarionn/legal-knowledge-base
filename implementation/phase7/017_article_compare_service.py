from __future__ import annotations

from datetime import date
from difflib import SequenceMatcher
from hashlib import sha256
import importlib.util
from pathlib import Path
import re
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
PHASE5_DIR = HERE.parent / "phase5"
LAW_ID_RE = re.compile(r"^[0-9A-Z]{15}$")
ARTICLE_NUM_RE = re.compile(r"^[0-9]+(?:_[0-9]+)*(?::[0-9]+(?:_[0-9]+)*)?$")
SCOPE_KEY_MAX_LENGTH = 300
MAX_CHANGE_ITEMS = 500


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TEMPORAL = _load(
    "legal_kb_phase7_compare_temporal",
    PHASE5_DIR / "003_temporal_resolver.py",
)


def parse_article_num(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("article_num must be a string")
    value = value.strip()
    if not ARTICLE_NUM_RE.fullmatch(value):
        raise ValueError("article_num must use e-Gov Num format such as 90, 398_2, or 155:157")
    return value



def parse_scope_key(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("scope_key must be a string")
    value = value.strip()
    if len(value) > SCOPE_KEY_MAX_LENGTH or "\x1f" in value or any(ord(ch) < 32 for ch in value):
        raise ValueError("scope_key is invalid")
    if value == "main" or value.startswith("supplementary:") and len(value) > len("supplementary:"):
        return value
    raise ValueError("scope_key is invalid")


def _fetch_document_nodes(conn: Any, document_pk: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT document_order, parent_document_order, node_kind,
                   tag_name, structural_num, display_label, attributes_jsonb,
                   text_original, mixed_content_jsonb
            FROM legal_kb.provision_node
            WHERE document_pk = %s
            ORDER BY document_order
            """,
            (document_pk,),
        )
        names = [column.name for column in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def _render_node(
    document_order: int,
    nodes: dict[int, dict[str, Any]],
    cache: dict[int, str],
) -> str:
    if document_order in cache:
        return cache[document_order]
    row = nodes[document_order]
    if row.get("node_kind") != "element":
        cache[document_order] = ""
        return ""

    segments = row.get("mixed_content_jsonb") or []
    if not segments:
        text = row.get("text_original") or ""
        cache[document_order] = text
        return text

    parts: list[str] = []
    for segment in segments:
        kind = segment.get("kind")
        if kind in {"text", "tail"}:
            parts.append(segment.get("value") or "")
        elif kind == "child":
            child_order = int(segment["document_order"])
            if child_order in nodes:
                parts.append(_render_node(child_order, nodes, cache))
    text = "".join(parts)
    cache[document_order] = text
    return text


def _article_scope(row: dict[str, Any], nodes: dict[int, dict[str, Any]]) -> tuple[str | None, str | None]:
    parent_order = row.get("parent_document_order")
    while parent_order is not None:
        parent = nodes.get(int(parent_order))
        if parent is None:
            break
        tag = parent.get("tag_name")
        if tag == "MainProvision":
            return "main", "本則"
        if tag == "SupplProvision":
            attrs = parent.get("attributes_jsonb") or {}
            amend_law_num = attrs.get("AmendLawNum")
            if amend_law_num:
                return f"supplementary:{amend_law_num}", f"附則 {amend_law_num}"
            return None, None
        parent_order = parent.get("parent_document_order")
    return None, None


def build_article_index(rows: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = {int(row["document_order"]): row for row in rows}
    cache: dict[int, str] = {}
    buckets: dict[str, list[dict[str, Any]]] = {}
    missing_num: list[dict[str, Any]] = []
    missing_scope: list[dict[str, Any]] = []
    for row in rows:
        if row.get("node_kind") != "element" or row.get("tag_name") != "Article":
            continue
        article_num = row.get("structural_num")
        scope_key, scope_label = _article_scope(row, nodes)
        item = {
            "article_num": article_num, "scope_key": scope_key, "scope_label": scope_label,
            "display_label": row.get("display_label"), "document_order": int(row["document_order"]),
            "text": _render_node(int(row["document_order"]), nodes, cache),
        }
        item["text_sha256"] = sha256(item["text"].encode("utf-8")).hexdigest()
        if not article_num:
            missing_num.append(item); continue
        if not scope_key:
            missing_scope.append(item); continue
        buckets.setdefault(f"{scope_key}\x1f{article_num}", []).append(item)

    unique = {key: values[0] for key, values in buckets.items() if len(values) == 1}
    duplicates = {key: len(values) for key, values in buckets.items() if len(values) > 1}
    return {
        "articles": unique,
        "duplicate_article_keys": duplicates,
        "missing_article_num_count": len(missing_num),
        "missing_article_scope_count": len(missing_scope),
        "article_count": len(unique) + sum(duplicates.values()) + len(missing_num) + len(missing_scope),
    }

def _article_sort_key(value: str) -> tuple[Any, ...]:
    scope_key, article_num = value.rsplit("\x1f", 1)
    if ARTICLE_NUM_RE.fullmatch(article_num):
        range_parts = tuple(tuple(int(part) for part in side.split("_")) for side in article_num.split(":"))
        article_sort = (0, range_parts)
    else:
        article_sort = (1, article_num)
    return (0 if scope_key == "main" else 1, scope_key, article_sort)

def diff_segments(left: str, right: str) -> list[dict[str, str]]:
    matcher = SequenceMatcher(a=left, b=right, autojunk=False)
    segments: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        segments.append({
            "op": tag,
            "left": left[i1:i2],
            "right": right[j1:j2],
        })
    return segments


def compare_article_indexes(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_articles, right_articles = left["articles"], right["articles"]
    keys = sorted(set(left_articles) | set(right_articles), key=_article_sort_key)
    changes: list[dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    for key in keys:
        l_item, r_item = left_articles.get(key), right_articles.get(key)
        status = "added" if l_item is None else "removed" if r_item is None else (
            "unchanged" if l_item["text_sha256"] == r_item["text_sha256"] else "changed"
        )
        counts[status] += 1
        if status != "unchanged":
            item = r_item or l_item
            changes.append({"scope_key": item["scope_key"], "scope_label": item["scope_label"],
                            "article_num": item["article_num"], "status": status,
                            "left_label": l_item.get("display_label") if l_item else None,
                            "right_label": r_item.get("display_label") if r_item else None})


    visible = changes[:MAX_CHANGE_ITEMS]
    warnings: list[str] = []
    if len(changes) > MAX_CHANGE_ITEMS:
        warnings.append("ARTICLE_CHANGE_LIST_TRUNCATED")
    if left["duplicate_article_keys"] or right["duplicate_article_keys"]:
        warnings.append("DUPLICATE_ARTICLE_SCOPE_KEY_EXCLUDED")
    if left["missing_article_num_count"] or right["missing_article_num_count"]:
        warnings.append("ARTICLE_WITHOUT_NUM_EXCLUDED")
    if left["missing_article_scope_count"] or right["missing_article_scope_count"]:
        warnings.append("ARTICLE_WITHOUT_SCOPE_EXCLUDED")
    return {
        "counts": counts, "changed_article_count": len(changes), "changes": visible,
        "changes_truncated": len(changes) > len(visible), "warnings": warnings,
        "left_article_count": left["article_count"], "right_article_count": right["article_count"],
        "left_duplicate_article_keys": left["duplicate_article_keys"],
        "right_duplicate_article_keys": right["duplicate_article_keys"],
        "left_missing_article_num_count": left["missing_article_num_count"],
        "right_missing_article_num_count": right["missing_article_num_count"],
        "left_missing_article_scope_count": left["missing_article_scope_count"],
        "right_missing_article_scope_count": right["missing_article_scope_count"],
    }

def _specific_article(article_num: str, left: dict[str, Any], right: dict[str, Any], scope_key: str | None) -> dict[str, Any]:
    if scope_key:
        candidate_keys = [f"{scope_key}\x1f{article_num}"]
    else:
        all_keys = set(left["articles"]) | set(right["articles"]) | set(left["duplicate_article_keys"]) | set(right["duplicate_article_keys"])
        candidate_keys = sorted(
            {key for key in all_keys if key.rsplit("\x1f", 1)[1] == article_num},
            key=_article_sort_key,
        )
    if not candidate_keys:
        return {"status": "not-found", "article_num": article_num, "scope_key": scope_key, "candidates": []}
    if len(candidate_keys) > 1:
        candidates=[]
        for key in candidate_keys:
            item = right["articles"].get(key) or left["articles"].get(key)
            candidate_scope = key.rsplit("\x1f", 1)[0]
            candidates.append({
                "scope_key": candidate_scope,
                "scope_label": item["scope_label"] if item else candidate_scope,
                "article_num": article_num,
            })
        return {"status": "ambiguous", "article_num": article_num, "scope_key": None, "candidates": candidates}
    key=candidate_keys[0]
    if key in left["duplicate_article_keys"] or key in right["duplicate_article_keys"]:
        return {"status": "ambiguous", "article_num": article_num, "scope_key": scope_key, "candidates": []}
    l_item, r_item = left["articles"].get(key), right["articles"].get(key)
    if l_item is None and r_item is None:
        return {"status": "not-found", "article_num": article_num, "scope_key": scope_key, "candidates": []}

    status = "added" if l_item is None else "removed" if r_item is None else (
        "unchanged" if l_item["text_sha256"] == r_item["text_sha256"] else "changed"
    )
    item = r_item or l_item
    detail = {"status": status, "article_num": article_num, "scope_key": item["scope_key"],
              "scope_label": item["scope_label"], "left": l_item, "right": r_item,
              "diff_segments": [], "candidates": []}
    if l_item is not None and r_item is not None:
        detail["diff_segments"] = diff_segments(l_item["text"], r_item["text"])
    return detail

def _side_payload(resolution: Any) -> dict[str, Any]:
    return {
        "as_of_date": resolution.as_of_date.isoformat(),
        "temporal_resolution": resolution.to_dict(),
        "law_revision_id": resolution.selected_revision_id,
        "content_status": resolution.content_status,
        "document_pk": resolution.selected_document_pk,
        "source_xml_sha256": resolution.source_xml_sha256,
    }


def get_article_comparison(
    conn: Any,
    law_id: str,
    *,
    from_date: date,
    to_date: date,
    article_num: str | None = None,
    scope_key: str | None = None,
) -> dict[str, Any]:
    if not LAW_ID_RE.fullmatch(law_id or ""):
        raise ValueError("law_id must be a 15-character e-Gov law ID")
    article_num = parse_article_num(article_num)
    scope_key = parse_scope_key(scope_key)
    left_resolution = TEMPORAL.resolve_as_of(conn, law_id, from_date)
    right_resolution = TEMPORAL.resolve_as_of(conn, law_id, to_date)
    response = {
        "api_version": "1",
        "law_id": law_id,
        "source_truth": "phase3-phase4",
        "from": _side_payload(left_resolution),
        "to": _side_payload(right_resolution),
        "article_num": article_num,
        "scope_key": scope_key,
        "status": None,
        "summary": None,
        "article": None,
        "warnings": [],
    }

    if left_resolution.status != "resolved" or right_resolution.status != "resolved":
        response["status"] = "blocked-temporal"
        return response

    if left_resolution.content_status != "available" or right_resolution.content_status != "available":
        response["status"] = "blocked-content"
        return response

    if left_resolution.selected_revision_id == right_resolution.selected_revision_id:
        response["status"] = "same-revision"
        return response

    left_rows = _fetch_document_nodes(conn, int(left_resolution.selected_document_pk))
    right_rows = _fetch_document_nodes(conn, int(right_resolution.selected_document_pk))
    left_index = build_article_index(left_rows)
    right_index = build_article_index(right_rows)
    summary = compare_article_indexes(left_index, right_index)
    response["summary"] = summary
    response["warnings"].extend(summary["warnings"])

    if article_num is not None:
        response["article"] = _specific_article(article_num, left_index, right_index, scope_key)
        if response["article"]["status"] == "ambiguous":
            response["status"] = "blocked-article-ambiguous"
            return response

    response["status"] = "ok"
    return response
