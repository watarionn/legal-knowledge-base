from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import re
import unicodedata
from typing import Any, Iterable

BUILDER_VERSION = "phase5-search-builder-0.1"
INDEX_VERSION = "phase5-search-unit-v1"
NORMALIZATION_VERSION = "phase5-search-normalization-v1"
UNIT_SEPARATOR = "\x1f"

ANCHOR_TAGS = frozenset({
    "Part", "Chapter", "Section", "Subsection", "Division", "Article",
    "Paragraph", "Item", "Subitem1", "Subitem2", "Subitem3", "Subitem4",
    "Subitem5", "Subitem6", "Subitem7", "Subitem8", "Subitem9", "Subitem10",
    "SupplProvision", "Appdx", "AppdxTable", "AppdxNote", "AppdxStyle",
    "AppdxFig", "AppdxFormat",
})
CONTEXT_TAGS = ANCHOR_TAGS
DIRECT_TEXT_TAGS = frozenset({
    "EnactStatement", "LawTitle", "Preamble", "TOCLabel", "SupplProvisionLabel",
    "AppdxTitle", "AppdxTableTitle", "AppdxNoteTitle", "AppdxStyleTitle",
    "AppdxFigTitle", "AppdxFormatTitle", "TableStructTitle", "FigStructTitle",
    "StyleStructTitle", "FormatStructTitle", "NoteStructTitle",
})
_WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)


@dataclass(frozen=True)
class SearchUnit:
    search_unit_id: str
    law_id: str
    law_revision_id: str
    document_pk: int
    source_document_order: int
    anchor_document_order: int
    unit_kind: str
    anchor_tag_name: str | None
    anchor_structural_num: str | None
    anchor_display_label: str | None
    hierarchy_jsonb: list[dict[str, Any]]
    search_text_cache: str
    search_text_normalized: str
    context_text_cache: str
    context_text_normalized: str
    source_xml_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BuildDocumentResult:
    units: tuple[SearchUnit, ...]
    searchable_sentence_count: int
    covered_sentence_count: int
    uncovered_sentence_orders: tuple[int, ...]

    @property
    def uncovered_sentence_count(self) -> int:
        return len(self.uncovered_sentence_orders)


def normalize_search_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    return _WHITESPACE_RE.sub("", value)


def _digest(*parts: str) -> str:
    return sha256(UNIT_SEPARATOR.join(parts).encode("utf-8")).hexdigest()


