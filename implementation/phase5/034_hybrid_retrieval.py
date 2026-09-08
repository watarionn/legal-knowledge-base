#!/usr/bin/env python3
"""Phase 5.3c strict temporal hybrid retrieval and context assembly."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any, Protocol, Sequence

PHASE5_DIR = Path(__file__).resolve().parent
RETRIEVAL_VERSION = "phase5-hybrid-retrieval-1.0"
DEFAULT_RRF_K = 60
DEFAULT_CHANNEL_LIMIT = 50
DEFAULT_MAX_CONTEXTS = 8
DEFAULT_CHARACTER_BUDGET = 6000
CHANNEL_ORDER = ("lexical", "structural", "vector")


def _load(name: str, filename: str):
    path = PHASE5_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TEMPORAL = _load("legal_kb_phase5_temporal_for_hybrid", "003_temporal_resolver.py")
EMBED = _load("legal_kb_phase5_embedding_for_hybrid", "029_embedding_adapter.py")
@dataclass(frozen=True)
class StructuralFilter:
    tag_name: str | None = None
    structural_num: str | None = None
    display_label: str | None = None

    def active(self) -> bool:
        return any(value is not None and str(value).strip() for value in (
            self.tag_name, self.structural_num, self.display_label
        ))


@dataclass(frozen=True)
class RetrievalConfig:
    rrf_k: int = DEFAULT_RRF_K
    lexical_weight: float = 1.0
    structural_weight: float = 0.75
    vector_weight: float = 1.0
    per_channel_limit: int = DEFAULT_CHANNEL_LIMIT
    max_contexts: int = DEFAULT_MAX_CONTEXTS
    character_budget: int = DEFAULT_CHARACTER_BUDGET
    chunking_config_sha256: str | None = None
    embedding_profile_id: str | None = None

    def validate(self) -> None:
        if self.rrf_k <= 0:
            raise ValueError("rrf_k must be positive")
        if self.per_channel_limit <= 0 or self.per_channel_limit > 200:
            raise ValueError("per_channel_limit must be in 1..200")
        if self.max_contexts <= 0:
            raise ValueError("max_contexts must be positive")
        if self.character_budget <= 0:
            raise ValueError("character_budget must be positive")
        for name in ("lexical_weight", "structural_weight", "vector_weight"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.chunking_config_sha256 is None:
            raise ValueError("chunking_config_sha256 is required for hybrid retrieval")
        if len(self.chunking_config_sha256) != 64:
            raise ValueError("chunking_config_sha256 must be a SHA-256 hex string")
        if self.embedding_profile_id is not None and len(self.embedding_profile_id) != 64:
            raise ValueError("embedding_profile_id must be a SHA-256 hex string")
@dataclass(frozen=True)
class ChannelHit:
    channel: str
    rank: int
    chunk_id: str
    law_id: str
    law_revision_id: str
    document_pk: int
    anchor_document_order: int
    start_document_order: int
    end_document_order: int
    context_prefix: str | None
    retrieval_text: str
    source_xml_sha256: str
    retrieval_text_sha256: str
    raw_score: float


@dataclass(frozen=True)
class FusedHit:
    chunk_id: str
    fused_score: float
    channels: tuple[str, ...]
    channel_ranks: tuple[tuple[str, int], ...]
    channel_scores: tuple[tuple[str, float], ...]
    law_id: str
    law_revision_id: str
    document_pk: int
    anchor_document_order: int
    start_document_order: int
    end_document_order: int
    context_prefix: str | None
    retrieval_text: str
    source_xml_sha256: str
    retrieval_text_sha256: str


@dataclass(frozen=True)
class ContextEnvelope:
    retrieval_rank: int
    chunk_id: str
    fused_score: float
    channels: tuple[str, ...]
    channel_ranks: tuple[tuple[str, int], ...]
    law_id: str
    law_revision_id: str
    document_pk: int
    source_xml_sha256: str
    retrieval_text_sha256: str
    context_prefix: str | None
    retrieval_text: str
    source_document_orders: tuple[int, ...]
    anchor_xml_path: str
    start_xml_path: str
    end_xml_path: str
    budget_overflow: bool
    citation_ready: bool = False
@dataclass(frozen=True)
class HybridRetrievalResult:
    status: str
    retrieval_version: str
    retrieval_config_sha256: str
    vector_backend: str | None
    embedding_profile_id: str | None
    resolution: Any
    channel_counts: tuple[tuple[str, int], ...]
    contexts: tuple[ContextEnvelope, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "retrieval_version": self.retrieval_version,
            "retrieval_config_sha256": self.retrieval_config_sha256,
            "vector_backend": self.vector_backend,
            "embedding_profile_id": self.embedding_profile_id,
            "resolution": self.resolution.to_dict(),
            "channel_counts": dict(self.channel_counts),
            "contexts": [asdict(context) for context in self.contexts],
            "warnings": list(self.warnings),
            "citation_truth": "phase3-phase4",
            "context_citation_ready": False,
        }


class VectorBackend(Protocol):
    name: str

    def search(
        self,
        conn: Any,
        *,
        embedding_profile_id: str,
        law_revision_id: str,
        document_pk: int,
        query_vector: Sequence[float],
        chunking_config_sha256: str | None,
        limit: int,
    ) -> list[ChannelHit]: ...


def retrieval_config_sha256(config: RetrievalConfig) -> str:
    config.validate()
    payload = {
        "retrieval_version": RETRIEVAL_VERSION,
        "rrf_k": config.rrf_k,
        "weights": {
            "lexical": config.lexical_weight,
            "structural": config.structural_weight,
            "vector": config.vector_weight,
        },
        "per_channel_limit": config.per_channel_limit,
        "max_contexts": config.max_contexts,
        "character_budget": config.character_budget,
        "embedding_profile_id": config.embedding_profile_id,
        "chunking_config_sha256": config.chunking_config_sha256,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
def _row_to_channel_hit(channel: str, rank: int, row: Sequence[Any]) -> ChannelHit:
    score = float(row[11])
    if not math.isfinite(score):
        raise ValueError(f"nonfinite {channel} score")
    return ChannelHit(
        channel=channel,
        rank=rank,
        chunk_id=str(row[0]),
        law_id=str(row[1]),
        law_revision_id=str(row[2]),
        document_pk=int(row[3]),
        anchor_document_order=int(row[4]),
        start_document_order=int(row[5]),
        end_document_order=int(row[6]),
        context_prefix=row[7],
        retrieval_text=str(row[8]),
        source_xml_sha256=str(row[9]),
        retrieval_text_sha256=str(row[10]),
        raw_score=score,
    )


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("cosine dimension mismatch")
    if not left:
        raise ValueError("cosine vectors must not be empty")
    dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("cosine similarity is undefined for a zero vector")
    score = dot / (left_norm * right_norm)
    if not math.isfinite(score):
        raise ValueError("cosine similarity became nonfinite")
    return max(-1.0, min(1.0, score))


class PostgresRealArrayExactBackend:
    """Correctness backend for 5.3c. It is not the scalable ANN production backend."""

    name = "postgres-real-array-exact-validation"

    def search(
        self,
        conn: Any,
        *,
        embedding_profile_id: str,
        law_revision_id: str,
        document_pk: int,
        query_vector: Sequence[float],
        chunking_config_sha256: str | None,
        limit: int,
    ) -> list[ChannelHit]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT vector_dimensions FROM legal_kb.embedding_profile WHERE embedding_profile_id=%s",
                (embedding_profile_id,),
            )
            profile = cur.fetchone()
        if profile is None:
            raise ValueError("embedding profile not found")
        vector = EMBED.normalize_vector(query_vector, int(profile[0]))
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.chunk_id, c.law_id, c.law_revision_id, c.document_pk,
                    c.anchor_document_order, c.start_document_order, c.end_document_order,
                    c.context_prefix, c.retrieval_text, c.source_xml_sha256,
                    c.retrieval_text_sha256, e.embedding_values
                FROM legal_kb.chunk_embedding e
                JOIN legal_kb.retrieval_chunk c ON c.chunk_id=e.chunk_id
                WHERE e.embedding_profile_id=%s
                  AND c.law_revision_id=%s
                  AND c.document_pk=%s
                  AND c.chunking_config_sha256=%s
                ORDER BY c.start_document_order, c.chunk_id
                """,
                (embedding_profile_id, law_revision_id, document_pk, chunking_config_sha256),
            )
            rows = cur.fetchall()

        scored: list[tuple[float, Sequence[Any]]] = []
        for row in rows:
            candidate_vector = tuple(float(value) for value in row[11])
            try:
                score = _cosine_similarity(vector, candidate_vector)
            except ValueError as exc:
                if "zero vector" in str(exc):
                    continue
                raise
            scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], int(item[1][5]), str(item[1][0])))

        hits: list[ChannelHit] = []
        for rank, (score, row) in enumerate(scored[:limit], start=1):
            hits.append(ChannelHit(
                channel="vector", rank=rank, chunk_id=str(row[0]), law_id=str(row[1]),
                law_revision_id=str(row[2]), document_pk=int(row[3]),
                anchor_document_order=int(row[4]), start_document_order=int(row[5]),
                end_document_order=int(row[6]), context_prefix=row[7],
                retrieval_text=str(row[8]), source_xml_sha256=str(row[9]),
                retrieval_text_sha256=str(row[10]), raw_score=score,
            ))
        return hits
