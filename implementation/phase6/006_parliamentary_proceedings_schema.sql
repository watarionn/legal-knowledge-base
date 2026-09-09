-- Phase 6.2: Parliamentary Proceedings Adapters
-- National Diet / Imperial Diet meeting and speech projections.
-- Raw provider payload remains immutable in Phase 3 source_file.

BEGIN;

CREATE SCHEMA IF NOT EXISTS legal_kb;
SET search_path TO legal_kb, public;

CREATE TABLE external_document_part (
    external_part_id text PRIMARY KEY,
    external_document_id text NOT NULL
        REFERENCES external_document(external_document_id) ON DELETE RESTRICT,
    provider_part_id text NOT NULL,
    part_kind text NOT NULL CHECK (part_kind IN ('speech')),
    part_order integer NOT NULL CHECK (part_order >= 0),
    first_seen_run_id text NOT NULL
        REFERENCES ingestion_run(ingestion_run_id) ON DELETE RESTRICT,
    last_seen_run_id text NOT NULL
        REFERENCES ingestion_run(ingestion_run_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (external_part_id ~ '^[0-9a-f]{64}$'),
    CHECK (length(provider_part_id) > 0),
    UNIQUE (external_document_id, provider_part_id)
);

COMMENT ON TABLE external_document_part IS
  'Provider-scoped subdocument identity such as NDL speechID. It is a projection of an immutable external_document_snapshot, not a replacement for the raw response.';
COMMENT ON COLUMN external_document_part.external_part_id IS
  'sha256(phase6-parliamentary-part-1.0 + US + external_document_id + US + provider_part_id).';

CREATE INDEX ix_external_document_part_document
    ON external_document_part(external_document_id, part_order);
CREATE INDEX ix_external_document_part_provider_id
    ON external_document_part(provider_part_id);

CREATE TABLE external_document_part_observation (
    part_observation_id text PRIMARY KEY,
    external_part_id text NOT NULL
        REFERENCES external_document_part(external_part_id) ON DELETE RESTRICT,
    snapshot_id text NOT NULL
        REFERENCES external_document_snapshot(snapshot_id) ON DELETE RESTRICT,
    observed_at timestamptz NOT NULL,
    text_sha256 text,
    text_projection text,
    metadata_projection_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (part_observation_id ~ '^[0-9a-f]{64}$'),
    CHECK (text_sha256 IS NULL OR text_sha256 ~ '^[0-9a-fA-F]{64}$'),
    CHECK (jsonb_typeof(metadata_projection_jsonb) = 'object'),
    UNIQUE (external_part_id, snapshot_id)
);

COMMENT ON TABLE external_document_part_observation IS
  'Snapshot-scoped speech projection. text_projection is rebuildable; source_file payload and SHA remain the source evidence.';
COMMENT ON COLUMN external_document_part_observation.part_observation_id IS
  'sha256(phase6-parliamentary-part-observation-1.0 + US + external_part_id + US + snapshot_id + US + text_sha256-or-none).';

CREATE INDEX ix_external_part_observation_part
    ON external_document_part_observation(external_part_id, observed_at);
CREATE INDEX ix_external_part_observation_snapshot
    ON external_document_part_observation(snapshot_id);
CREATE INDEX ix_external_part_observation_text_sha
    ON external_document_part_observation(text_sha256)
    WHERE text_sha256 IS NOT NULL;

CREATE OR REPLACE FUNCTION legal_kb.parliamentary_part_provenance(
    p_external_part_id text
) RETURNS TABLE (
    external_part_id text,
    provider_part_id text,
    part_order integer,
    external_document_id text,
    provider_code text,
    provider_document_id text,
    issued_on date,
    snapshot_id text,
    source_file_id text,
    source_file_sha256 text,
    text_sha256 text,
    speech_url text
)
LANGUAGE sql
STABLE
AS $$
SELECT
    p.external_part_id,
    p.provider_part_id,
    p.part_order,
    d.external_document_id,
    d.provider_code,
    d.provider_document_id,
    d.issued_on,
    o.snapshot_id,
    s.source_file_id,
    sf.sha256,
    o.text_sha256,
    o.metadata_projection_jsonb ->> 'speechURL'
FROM legal_kb.external_document_part p
JOIN legal_kb.external_document d
  ON d.external_document_id = p.external_document_id
JOIN legal_kb.external_document_part_observation o
  ON o.external_part_id = p.external_part_id
JOIN legal_kb.external_document_snapshot s
  ON s.snapshot_id = o.snapshot_id
JOIN legal_kb.source_file sf
  ON sf.source_file_id = s.source_file_id
WHERE p.external_part_id = p_external_part_id
ORDER BY o.observed_at, o.part_observation_id;
$$;

COMMENT ON FUNCTION legal_kb.parliamentary_part_provenance(text) IS
  'Returns speech identity plus immutable meeting-response source_file SHA and snapshot-scoped text hash.';

COMMIT;
