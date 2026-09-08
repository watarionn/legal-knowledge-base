#!/usr/bin/env python3
"""Phase 5.3b provider-neutral embedding adapter."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import struct
from typing import Any, Protocol, Sequence

ADAPTER_VERSION = "phase5-embedding-adapter-1.0"
DEFAULT_INPUT_POLICY = "context-prefix-plus-retrieval-text-v1"


@dataclass(frozen=True)
class EmbeddingProfile:
    provider: str
    model: str
    model_version: str
    vector_dimensions: int
    input_policy: str = DEFAULT_INPUT_POLICY
    adapter_version: str = ADAPTER_VERSION

    def validate(self) -> None:
        for name in ("provider", "model", "model_version", "input_policy", "adapter_version"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be blank")
        if self.vector_dimensions <= 0:
            raise ValueError("vector_dimensions must be positive")

@dataclass(frozen=True)
class ChunkInput:
    chunk_id: str
    context_prefix: str | None
    retrieval_text: str


@dataclass(frozen=True)
class StoredEmbedding:
    embedding_profile_id: str
    chunk_id: str
    vector_dimensions: int
    embedding_input_sha256: str
    embedding_values_sha256: str
    embedding_values: tuple[float, ...]


class EmbeddingProvider(Protocol):
    @property
    def profile(self) -> EmbeddingProfile: ...

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def embedding_profile_id(profile: EmbeddingProfile) -> str:
    profile.validate()
    payload = "\x1f".join((
        profile.adapter_version,
        profile.provider,
        profile.model,
        profile.model_version,
        str(profile.vector_dimensions),
        profile.input_policy,
    ))
    return _sha256_bytes(payload.encode("utf-8"))

def build_embedding_input(chunk: ChunkInput, input_policy: str) -> str:
    if input_policy != DEFAULT_INPUT_POLICY:
        raise ValueError(f"unsupported input_policy: {input_policy}")
    prefix = (chunk.context_prefix or "").strip()
    if prefix:
        return f"{prefix}\n\n{chunk.retrieval_text}"
    return chunk.retrieval_text


def embedding_input_sha256(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _to_float32(value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("embedding values must be finite")
    try:
        packed = struct.pack("!f", numeric)
    except OverflowError as exc:
        raise ValueError("embedding value is outside float32 range") from exc
    normalized = struct.unpack("!f", packed)[0]
    if not math.isfinite(normalized):
        raise ValueError("embedding value became nonfinite after float32 normalization")
    return normalized


def normalize_vector(values: Sequence[float], dimensions: int) -> tuple[float, ...]:
    if len(values) != dimensions:
        raise ValueError(f"embedding dimension mismatch: expected {dimensions}, got {len(values)}")
    return tuple(_to_float32(value) for value in values)


def embedding_values_sha256(values: Sequence[float]) -> str:
    payload = b"".join(struct.pack("!f", _to_float32(value)) for value in values)
    return _sha256_bytes(payload)

class DeterministicTestProvider:
    """Deterministic CI-only provider. Never use for production retrieval quality."""

    def __init__(self, dimensions: int = 8) -> None:
        self._profile = EmbeddingProfile(
            provider="deterministic-test",
            model="sha256-float32",
            model_version="1",
            vector_dimensions=dimensions,
        )
        self._profile.validate()

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        output: list[list[float]] = []
        for text in texts:
            seed = hashlib.sha256(text.encode("utf-8")).digest()
            values: list[float] = []
            counter = 0
            while len(values) < self.profile.vector_dimensions:
                block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
                for offset in range(0, len(block), 4):
                    raw = int.from_bytes(block[offset:offset + 4], "big")
                    values.append((raw / 4294967295.0) * 2.0 - 1.0)
                    if len(values) == self.profile.vector_dimensions:
                        break
                counter += 1
            output.append(values)
        return output


def load_chunks(conn: Any, *, document_pk: int | None = None, limit: int | None = None) -> list[ChunkInput]:
    sql = "SELECT chunk_id, context_prefix, retrieval_text FROM legal_kb.retrieval_chunk"
    params: list[Any] = []
    if document_pk is not None:
        sql += " WHERE document_pk=%s"
        params.append(document_pk)
    sql += " ORDER BY document_pk, start_document_order, chunk_id"
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        sql += " LIMIT %s"
        params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return [ChunkInput(*row) for row in cur.fetchall()]

def ensure_profile(conn: Any, profile: EmbeddingProfile) -> str:
    profile_id = embedding_profile_id(profile)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.embedding_profile (
                embedding_profile_id, adapter_version, provider, model,
                model_version, vector_dimensions, input_policy
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (embedding_profile_id) DO NOTHING
            """,
            (
                profile_id, profile.adapter_version, profile.provider, profile.model,
                profile.model_version, profile.vector_dimensions, profile.input_policy,
            ),
        )
        cur.execute(
            """
            SELECT adapter_version, provider, model, model_version,
                   vector_dimensions, input_policy
            FROM legal_kb.embedding_profile
            WHERE embedding_profile_id=%s
            """,
            (profile_id,),
        )
        stored = cur.fetchone()
    expected = (
        profile.adapter_version, profile.provider, profile.model,
        profile.model_version, profile.vector_dimensions, profile.input_policy,
    )
    if stored != expected:
        raise AssertionError("embedding profile identity collision or metadata drift")
    return profile_id

