-- Phase 6.3: Official Gazette Adapter
-- Explicit-issue ingestion only. No site crawling.
-- Raw PDF remains immutable in Phase 3 source_file.

BEGIN;

CREATE SCHEMA IF NOT EXISTS legal_kb;
SET search_path TO legal_kb, public;

CREATE TABLE official_gazette_issue (
    external_document_id text PRIMARY KEY
        REFERENCES external_document(external_document_id) ON DELETE RESTRICT,
    issued_on date NOT NULL,
    publication_kind text NOT NULL CHECK (
        publication_kind IN ('regular','extra','government-procurement','special-extra','index')
    ),
    issue_number integer NOT NULL CHECK (issue_number > 0),
    derived_provider_key text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (derived_provider_key ~ '^derived:[0-9]{4}-[0-9]{2}-[0-9]{2}:[a-z-]+:[0-9]+$')
);

COMMENT ON TABLE official_gazette_issue IS
  'Operator-specified Gazette issue identity. The derived key is not represented as an official Cabinet Office identifier.';
CREATE TABLE official_gazette_asset (
    gazette_asset_id text PRIMARY KEY,
    external_document_id text NOT NULL
        REFERENCES official_gazette_issue(external_document_id) ON DELETE RESTRICT,
    snapshot_id text NOT NULL
        REFERENCES external_document_snapshot(snapshot_id) ON DELETE RESTRICT,
    page_start integer NOT NULL CHECK (page_start > 0),
    page_end integer NOT NULL CHECK (page_end >= page_start),
    pdf_url text NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-fA-F]{64}$'),
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (gazette_asset_id ~ '^[0-9a-f]{64}$'),
    UNIQUE (external_document_id, page_start, page_end, payload_sha256)
);

COMMENT ON TABLE official_gazette_asset IS
  'Booklet PDF or split PDF segment explicitly supplied to the adapter. The adapter never discovers assets by crawling the Gazette site.';

CREATE INDEX ix_official_gazette_asset_issue
    ON official_gazette_asset(external_document_id, page_start, page_end);
CREATE INDEX ix_official_gazette_asset_snapshot
    ON official_gazette_asset(snapshot_id);
CREATE TABLE official_gazette_certificate_observation (
    snapshot_id text PRIMARY KEY
        REFERENCES external_document_snapshot(snapshot_id) ON DELETE RESTRICT,
    signature_field_count integer NOT NULL CHECK (signature_field_count >= 0),
    document_timestamp_count integer NOT NULL CHECK (document_timestamp_count >= 0),
    byte_range_count integer NOT NULL CHECK (byte_range_count >= 0),
    cades_detached_count integer NOT NULL CHECK (cades_detached_count >= 0),
    cryptographic_verification_status text NOT NULL CHECK (
        cryptographic_verification_status IN ('not-checked','valid','invalid','indeterminate')
    ),
    verifier_name text,
    verifier_version text,
    details_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(details_jsonb) = 'object')
);

COMMENT ON TABLE official_gazette_certificate_observation IS
  'Signature/timestamp observations for a Gazette PDF. Byte-level structure detection is not cryptographic certificate validation.';

CREATE INDEX ix_gazette_certificate_status
    ON official_gazette_certificate_observation(cryptographic_verification_status);
CREATE OR REPLACE FUNCTION legal_kb.official_gazette_asset_provenance(
    p_gazette_asset_id text
) RETURNS TABLE (
    gazette_asset_id text,
    external_document_id text,
    provider_document_id text,
    issued_on date,
    publication_kind text,
    issue_number integer,
    page_start integer,
    page_end integer,
    pdf_url text,
    snapshot_id text,
    source_file_id text,
    source_file_sha256 text,
    asset_payload_sha256 text,
    cryptographic_verification_status text
)
LANGUAGE sql
STABLE
AS $$
SELECT a.gazette_asset_id, d.external_document_id, d.provider_document_id,
       i.issued_on, i.publication_kind, i.issue_number,
       a.page_start, a.page_end, a.pdf_url,
       s.snapshot_id, s.source_file_id, sf.sha256, a.payload_sha256,
       c.cryptographic_verification_status
FROM legal_kb.official_gazette_asset a
JOIN legal_kb.official_gazette_issue i USING (external_document_id)
JOIN legal_kb.external_document d USING (external_document_id)
JOIN legal_kb.external_document_snapshot s ON s.snapshot_id = a.snapshot_id
JOIN legal_kb.source_file sf ON sf.source_file_id = s.source_file_id
LEFT JOIN legal_kb.official_gazette_certificate_observation c ON c.snapshot_id = s.snapshot_id
WHERE a.gazette_asset_id = p_gazette_asset_id;
$$;

COMMENT ON FUNCTION legal_kb.official_gazette_asset_provenance(text) IS
  'Returns derived issue identity plus immutable Gazette PDF source_file SHA and certificate-observation status.';

COMMIT;