def _node_map(nodes: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for raw in nodes:
        row = dict(raw)
        order = int(row["document_order"])
        if order in result:
            raise ValueError(f"duplicate document_order: {order}")
        result[order] = row
    return result


def reconstruct_string_values(nodes: Iterable[dict[str, Any]]) -> dict[int, str]:
    by_order = _node_map(nodes)
    values: dict[int, str] = {}
    for order in sorted(by_order, reverse=True):
        node = by_order[order]
        if node.get("node_kind") != "element":
            values[order] = node.get("text_original") or ""
            continue
        mixed = node.get("mixed_content_jsonb") or []
        if isinstance(mixed, str):
            mixed = json.loads(mixed)
        if not mixed:
            values[order] = node.get("text_original") or ""
            continue
        pieces: list[str] = []
        for segment in mixed:
            kind = segment.get("kind")
            if kind in {"text", "tail"}:
                pieces.append(segment.get("value") or "")
            elif kind == "child":
                child_order = int(segment["document_order"])
                child = by_order.get(child_order)
                if child is not None and child.get("node_kind") == "element":
                    pieces.append(values.get(child_order, ""))
        values[order] = "".join(pieces)
    return values


def _ancestor_orders(order: int, by_order: dict[int, dict[str, Any]]) -> list[int]:
    chain: list[int] = []
    seen: set[int] = set()
    current = by_order[order].get("parent_document_order")
    while current is not None:
        current = int(current)
        if current in seen:
            raise ValueError(f"parent cycle at document_order={order}")
        seen.add(current)
        if current not in by_order:
            raise ValueError(f"missing parent {current} for document_order={order}")
        chain.append(current)
        current = by_order[current].get("parent_document_order")
    return chain


def _nearest_anchor(order: int, by_order: dict[int, dict[str, Any]]) -> int:
    node = by_order[order]
    if node.get("tag_name") in ANCHOR_TAGS:
        return order
    for ancestor in _ancestor_orders(order, by_order):
        if by_order[ancestor].get("tag_name") in ANCHOR_TAGS:
            return ancestor
    parent = node.get("parent_document_order")
    return int(parent) if parent is not None else order


def _nearest_table_row(order: int, by_order: dict[int, dict[str, Any]]) -> int | None:
    if by_order[order].get("tag_name") == "TableRow":
        return order
    for ancestor in _ancestor_orders(order, by_order):
        if by_order[ancestor].get("tag_name") == "TableRow":
            return ancestor
    return None


def _hierarchy(order: int, by_order: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    chain = list(reversed(_ancestor_orders(order, by_order))) + [order]
    result: list[dict[str, Any]] = []
    for current in chain:
        node = by_order[current]
        tag = node.get("tag_name")
        if tag not in CONTEXT_TAGS:
            continue
        result.append({
            "document_order": current,
            "tag_name": tag,
            "structural_num": node.get("structural_num"),
            "display_label": node.get("display_label"),
        })
    return result


def _context_text(law_title: str | None, hierarchy: list[dict[str, Any]]) -> str:
    pieces: list[str] = []
    if law_title:
        pieces.append(law_title)
    for item in hierarchy:
        for key in ("display_label", "structural_num"):
            value = item.get(key)
            if value and value not in pieces:
                pieces.append(str(value))
    return " ".join(pieces)


def _make_unit(
    *,
    law_id: str,
    law_revision_id: str,
    document_pk: int,
    document_id: str,
    source_xml_sha256: str,
    source_order: int,
    anchor_order: int,
    unit_kind: str,
    search_text: str,
    law_title: str | None,
    by_order: dict[int, dict[str, Any]],
) -> SearchUnit:
    hierarchy = _hierarchy(anchor_order, by_order)
    context = _context_text(law_title, hierarchy)
    anchor = by_order[anchor_order]
    source_node_id = by_order[source_order].get("node_id")
    if isinstance(source_node_id, memoryview):
        source_node_id = bytes(source_node_id)
    if isinstance(source_node_id, (bytes, bytearray)):
        source_identity = bytes(source_node_id).hex()
    else:
        source_identity = str(source_node_id or source_order)
    unit_id = _digest(document_id, unit_kind, source_identity)
    normalized = normalize_search_text(search_text)
    if not normalized:
        raise ValueError("cannot create empty search unit")
    return SearchUnit(
        search_unit_id=unit_id,
        law_id=law_id,
        law_revision_id=law_revision_id,
        document_pk=document_pk,
        source_document_order=source_order,
        anchor_document_order=anchor_order,
        unit_kind=unit_kind,
        anchor_tag_name=anchor.get("tag_name"),
        anchor_structural_num=anchor.get("structural_num"),
        anchor_display_label=anchor.get("display_label"),
        hierarchy_jsonb=hierarchy,
        search_text_cache=search_text,
        search_text_normalized=normalized,
        context_text_cache=context,
        context_text_normalized=normalize_search_text(context),
        source_xml_sha256=source_xml_sha256,
    )


def build_search_units(
    nodes: Iterable[dict[str, Any]],
    *,
    law_id: str,
    law_revision_id: str,
    document_pk: int,
    document_id: str,
    source_xml_sha256: str,
    law_title: str | None,
) -> BuildDocumentResult:
    by_order = _node_map(nodes)
    values = reconstruct_string_values(by_order.values())
    searchable_sentences = {
        order for order, node in by_order.items()
        if node.get("node_kind") == "element"
        and node.get("tag_name") == "Sentence"
        and normalize_search_text(values.get(order, ""))
    }
    covered: set[int] = set()
    units: list[SearchUnit] = []
    table_rows_with_text: set[int] = set()

    for sentence_order in sorted(searchable_sentences):
        table_row = _nearest_table_row(sentence_order, by_order)
        if table_row is not None:
            table_rows_with_text.add(table_row)
            covered.add(sentence_order)
            continue
        anchor = _nearest_anchor(sentence_order, by_order)
        units.append(_make_unit(
            law_id=law_id, law_revision_id=law_revision_id, document_pk=document_pk,
            document_id=document_id, source_xml_sha256=source_xml_sha256,
            source_order=sentence_order, anchor_order=anchor, unit_kind="sentence",
            search_text=values[sentence_order], law_title=law_title, by_order=by_order,
        ))
        covered.add(sentence_order)

    for row_order in sorted(table_rows_with_text):
        row_text = values.get(row_order, "")
        if not normalize_search_text(row_text):
            continue
        units.append(_make_unit(
            law_id=law_id, law_revision_id=law_revision_id, document_pk=document_pk,
            document_id=document_id, source_xml_sha256=source_xml_sha256,
            source_order=row_order, anchor_order=row_order, unit_kind="table-row",
            search_text=row_text, law_title=law_title, by_order=by_order,
        ))

    descendant_sentence_count: dict[int, int] = {order: 0 for order in by_order}
    children: dict[int, list[int]] = {order: [] for order in by_order}
    for order, node in by_order.items():
        parent = node.get("parent_document_order")
        if parent is not None and int(parent) in children:
            children[int(parent)].append(order)
    for order in sorted(by_order, reverse=True):
        count = 1 if order in searchable_sentences else 0
        count += sum(descendant_sentence_count[child] for child in children.get(order, []))
        descendant_sentence_count[order] = count

    used_sources = {(u.unit_kind, u.source_document_order) for u in units}
    for order in sorted(by_order):
        node = by_order[order]
        if node.get("node_kind") != "element" or node.get("tag_name") not in DIRECT_TEXT_TAGS:
            continue
        if descendant_sentence_count.get(order, 0) != 0:
            continue
        text = values.get(order, "")
        if not normalize_search_text(text):
            continue
        key = ("direct-text", order)
        if key in used_sources:
            continue
        units.append(_make_unit(
            law_id=law_id, law_revision_id=law_revision_id, document_pk=document_pk,
            document_id=document_id, source_xml_sha256=source_xml_sha256,
            source_order=order, anchor_order=order, unit_kind="direct-text",
            search_text=text, law_title=law_title, by_order=by_order,
        ))
        used_sources.add(key)

    uncovered = tuple(sorted(searchable_sentences - covered))
    return BuildDocumentResult(
        units=tuple(units),
        searchable_sentence_count=len(searchable_sentences),
        covered_sentence_count=len(covered),
        uncovered_sentence_orders=uncovered,
    )
