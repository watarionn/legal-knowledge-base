-- Phase 6.4: NDL Legislative Metadata Adapter
-- OAI-PMH identifier is the logical record identity.
-- Raw GetRecord XML remains immutable source evidence.

BEGIN;

CREATE SCHEMA IF NOT EXISTS legal_kb;
SET search_path TO legal_kb, public;

CREATE TABLE ndl_metadata_observation (
    ndl_metadata_observation_id text PRIMARY KEY,
    external_document_id text NOT NULL
        REFERENCES external_document(external_document_id) ON DELETE RESTRICT,
    snapshot_id text NOT NULL
        REFERENCES external_document_snapshot(snapshot_id) ON DELETE RESTRICT,
    oai_identifier text NOT NULL,
    repository_number text NOT NULL,
    item_number text NOT NULL,
    oai_datestamp text NOT NULL,
    metadata_prefix text NOT NULL CHECK (
        metadata_prefix IN ('oai_dc', 'dcndl', 'dcndl_v3')
    ),
    deleted boolean NOT NULL,
    set_specs text[] NOT NULL DEFAULT ARRAY[]::text[],
    metadata_xml_sha256 text,
    projection_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (ndl_metadata_observation_id ~ '^[0-9a-f]{64}$'),
    CHECK (oai_identifier ~ '^oai:ndlsearch[.]ndl[.]go[.]jp:R[0-9]{9}-I.+$'),
    CHECK (position(' ' in oai_identifier) = 0),
    CHECK (repository_number ~ '^R[0-9]{9}$'),
    CHECK (length(item_number) > 0),
    CHECK (length(oai_datestamp) > 0),
    CHECK (metadata_xml_sha256 IS NULL OR metadata_xml_sha256 ~ '^[0-9a-fA-F]{64}$'),
    CHECK (jsonb_typeof(projection_jsonb) = 'object'),
    CHECK ((deleted AND metadata_xml_sha256 IS NULL)
        OR (NOT deleted AND metadata_xml_sha256 IS NOT NULL)),
    UNIQUE (external_document_id, snapshot_id)
);

COMMENT ON TABLE ndl_metadata_observation IS
  'Snapshot-scoped OAI-PMH metadata observation. Projection columns are rebuildable; raw GetRecord XML in source_file remains evidence.';
COMMENT ON COLUMN ndl_metadata_observation.oai_identifier IS
  'NDL Search OAI-PMH metadata identifier, used as the provider-scoped logical document identity.';
COMMENT ON COLUMN ndl_metadata_observation.deleted IS
  'Persistent OAI-PMH tombstone observation. Historical snapshots are never physically deleted.';

CREATE INDEX ix_ndl_metadata_identifier
    ON ndl_metadata_observation(oai_identifier, observed_at);
CREATE INDEX ix_ndl_metadata_repository
    ON ndl_metadata_observation(repository_number, observed_at);CREATE INDEX ix_ndl_metadata_deleted
    ON ndl_metadata_observation(deleted, observed_at);

CREATE OR REPLACE FUNCTION legal_kb.ndl_metadata_provenance(
    p_external_document_id text
) RETURNS TABLE (
    external_document_id text,
    oai_identifier text,
    oai_datestamp text,
    deleted boolean,
    metadata_prefix text,
    set_specs text[],
    snapshot_id text,
    source_file_id text,
    source_file_sha256 text,
    metadata_xml_sha256 text,
    response_locator text
)
LANGUAGE sql
STABLE
AS $$
SELECT
    o.external_document_id,
    o.oai_identifier,
    o.oai_datestamp,
    o.deleted,
    o.metadata_prefix,
    o.set_specs,
    o.snapshot_id,
    s.source_file_id,
    sf.sha256,
    o.metadata_xml_sha256,
    s.response_locator
FROM legal_kb.ndl_metadata_observation o
JOIN legal_kb.external_document_snapshot s
  ON s.snapshot_id = o.snapshot_id
JOIN legal_kb.source_file sf
  ON sf.source_file_id = s.source_file_id
WHERE o.external_document_id = p_external_document_id
ORDER BY o.observed_at, o.ndl_metadata_observation_id;
$$;

COMMENT ON FUNCTION legal_kb.ndl_metadata_provenance(text) IS
  'Returns OAI identity plus immutable GetRecord source_file SHA and snapshot-scoped metadata hash.';

COMMIT;
