from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

PHASE5_DIR = Path(__file__).resolve().parent


def _load():
    path = PHASE5_DIR / "029_embedding_adapter.py"
    spec = importlib.util.spec_from_file_location("legal_kb_phase5_embedding_adapter_smoke_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EMBED = _load()


class VersionedProvider:
    def __init__(self, version: str, dimensions: int = 8, bias: float = 0.0) -> None:
        self._base = EMBED.DeterministicTestProvider(dimensions)
        self._profile = EMBED.EmbeddingProfile(
            provider="deterministic-test",
            model="sha256-float32",
            model_version=version,
            vector_dimensions=dimensions,
        )
        self.bias = bias

    @property
    def profile(self):
        return self._profile

    def embed(self, texts):
        vectors = self._base.embed(texts)
        if self.bias == 0.0:
            return vectors
        return [[value + self.bias for value in vector] for vector in vectors]


def _scalar(conn, sql: str, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def run(database_url: str) -> dict:
    import psycopg

    with psycopg.connect(database_url) as conn:
        document_pk = _scalar(conn, "SELECT min(document_pk) FROM legal_kb.retrieval_chunk")
        if document_pk is None:
            raise AssertionError("Phase 5.3a retrieval chunk smoke must run first")
        chunks = EMBED.load_chunks(conn, document_pk=int(document_pk))
        if not chunks:
            raise AssertionError("no retrieval chunks available for embedding smoke")

        provider_v1 = VersionedProvider("1", dimensions=8)
        first = EMBED.embed_chunks(conn, provider_v1, chunks)
        second = EMBED.embed_chunks(conn, provider_v1, chunks)
        if [row.embedding_values_sha256 for row in first] != [row.embedding_values_sha256 for row in second]:
            raise AssertionError("embedding rebuild is not deterministic")

        profile_v1 = EMBED.embedding_profile_id(provider_v1.profile)
        count_v1 = int(_scalar(
            conn,
            "SELECT count(*) FROM legal_kb.chunk_embedding WHERE embedding_profile_id=%s",
            (profile_v1,),
        ))
        if count_v1 != len(chunks):
            raise AssertionError("unexpected v1 embedding count")

        drift_detected = False
        drift_provider = VersionedProvider("1", dimensions=8, bias=0.125)
        try:
            EMBED.embed_chunks(conn, drift_provider, chunks[:1])
        except AssertionError as exc:
            if "drift" not in str(exc):
                raise
            drift_detected = True
        if not drift_detected:
            raise AssertionError("same-profile embedding drift was not detected")

        provider_v2 = VersionedProvider("2", dimensions=8)
        third = EMBED.embed_chunks(conn, provider_v2, chunks)
        profile_v2 = EMBED.embedding_profile_id(provider_v2.profile)
        if profile_v1 == profile_v2:
            raise AssertionError("model version must change embedding profile identity")
        if len(third) != len(chunks):
            raise AssertionError("unexpected v2 embedding count")

        profile_count = int(_scalar(
            conn,
            "SELECT count(*) FROM legal_kb.embedding_profile WHERE provider='deterministic-test'",
        ))
        embedding_count = int(_scalar(
            conn,
            "SELECT count(*) FROM legal_kb.chunk_embedding WHERE chunk_id = ANY(%s)",
            ([chunk.chunk_id for chunk in chunks],),
        ))
        if profile_count != 2 or embedding_count != len(chunks) * 2:
            raise AssertionError("versioned embedding profiles did not coexist")

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT provider, model_version, chunk_id, law_revision_id,
                       source_xml_sha256, retrieval_text_sha256
                FROM legal_kb.chunk_embedding_provenance(%s, %s)
                """,
                (profile_v1, chunks[0].chunk_id),
            )
            provenance = cur.fetchone()
        if provenance is None or provenance[0] != "deterministic-test" or provenance[1] != "1":
            raise AssertionError("embedding provenance roundtrip failed")
        if not provenance[3] or not provenance[4] or not provenance[5]:
            raise AssertionError("embedding provenance must reach revision and source hashes")

        return {
            "schema_version": "1.0",
            "runner": "031_embedding_adapter_smoke.py",
            "status": "passed",
            "adapter_version": EMBED.ADAPTER_VERSION,
            "document_pk": int(document_pk),
            "chunk_count": len(chunks),
            "profile_count": profile_count,
            "embedding_count": embedding_count,
            "vector_dimensions": 8,
            "deterministic_rebuild": True,
            "same_profile_drift_detected": True,
            "model_versions_coexist": True,
            "provenance_roundtrip": True,
            "test_provider_only": True,
            "credentials_recorded": False,
            "database_url_recorded": False,
        }


def main() -> None:
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("LEGAL_KB_DSN")
    if not database_url:
        raise SystemExit("DATABASE_URL or LEGAL_KB_DSN is required")
    result = run(database_url)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
