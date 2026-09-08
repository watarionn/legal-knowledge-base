#!/usr/bin/env python3
"""Phase 5.3a deterministic structural retrieval chunk builder."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

CHUNKING_VERSION = "phase5-structural-chunk-1.0"
DEFAULT_MAX_CHARS = 1200
BOUNDARY_TAGS = frozenset({
    "Article", "Paragraph", "Item",
    "Subitem1", "Subitem2", "Subitem3", "Subitem4", "Subitem5",
    "Subitem6", "Subitem7", "Subitem8", "Subitem9", "Subitem10",
    "SupplProvision", "Preamble", "EnactStatement",
    "Appdx", "AppdxTable", "AppdxStyle", "AppdxFig", "AppdxFormat", "AppdxNote",
    "TableStruct", "FigStruct",
})


@dataclass(frozen=True)
class DocumentMeta:
    document_pk: int
    law_id: str
    law_revision_id: str
    source_xml_sha256: str

@dataclass(frozen=True)
class NodeRow:
    document_order: int
    node_id_hex: str
    parent_document_order: int | None
    tag_name: str | None
    structural_num: str | None
    display_label: str | None
    text_original: str | None


@dataclass(frozen=True)
class ChunkPlan:
    chunk_id: str
    chunking_version: str
    chunking_config_sha256: str
    soft_max_chars: int
    document_pk: int
    law_id: str
    law_revision_id: str
    source_xml_sha256: str
    anchor_document_order: int
    start_document_order: int
    end_document_order: int
    source_document_orders: tuple[int, ...]
    anchor_node_id_hex: str
    start_node_id_hex: str
    end_node_id_hex: str
    anchor_tag_name: str | None
    anchor_structural_num: str | None
    anchor_display_label: str | None
    context_prefix: str | None
    retrieval_text: str
    retrieval_text_sha256: str
    char_count: int
    source_unit_count: int
    is_oversize: bool


def normalize_retrieval_text(text: str | None) -> str:
    if text is None:
        return ""
    return " ".join(text.split())


def _node_label(node: NodeRow) -> str:
    if node.display_label and node.display_label.strip():
        return normalize_retrieval_text(node.display_label)
    if node.tag_name and node.structural_num:
        return f"{node.tag_name} {node.structural_num}"
    return node.tag_name or ""


def _find_anchor(order: int, nodes: dict[int, NodeRow]) -> int:
    node = nodes[order]
    direct_parent = node.parent_document_order
    current: NodeRow | None = node
    seen: set[int] = set()
    while current is not None and current.document_order not in seen:
        seen.add(current.document_order)
        if current.tag_name in BOUNDARY_TAGS:
            return current.document_order
        parent_order = current.parent_document_order
        current = nodes.get(parent_order) if parent_order is not None else None
    if direct_parent is not None and direct_parent in nodes:
        return direct_parent
    return order


def _context_prefix(anchor_order: int, nodes: dict[int, NodeRow]) -> str | None:
    parts: list[str] = []
    current = nodes.get(anchor_order)
    seen: set[int] = set()
    while current is not None and current.document_order not in seen:
        seen.add(current.document_order)
        if current.document_order == anchor_order or current.tag_name in BOUNDARY_TAGS:
            label = _node_label(current)
            if label:
                parts.append(label)
        parent_order = current.parent_document_order
        current = nodes.get(parent_order) if parent_order is not None else None
    parts.reverse()
    return " > ".join(parts) or None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunking_config_sha256(version: str, max_chars: int) -> str:
    payload = "\x1f".join((version, f"soft_max_chars={max_chars}"))
    return _sha256_text(payload)


def _chunk_id(
    version: str,
    config_sha256: str,
    meta: DocumentMeta,
    anchor: NodeRow,
    first: NodeRow,
    last: NodeRow,
    retrieval_text_sha256: str,
) -> str:
    payload = "\x1f".join((
        version,
        config_sha256,
        meta.law_revision_id,
        meta.source_xml_sha256,
        anchor.node_id_hex,
        first.node_id_hex,
        last.node_id_hex,
        retrieval_text_sha256,
    ))
    return _sha256_text(payload)


def _make_chunk(
    *,
    version: str,
    max_chars: int,
    meta: DocumentMeta,
    nodes: dict[int, NodeRow],
    anchor_order: int,
    source_units: list[tuple[NodeRow, str]],
) -> ChunkPlan:
    anchor = nodes[anchor_order]
    first = source_units[0][0]
    last = source_units[-1][0]
    retrieval_text = "\n".join(text for _, text in source_units)
    text_sha = _sha256_text(retrieval_text)
    config_sha = chunking_config_sha256(version, max_chars)
    return ChunkPlan(
        chunk_id=_chunk_id(version, config_sha, meta, anchor, first, last, text_sha),
        chunking_version=version,
        chunking_config_sha256=config_sha,
        soft_max_chars=max_chars,
        document_pk=meta.document_pk,
        law_id=meta.law_id,
        law_revision_id=meta.law_revision_id,
        source_xml_sha256=meta.source_xml_sha256,
        anchor_document_order=anchor_order,
        start_document_order=first.document_order,
        end_document_order=last.document_order,
        source_document_orders=tuple(node.document_order for node, _ in source_units),
        anchor_node_id_hex=anchor.node_id_hex,
        start_node_id_hex=first.node_id_hex,
        end_node_id_hex=last.node_id_hex,
        anchor_tag_name=anchor.tag_name,
        anchor_structural_num=anchor.structural_num,
        anchor_display_label=anchor.display_label,
        context_prefix=_context_prefix(anchor_order, nodes),
        retrieval_text=retrieval_text,
        retrieval_text_sha256=text_sha,
        char_count=len(retrieval_text),
        source_unit_count=len(source_units),
        is_oversize=len(retrieval_text) > max_chars,
    )


def build_document_chunks(
    meta: DocumentMeta,
    rows: Iterable[NodeRow],
    *,
    chunking_version: str = CHUNKING_VERSION,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[ChunkPlan]:
    if max_chars < 100:
        raise ValueError("max_chars must be >= 100")
    if not chunking_version.strip():
        raise ValueError("chunking_version must not be empty")
    nodes = {row.document_order: row for row in rows}
    text_units = [
        (row, normalize_retrieval_text(row.text_original))
        for row in sorted(nodes.values(), key=lambda r: r.document_order)
        if normalize_retrieval_text(row.text_original)
    ]

    chunks: list[ChunkPlan] = []
    current_anchor: int | None = None
    current_units: list[tuple[NodeRow, str]] = []
    current_chars = 0

    def flush() -> None:
        nonlocal current_anchor, current_units, current_chars
        if current_anchor is None or not current_units:
            return
        chunks.append(_make_chunk(
            version=chunking_version,
            max_chars=max_chars,
            meta=meta,
            nodes=nodes,
            anchor_order=current_anchor,
            source_units=current_units,
        ))
        current_anchor = None
        current_units = []
        current_chars = 0

    for node, text in text_units:
        anchor_order = _find_anchor(node.document_order, nodes)
        if current_anchor is not None and anchor_order != current_anchor:
            flush()
        candidate_chars = len(text) if not current_units else current_chars + 1 + len(text)
        if current_units and candidate_chars > max_chars:
            flush()
        if current_anchor is None:
            current_anchor = anchor_order
        current_units.append((node, text))
        current_chars = len(text) if len(current_units) == 1 else current_chars + 1 + len(text)
    flush()
    return chunks


def load_document_meta(conn: Any, document_pk: int) -> DocumentMeta:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.document_pk, r.law_id, d.law_revision_id, d.source_xml_sha256
            FROM legal_kb.law_document d
            JOIN legal_kb.law_revision r ON r.law_revision_id = d.law_revision_id
            WHERE d.document_pk = %s
              AND d.parse_status IN ('succeeded', 'succeeded-with-warnings')
            """,
            (document_pk,),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"eligible law_document not found: {document_pk}")
    return DocumentMeta(*row)


