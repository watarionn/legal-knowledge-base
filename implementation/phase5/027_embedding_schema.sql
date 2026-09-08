-- 法令ナレッジベース Phase 5.3b: embedding adapter storage
-- Target: PostgreSQL 16+
-- Embeddings are disposable derivative data. Citation truth remains Phase 3/4.

BEGIN;

CREATE TABLE IF NOT EXISTS legal_kb.embedding_profile (
    embedding_profile_id text PRIMARY KEY,
    adapter_version text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    model_version text NOT NULL,
    vector_dimensions integer NOT NULL CHECK (vector_dimensions > 0),
    input_policy text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),

    CHECK (embedding_profile_id ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(adapter_version) <> ''),
    CHECK (btrim(provider) <> ''),
    CHECK (btrim(model) <> ''),
    CHECK (btrim(model_version) <> ''),
    CHECK (btrim(input_policy) <> ''),
    UNIQUE (embedding_profile_id, vector_dimensions)
);

COMMENT ON TABLE legal_kb.embedding_profile IS
  'Embedding生成条件のimmutable profile。provider/model/version/dimensions/input policyを固定する。';
CREATE TABLE IF NOT EXISTS legal_kb.chunk_embedding (
    embedding_profile_id text NOT NULL,
    chunk_id text NOT NULL,
    vector_dimensions integer NOT NULL CHECK (vector_dimensions > 0),
    embedding_input_sha256 text NOT NULL,
    embedding_values_sha256 text NOT NULL,
    embedding_values real[] NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (embedding_profile_id, chunk_id),
    CHECK (embedding_input_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (embedding_values_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (cardinality(embedding_values) = vector_dimensions),
    CHECK (array_position(embedding_values, NULL) IS NULL),

    FOREIGN KEY (embedding_profile_id, vector_dimensions)
        REFERENCES legal_kb.embedding_profile(embedding_profile_id, vector_dimensions)
        ON DELETE CASCADE,
    FOREIGN KEY (chunk_id)
        REFERENCES legal_kb.retrieval_chunk(chunk_id) ON DELETE CASCADE
);

COMMENT ON TABLE legal_kb.chunk_embedding IS
  'chunk_idへ従属する再生成可能なembedding。vector backendや引用正本ではない。';
COMMENT ON COLUMN legal_kb.chunk_embedding.embedding_input_sha256 IS
  'input_policy適用後のembedding入力UTF-8 bytesのSHA-256。';
COMMENT ON COLUMN legal_kb.chunk_embedding.embedding_values_sha256 IS
  'float32へ正規化したvectorのcanonical binary SHA-256。';
CREATE INDEX IF NOT EXISTS ix_chunk_embedding_chunk
    ON legal_kb.chunk_embedding(chunk_id, embedding_profile_id);

CREATE OR REPLACE FUNCTION legal_kb.chunk_embedding_provenance(
    p_embedding_profile_id text,
    p_chunk_id text
)
RETURNS TABLE (
    embedding_profile_id text,
    adapter_version text,
    provider text,
    model text,
    model_version text,
    vector_dimensions integer,
    input_policy text,
    chunk_id text,
    embedding_input_sha256 text,
    embedding_values_sha256 text,
    law_id text,
    law_revision_id text,
    source_xml_sha256 text,
    retrieval_text_sha256 text
)
LANGUAGE sql
STABLE
AS $$
SELECT
    p.embedding_profile_id,
    p.adapter_version,
    p.provider,
    p.model,
    p.model_version,
    p.vector_dimensions,
    p.input_policy,
    e.chunk_id,
    e.embedding_input_sha256,
    e.embedding_values_sha256,
    c.law_id,
    c.law_revision_id,
    c.source_xml_sha256,
    c.retrieval_text_sha256
FROM legal_kb.chunk_embedding e
JOIN legal_kb.embedding_profile p
  ON p.embedding_profile_id=e.embedding_profile_id
JOIN legal_kb.retrieval_chunk c
  ON c.chunk_id=e.chunk_id
WHERE e.embedding_profile_id=p_embedding_profile_id
  AND e.chunk_id=p_chunk_id;
$$;

COMMENT ON FUNCTION legal_kb.chunk_embedding_provenance(text, text) IS
  'Embeddingからprofile、chunk、revision、RAW SHAまで戻るprovenance envelope。';

COMMIT;