def _prepare_embedding(
    profile_id: str,
    profile: EmbeddingProfile,
    chunk: ChunkInput,
    values: Sequence[float],
) -> StoredEmbedding:
    input_text = build_embedding_input(chunk, profile.input_policy)
    vector = normalize_vector(values, profile.vector_dimensions)
    return StoredEmbedding(
        embedding_profile_id=profile_id,
        chunk_id=chunk.chunk_id,
        vector_dimensions=profile.vector_dimensions,
        embedding_input_sha256=embedding_input_sha256(input_text),
        embedding_values_sha256=embedding_values_sha256(vector),
        embedding_values=vector,
    )


def store_embedding(conn: Any, embedding: StoredEmbedding) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.chunk_embedding (
                embedding_profile_id, chunk_id, vector_dimensions,
                embedding_input_sha256, embedding_values_sha256, embedding_values
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (embedding_profile_id, chunk_id) DO NOTHING
            """,
            (
                embedding.embedding_profile_id, embedding.chunk_id,
                embedding.vector_dimensions, embedding.embedding_input_sha256,
                embedding.embedding_values_sha256, list(embedding.embedding_values),
            ),
        )
        cur.execute(
            """
            SELECT vector_dimensions, embedding_input_sha256, embedding_values_sha256
            FROM legal_kb.chunk_embedding
            WHERE embedding_profile_id=%s AND chunk_id=%s
            """,
            (embedding.embedding_profile_id, embedding.chunk_id),
        )
        stored = cur.fetchone()
    expected = (
        embedding.vector_dimensions,
        embedding.embedding_input_sha256,
        embedding.embedding_values_sha256,
    )
    if stored != expected:
        raise AssertionError("embedding drift detected for an existing profile/chunk pair")

def embed_chunks(
    conn: Any,
    provider: EmbeddingProvider,
    chunks: Sequence[ChunkInput],
) -> list[StoredEmbedding]:
    profile = provider.profile
    profile.validate()
    profile_id = ensure_profile(conn, profile)
    inputs = [build_embedding_input(chunk, profile.input_policy) for chunk in chunks]
    vectors = provider.embed(inputs)
    if len(vectors) != len(chunks):
        raise ValueError(f"provider result count mismatch: expected {len(chunks)}, got {len(vectors)}")

    stored: list[StoredEmbedding] = []
    for chunk, values in zip(chunks, vectors, strict=True):
        embedding = _prepare_embedding(profile_id, profile, chunk, values)
        store_embedding(conn, embedding)
        stored.append(embedding)
    conn.commit()
    return stored


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-pk", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--deterministic-test-dimensions", type=int)
    parser.add_argument("--allow-test-provider", action="store_true")
    parser.add_argument("--result", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.deterministic_test_dimensions is None or not args.allow_test_provider:
        raise SystemExit(
            "5.3b core is provider-neutral; CLI execution currently requires "
            "--allow-test-provider --deterministic-test-dimensions N"
        )
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("LEGAL_KB_DSN")
    if not dsn:
        raise SystemExit("DATABASE_URL or LEGAL_KB_DSN is required")

    import psycopg

    provider = DeterministicTestProvider(args.deterministic_test_dimensions)
    with psycopg.connect(dsn) as conn:
        chunks = load_chunks(conn, document_pk=args.document_pk, limit=args.limit)
        embeddings = embed_chunks(conn, provider, chunks)

    profile_id = embedding_profile_id(provider.profile)
    result = {
        "schema_version": "1.0",
        "runner": "029_embedding_adapter.py",
        "adapter_version": ADAPTER_VERSION,
        "embedding_profile_id": profile_id,
        "provider": provider.profile.provider,
        "model": provider.profile.model,
        "model_version": provider.profile.model_version,
        "vector_dimensions": provider.profile.vector_dimensions,
        "input_policy": provider.profile.input_policy,
        "chunk_count": len(embeddings),
        "test_provider": True,
        "credentials_recorded": False,
        "database_url_recorded": False,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