def load_document_nodes(conn: Any, document_pk: int) -> list[NodeRow]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                document_order,
                encode(node_id, 'hex'),
                parent_document_order,
                tag_name,
                structural_num,
                display_label,
                text_original
            FROM legal_kb.provision_node
            WHERE document_pk = %s
            ORDER BY document_order
            """,
            (document_pk,),
        )
        return [NodeRow(*row) for row in cur.fetchall()]


def store_chunks(conn: Any, chunks: list[ChunkPlan], *, document_pk: int, chunking_config_sha256: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM legal_kb.retrieval_chunk WHERE document_pk=%s AND chunking_config_sha256=%s",
            (document_pk, chunking_config_sha256),
        )
        for chunk in chunks:
            cur.execute(
                """
                INSERT INTO legal_kb.retrieval_chunk (
                    chunk_id, chunking_version, chunking_config_sha256, soft_max_chars,
                    document_pk, law_id, law_revision_id, source_xml_sha256,
                    anchor_document_order, start_document_order,
                    end_document_order, source_document_orders, anchor_node_id,
                    start_node_id, end_node_id, anchor_tag_name,
                    anchor_structural_num, anchor_display_label, context_prefix,
                    retrieval_text, retrieval_text_sha256, char_count,
                    source_unit_count, is_oversize
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, decode(%s, 'hex'),
                    decode(%s, 'hex'), decode(%s, 'hex'), %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                """,
                (
                    chunk.chunk_id, chunk.chunking_version, chunk.chunking_config_sha256,
                    chunk.soft_max_chars, chunk.document_pk, chunk.law_id,
                    chunk.law_revision_id, chunk.source_xml_sha256,
                    chunk.anchor_document_order, chunk.start_document_order,
                    chunk.end_document_order, list(chunk.source_document_orders),
                    chunk.anchor_node_id_hex, chunk.start_node_id_hex, chunk.end_node_id_hex,
                    chunk.anchor_tag_name, chunk.anchor_structural_num,
                    chunk.anchor_display_label, chunk.context_prefix,
                    chunk.retrieval_text, chunk.retrieval_text_sha256,
                    chunk.char_count, chunk.source_unit_count, chunk.is_oversize,
                ),
            )
    conn.commit()
    return len(chunks)

def rebuild_document(
    conn: Any,
    document_pk: int,
    *,
    chunking_version: str = CHUNKING_VERSION,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[ChunkPlan]:
    meta = load_document_meta(conn, document_pk)
    nodes = load_document_nodes(conn, document_pk)
    chunks = build_document_chunks(
        meta,
        nodes,
        chunking_version=chunking_version,
        max_chars=max_chars,
    )
    store_chunks(
        conn,
        chunks,
        document_pk=document_pk,
        chunking_config_sha256=chunking_config_sha256(chunking_version, max_chars),
    )
    return chunks


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-pk", type=int, required=True)
    parser.add_argument("--chunking-version", default=CHUNKING_VERSION)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--result", type=Path)
    return parser.parse_args()

def main() -> None:
    args = _parse_args()
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("LEGAL_KB_DSN")
    if not dsn:
        raise SystemExit("DATABASE_URL or LEGAL_KB_DSN is required")

    import psycopg

    with psycopg.connect(dsn) as conn:
        chunks = rebuild_document(
            conn,
            args.document_pk,
            chunking_version=args.chunking_version,
            max_chars=args.max_chars,
        )

    result = {
        "schema_version": "1.0",
        "runner": "024_retrieval_chunk_builder.py",
        "chunking_version": args.chunking_version,
        "chunking_config_sha256": chunking_config_sha256(args.chunking_version, args.max_chars),
        "soft_max_chars": args.max_chars,
        "document_pk": args.document_pk,
        "chunk_count": len(chunks),
        "oversize_chunk_count": sum(1 for chunk in chunks if chunk.is_oversize),
        "database_url_recorded": False,
    }
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