def lexical_search(
    conn: Any,
    *,
    query_text: str,
    law_revision_id: str,
    document_pk: int,
    chunking_config_sha256: str | None,
    limit: int,
) -> list[ChannelHit]:
    if not query_text.strip():
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM legal_kb.retrieval_chunk_lexical_search(%s,%s,%s,%s,%s)",
            (query_text, law_revision_id, document_pk, chunking_config_sha256, limit),
        )
        rows = cur.fetchall()
    return [_row_to_channel_hit("lexical", rank, row) for rank, row in enumerate(rows, start=1)]


def structural_search(
    conn: Any,
    *,
    structural_filter: StructuralFilter,
    law_revision_id: str,
    document_pk: int,
    chunking_config_sha256: str | None,
    limit: int,
) -> list[ChannelHit]:
    if not structural_filter.active():
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM legal_kb.retrieval_chunk_structural_search(%s,%s,%s,%s,%s,%s,%s)",
            (
                law_revision_id, document_pk,
                structural_filter.tag_name, structural_filter.structural_num,
                structural_filter.display_label, chunking_config_sha256, limit,
            ),
        )
        rows = cur.fetchall()
    return [_row_to_channel_hit("structural", rank, row) for rank, row in enumerate(rows, start=1)]


def _metadata_identity(hit: ChannelHit) -> tuple[Any, ...]:
    return (
        hit.law_id, hit.law_revision_id, hit.document_pk,
        hit.anchor_document_order, hit.start_document_order, hit.end_document_order,
        hit.context_prefix, hit.retrieval_text,
        hit.source_xml_sha256, hit.retrieval_text_sha256,
    )
