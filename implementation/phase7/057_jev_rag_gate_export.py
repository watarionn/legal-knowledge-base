#!/usr/bin/env python3
"""Shadow export contract for the Jev Legal KB RAG evidence gate.

This module does not call Jev and cannot change retrieval, evidence, citations,
or generated answers. It only exports a bounded JSON-safe snapshot for an
external advisory sidecar.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


CONTRACT = "legal-kb-jev-rag-gate-v1"
MODE = "shadow_only"
MAX_EVIDENCE = 8
MAX_NODES_PER_EVIDENCE = 64
MAX_TEXT_CHARS_PER_NODE = 4000


def _bounded_node(node: dict[str, Any]) -> dict[str, Any]:
    text = node.get("text_original")
    if isinstance(text, str) and len(text) > MAX_TEXT_CHARS_PER_NODE:
        text = text[:MAX_TEXT_CHARS_PER_NODE]
    return {
        "node_id_hex": node.get("node_id_hex"),
        "xml_path": node.get("xml_path"),
        "tag_name": node.get("tag_name"),
        "structural_num": node.get("structural_num"),
        "display_label": node.get("display_label"),
        "text_original": text,
    }


def _bounded_evidence(item: dict[str, Any]) -> dict[str, Any]:
    nodes = item.get("source_nodes") or []
    return {
        "evidence_id": item.get("evidence_id"),
        "retrieval_rank": item.get("retrieval_rank"),
        "chunk_id": item.get("chunk_id"),
        "law_id": item.get("law_id"),
        "law_revision_id": item.get("law_revision_id"),
        "document_pk": item.get("document_pk"),
        "source_xml_sha256": item.get("source_xml_sha256"),
        "display_path": item.get("display_path"),
        "source_nodes": [
            _bounded_node(node)
            for node in nodes[:MAX_NODES_PER_EVIDENCE]
            if isinstance(node, dict)
        ],
    }


def build_shadow_export(query_response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(query_response, dict):
        raise TypeError("query_response must be a dict")

    retrieval = query_response.get("retrieval") or {}
    law_resolution = query_response.get("law_resolution") or {}
    temporal = query_response.get("temporal_resolution") or {}
    evidence_raw = query_response.get("evidence")
    if evidence_raw is None:
        evidence = []
    elif not isinstance(evidence_raw, list):
        raise ValueError("query_response evidence must be a list")
    else:
        evidence = evidence_raw

    return {
        "contract": CONTRACT,
        "mode": MODE,
        "question": query_response.get("question"),
        "as_of_date": query_response.get("effective_as_of_date"),
        "law_title": (
            law_resolution.get("selected_title")
            or law_resolution.get("law_title")
        ),
        "law_id": law_resolution.get("selected_law_id"),
        "temporal_status": temporal.get("status"),
        "retrieval_status": retrieval.get("status"),
        "retrieval_query_text": retrieval.get("query_text"),
        "structural_filter": deepcopy(retrieval.get("structural_filter") or {}),
        "retrieval_context_count": retrieval.get("context_count"),
        "evidence": [
            _bounded_evidence(item)
            for item in evidence[:MAX_EVIDENCE]
            if isinstance(item, dict)
        ],
        "authority": {
            "change_retrieval": False,
            "change_temporal_resolution": False,
            "change_citation_truth": False,
            "suppress_answer": False,
            "trigger_additional_retrieval": False,
        },
        "answer_content_exported": False,
        "source_truth": "phase3-phase4",
    }
