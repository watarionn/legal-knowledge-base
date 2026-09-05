from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import importlib.util
from pathlib import Path
import re
import sys
from typing import Any

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = _load("phase5_search_builder", "008_search_unit_builder.py")
temporal = _load("phase5_temporal_resolver", "003_temporal_resolver.py")
REVISION_RE = re.compile(r"^[0-9A-Z]{15}_[0-9]{8}_[0-9A-Z]{15}$")


@dataclass(frozen=True)
class SearchHit:
    search_unit_id: str
    law_id: str
    law_revision_id: str
    document_pk: int
    document_id: str
    source_xml_sha256: str
    source_document_order: int
    anchor_document_order: int
    unit_kind: str
    anchor_tag_name: str | None
    anchor_structural_num: str | None
    anchor_display_label: str | None
    hierarchy: list[dict[str, Any]]
    reconstructed_xml_path: str
    body_match: bool
    context_match: bool
    rank_score: float
    citation_text: str
    citation_text_sha256: str


@dataclass(frozen=True)
class SearchResponse:
    status: str
    law_id: str | None
    law_revision_id: str | None
    as_of_date: str | None
    query: str
    query_normalized: str
    hits: tuple[SearchHit, ...]
    temporal_resolution: dict[str, Any] | None
    warnings: tuple[str, ...]

    def to_dict(self):
        value = asdict(self)
        value["hits"] = [asdict(hit) for hit in self.hits]
        return value


def _rows(cur):
    names = [c.name for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def search_revision(conn, law_revision_id: str, query: str, *, limit: int = 20,
                    anchor_tag_name: str | None = None,
                    structural_num: str | None = None,
                    unit_kind: str | None = None) -> tuple[SearchHit, ...]:
    if not REVISION_RE.fullmatch(law_revision_id or ""):
        raise ValueError(f"invalid law_revision_id: {law_revision_id!r}")
    query_normalized = builder.normalize_search_text(query)
    if not query_normalized:
        return ()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM legal_kb.search_revision_units_normalized(%s,%s,%s,%s,%s,%s)",
            (law_revision_id, query_normalized, limit, anchor_tag_name, structural_num, unit_kind),
        )
        rows = _rows(cur)
    hits: list[SearchHit] = []
    for row in rows:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT legal_kb.provision_node_string_value(%s,%s), search_text_cache "
                "FROM legal_kb.search_unit WHERE search_unit_id=%s",
                (row["document_pk"], row["source_document_order"], row["search_unit_id"]),
            )
            citation_text, cache = cur.fetchone()
        if builder.normalize_search_text(citation_text) != builder.normalize_search_text(cache):
            raise RuntimeError(f"search cache/source mismatch: {row['search_unit_id']}")
        hits.append(SearchHit(
            search_unit_id=row["search_unit_id"], law_id=row["law_id"],
            law_revision_id=row["law_revision_id"], document_pk=int(row["document_pk"]),
            document_id=row["document_id"], source_xml_sha256=row["source_xml_sha256"],
            source_document_order=int(row["source_document_order"]),
            anchor_document_order=int(row["anchor_document_order"]), unit_kind=row["unit_kind"],
            anchor_tag_name=row["anchor_tag_name"], anchor_structural_num=row["anchor_structural_num"],
            anchor_display_label=row["anchor_display_label"], hierarchy=row["hierarchy_jsonb"],
            reconstructed_xml_path=row["reconstructed_xml_path"], body_match=bool(row["body_match"]),
            context_match=bool(row["context_match"]), rank_score=float(row["rank_score"]),
            citation_text=citation_text or "",
            citation_text_sha256=sha256((citation_text or "").encode("utf-8")).hexdigest(),
        ))
    return tuple(hits)


def search_as_of(conn, law_id: str, as_of_date: date, query: str, *, limit: int = 20,
                 anchor_tag_name: str | None = None,
                 structural_num: str | None = None,
                 unit_kind: str | None = None) -> SearchResponse:
    resolution = temporal.resolve_as_of(conn, law_id, as_of_date)
    query_normalized = builder.normalize_search_text(query)
    if resolution.status != "resolved" or resolution.content_status != "available":
        warnings = tuple(resolution.warnings) + ("SEARCH_NOT_EXECUTED_WITHOUT_UNIQUE_AVAILABLE_REVISION",)
        return SearchResponse(
            status="not-searchable", law_id=law_id, law_revision_id=resolution.selected_revision_id,
            as_of_date=as_of_date.isoformat(), query=query, query_normalized=query_normalized,
            hits=(), temporal_resolution=resolution.to_dict(), warnings=warnings,
        )
    hits = search_revision(
        conn, resolution.selected_revision_id, query, limit=limit,
        anchor_tag_name=anchor_tag_name, structural_num=structural_num, unit_kind=unit_kind,
    )
    return SearchResponse(
        status="searched", law_id=law_id, law_revision_id=resolution.selected_revision_id,
        as_of_date=as_of_date.isoformat(), query=query, query_normalized=query_normalized,
        hits=hits, temporal_resolution=resolution.to_dict(), warnings=(),
    )