def fuse_hits(channel_hits: Sequence[ChannelHit], config: RetrievalConfig) -> list[FusedHit]:
    config.validate()
    weights = {
        "lexical": config.lexical_weight,
        "structural": config.structural_weight,
        "vector": config.vector_weight,
    }
    grouped: dict[str, list[ChannelHit]] = {}
    for hit in channel_hits:
        if hit.channel not in weights:
            raise ValueError(f"unknown retrieval channel: {hit.channel}")
        if hit.rank <= 0:
            raise ValueError("channel rank must be positive")
        grouped.setdefault(hit.chunk_id, []).append(hit)

    fused: list[FusedHit] = []
    for chunk_id, hits in grouped.items():
        first = hits[0]
        expected = _metadata_identity(first)
        if any(_metadata_identity(hit) != expected for hit in hits[1:]):
            raise AssertionError("chunk metadata drift across retrieval channels")
        by_channel: dict[str, ChannelHit] = {}
        for hit in hits:
            previous = by_channel.get(hit.channel)
            if previous is None or hit.rank < previous.rank:
                by_channel[hit.channel] = hit
        score = sum(
            weights[channel] / (config.rrf_k + hit.rank)
            for channel, hit in by_channel.items()
            if weights[channel] > 0
        )
        channels = tuple(channel for channel in CHANNEL_ORDER if channel in by_channel)
        ranks = tuple((channel, by_channel[channel].rank) for channel in channels)
        scores = tuple((channel, by_channel[channel].raw_score) for channel in channels)
        fused.append(FusedHit(
            chunk_id=chunk_id,
            fused_score=score,
            channels=channels,
            channel_ranks=ranks,
            channel_scores=scores,
            law_id=first.law_id,
            law_revision_id=first.law_revision_id,
            document_pk=first.document_pk,
            anchor_document_order=first.anchor_document_order,
            start_document_order=first.start_document_order,
            end_document_order=first.end_document_order,
            context_prefix=first.context_prefix,
            retrieval_text=first.retrieval_text,
            source_xml_sha256=first.source_xml_sha256,
            retrieval_text_sha256=first.retrieval_text_sha256,
        ))
    fused.sort(key=lambda hit: (-hit.fused_score, hit.start_document_order, hit.chunk_id))
    return fused
def _fetch_context_provenance(conn: Any, hit: FusedHit) -> tuple[tuple[int, ...], str, str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM legal_kb.retrieval_chunk_provenance(%s)", (hit.chunk_id,))
        row = cur.fetchone()
    if row is None:
        raise AssertionError("retrieval chunk provenance disappeared")
    if str(row[4]) != hit.law_id or str(row[5]) != hit.law_revision_id:
        raise AssertionError("retrieval chunk law/revision provenance drift")
    if int(row[6]) != hit.document_pk:
        raise AssertionError("retrieval chunk document provenance drift")
    if str(row[14]).lower() != hit.source_xml_sha256.lower():
        raise AssertionError("retrieval chunk source SHA provenance drift")
    if str(row[15]).lower() != hit.retrieval_text_sha256.lower():
        raise AssertionError("retrieval text SHA provenance drift")
    paths = (row[8], row[10], row[12])
    if any(path is None or not str(path) for path in paths):
        raise AssertionError("context provenance XML path is missing")
    return tuple(int(value) for value in row[13]), str(row[8]), str(row[10]), str(row[12])


def assemble_contexts(
    conn: Any,
    fused_hits: Sequence[FusedHit],
    *,
    max_contexts: int,
    character_budget: int,
) -> list[ContextEnvelope]:
    if max_contexts <= 0 or character_budget <= 0:
        raise ValueError("context limits must be positive")
    contexts: list[ContextEnvelope] = []
    used_chars = 0
    for retrieval_rank, hit in enumerate(fused_hits, start=1):
        if len(contexts) >= max_contexts:
            break
        char_count = len(hit.retrieval_text)
        overflow = False
        if used_chars + char_count > character_budget:
            if contexts:
                continue
            overflow = True
        source_orders, anchor_path, start_path, end_path = _fetch_context_provenance(conn, hit)
        contexts.append(ContextEnvelope(
            retrieval_rank=retrieval_rank,
            chunk_id=hit.chunk_id,
            fused_score=hit.fused_score,
            channels=hit.channels,
            channel_ranks=hit.channel_ranks,
            law_id=hit.law_id,
            law_revision_id=hit.law_revision_id,
            document_pk=hit.document_pk,
            source_xml_sha256=hit.source_xml_sha256,
            retrieval_text_sha256=hit.retrieval_text_sha256,
            context_prefix=hit.context_prefix,
            retrieval_text=hit.retrieval_text,
            source_document_orders=source_orders,
            anchor_xml_path=anchor_path,
            start_xml_path=start_path,
            end_xml_path=end_path,
            budget_overflow=overflow,
        ))
        used_chars += char_count
    return contexts
def _empty_result(
    resolution: Any,
    config: RetrievalConfig,
    *,
    status: str,
    warnings: Sequence[str],
    vector_backend: str | None = None,
) -> HybridRetrievalResult:
    return HybridRetrievalResult(
        status=status,
        retrieval_version=RETRIEVAL_VERSION,
        retrieval_config_sha256=retrieval_config_sha256(config),
        vector_backend=vector_backend,
        embedding_profile_id=config.embedding_profile_id,
        resolution=resolution,
        channel_counts=tuple((channel, 0) for channel in CHANNEL_ORDER),
        contexts=(),
        warnings=tuple(warnings),
    )


def _assert_scope(hit: ChannelHit, resolution: Any) -> None:
    if hit.law_id != resolution.law_id:
        raise AssertionError("retrieval hit leaked across law_id")
    if hit.law_revision_id != resolution.selected_revision_id:
        raise AssertionError("retrieval hit leaked across law_revision_id")
    if hit.document_pk != resolution.selected_document_pk:
        raise AssertionError("retrieval hit leaked across selected document")
    if hit.source_xml_sha256.lower() != resolution.source_xml_sha256.lower():
        raise AssertionError("retrieval hit source SHA differs from temporal selection")


def hybrid_retrieve(
    conn: Any,
    law_id: str,
    as_of_date: date,
    query_text: str,
    *,
    config: RetrievalConfig,
    structural_filter: StructuralFilter | None = None,
    query_vector: Sequence[float] | None = None,
    vector_backend: VectorBackend | None = None,
) -> HybridRetrievalResult:
    config.validate()
    structural_filter = structural_filter or StructuralFilter()
    if (query_vector is None) != (config.embedding_profile_id is None):
        raise ValueError("query_vector and embedding_profile_id must be supplied together")
    if not query_text.strip() and not structural_filter.active() and query_vector is None:
        raise ValueError("at least one retrieval channel must be active")

    resolution = TEMPORAL.resolve_as_of(conn, law_id, as_of_date)
    backend_name = vector_backend.name if query_vector is not None and vector_backend is not None else None
    if resolution.status != "resolved":
        return _empty_result(
            resolution, config,
            status="blocked-temporal",
            warnings=tuple(resolution.warnings) + ("RETRIEVAL_NOT_RUN",),
            vector_backend=backend_name,
        )
    if resolution.content_status != "available":
        return _empty_result(
            resolution, config,
            status="blocked-content",
            warnings=tuple(resolution.warnings) + ("RETRIEVAL_NOT_RUN",),
            vector_backend=backend_name,
        )
    if resolution.selected_revision_id is None or resolution.selected_document_pk is None:
        raise AssertionError("resolved available content is missing selected provenance")
    if resolution.source_xml_sha256 is None:
        raise AssertionError("resolved available content is missing source SHA")
    all_hits: list[ChannelHit] = []
    lexical = lexical_search(
        conn,
        query_text=query_text,
        law_revision_id=resolution.selected_revision_id,
        document_pk=resolution.selected_document_pk,
        chunking_config_sha256=config.chunking_config_sha256,
        limit=config.per_channel_limit,
    )
    all_hits.extend(lexical)

    structural = structural_search(
        conn,
        structural_filter=structural_filter,
        law_revision_id=resolution.selected_revision_id,
        document_pk=resolution.selected_document_pk,
        chunking_config_sha256=config.chunking_config_sha256,
        limit=config.per_channel_limit,
    )
    all_hits.extend(structural)

    vector: list[ChannelHit] = []
    if query_vector is not None:
        backend = vector_backend or PostgresRealArrayExactBackend()
        backend_name = backend.name
        vector = backend.search(
            conn,
            embedding_profile_id=config.embedding_profile_id,
            law_revision_id=resolution.selected_revision_id,
            document_pk=resolution.selected_document_pk,
            query_vector=query_vector,
            chunking_config_sha256=config.chunking_config_sha256,
            limit=config.per_channel_limit,
        )
        all_hits.extend(vector)

    for hit in all_hits:
        _assert_scope(hit, resolution)

    fused = fuse_hits(all_hits, config)
    contexts = assemble_contexts(
        conn,
        fused,
        max_contexts=config.max_contexts,
        character_budget=config.character_budget,
    )

    warnings: list[str] = []
    if query_vector is not None and backend_name == PostgresRealArrayExactBackend.name:
        warnings.append("VECTOR_BACKEND_VALIDATION_ONLY")
    if query_vector is not None and not vector:
        warnings.append("VECTOR_CHANNEL_NO_HITS")
    if not contexts:
        warnings.append("NO_RETRIEVAL_HITS")

    return HybridRetrievalResult(
        status="ok" if contexts else "no-hits",
        retrieval_version=RETRIEVAL_VERSION,
        retrieval_config_sha256=retrieval_config_sha256(config),
        vector_backend=backend_name,
        embedding_profile_id=config.embedding_profile_id,
        resolution=resolution,
        channel_counts=(("lexical", len(lexical)), ("structural", len(structural)), ("vector", len(vector))),
        contexts=tuple(contexts),
        warnings=tuple(warnings),
    )
