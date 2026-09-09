-- 法令ナレッジベース Phase 6.1: External Source Foundation
-- Target: PostgreSQL
-- External sources remain distinct from Phase 3/4 law text truth.

BEGIN;

CREATE SCHEMA IF NOT EXISTS legal_kb;
SET search_path TO legal_kb, public;

CREATE TABLE external_source_provider (
    provider_code text PRIMARY KEY,
    source_family text NOT NULL CHECK (
        source_family IN (
            'official-gazette',
            'diet-minutes',
            'imperial-diet-minutes',
            'ndl-search'
        )
    ),
    authority_name text NOT NULL,
    base_url text NOT NULL,
    transport_kind text NOT NULL CHECK (
        transport_kind IN ('html-pdf', 'http-json-xml', 'sru-opensearch-oai-pmh', 'other')
    ),
    provider_id_strategy text NOT NULL,
    source_truth_role text NOT NULL CHECK (
        source_truth_role IN (
            'official-publication',
            'official-proceedings',
            'bibliographic-metadata'
        )
    ),
    active boolean NOT NULL DEFAULT true,
    metadata_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (provider_code ~ '^[a-z0-9][a-z0-9._-]{2,63}$'),
    CHECK (jsonb_typeof(metadata_jsonb) = 'object')
);

COMMENT ON TABLE external_source_provider IS
  'Phase 6 external source registry. Provider metadata describes acquisition/provenance only; it does not merge external material into law text truth.';
COMMENT ON COLUMN external_source_provider.provider_id_strategy IS
  'How the adapter obtains a provider-scoped logical identifier. Derived keys must be explicitly labeled as derived, not misrepresented as official IDs.';

CREATE TABLE external_document (
    external_document_id text PRIMARY KEY,
    provider_code text NOT NULL REFERENCES external_source_provider(provider_code) ON DELETE RESTRICT,
    provider_document_id text NOT NULL,
    document_kind text NOT NULL,
    issued_on date,
    title text,
    canonical_url text,
    first_seen_run_id text NOT NULL REFERENCES ingestion_run(ingestion_run_id) ON DELETE RESTRICT,
    last_seen_run_id text NOT NULL REFERENCES ingestion_run(ingestion_run_id) ON DELETE RESTRICT,
    metadata_projection_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (external_document_id ~ '^[0-9a-f]{64}$'),
    CHECK (length(provider_document_id) > 0),
    CHECK (length(document_kind) > 0),
    CHECK (jsonb_typeof(metadata_projection_jsonb) = 'object'),
    UNIQUE (provider_code, provider_document_id)
);

COMMENT ON TABLE external_document IS
  'Provider-scoped logical external record. Mutable metadata columns are searchable projections; immutable fetched evidence is external_document_snapshot/source_file.';
COMMENT ON COLUMN external_document.external_document_id IS
  'sha256(identity_version + US + provider_code + US + provider_document_id).';
COMMENT ON COLUMN external_document.metadata_projection_jsonb IS
  'Search/display projection only. Never use as a replacement for immutable raw source_file payload.';

CREATE INDEX ix_external_document_provider
    ON external_document(provider_code, issued_on);
CREATE INDEX ix_external_document_kind
    ON external_document(document_kind, issued_on);

CREATE TABLE external_document_snapshot (
    snapshot_id text PRIMARY KEY,
    external_document_id text NOT NULL REFERENCES external_document(external_document_id) ON DELETE RESTRICT,
    source_file_id text NOT NULL REFERENCES source_file(source_file_id) ON DELETE RESTRICT,
    ingestion_run_id text NOT NULL REFERENCES ingestion_run(ingestion_run_id) ON DELETE RESTRICT,
    observed_at timestamptz NOT NULL,
    payload_sha256 text NOT NULL,
    response_locator text,
    response_metadata_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (snapshot_id ~ '^[0-9a-f]{64}$'),
    CHECK (payload_sha256 ~ '^[0-9a-fA-F]{64}$'),
    CHECK (jsonb_typeof(response_metadata_jsonb) = 'object'),
    UNIQUE (external_document_id, payload_sha256)
);

COMMENT ON TABLE external_document_snapshot IS
  'Immutable observation of an external document backed by Phase 3 source_file. A changed payload becomes a new snapshot; old observations are never overwritten.';
COMMENT ON COLUMN external_document_snapshot.snapshot_id IS
  'sha256(snapshot_version + US + external_document_id + US + lowercase(payload_sha256)).';

CREATE INDEX ix_external_snapshot_document
    ON external_document_snapshot(external_document_id, observed_at);
CREATE INDEX ix_external_snapshot_source_file
    ON external_document_snapshot(source_file_id);

CREATE TABLE source_relation (
    source_relation_id text PRIMARY KEY,
    external_document_id text NOT NULL REFERENCES external_document(external_document_id) ON DELETE RESTRICT,
    target_kind text NOT NULL CHECK (
        target_kind IN ('law', 'law_revision', 'provision_node')
    ),
    target_law_id text REFERENCES law(law_id) ON DELETE RESTRICT,
    target_law_revision_id text REFERENCES law_revision(law_revision_id) ON DELETE RESTRICT,
    target_document_pk bigint,
    target_document_order integer,
    relation_kind text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_relation_id ~ '^[0-9a-f]{64}$'),
    CHECK (length(relation_kind) > 0),
    CHECK (
        (target_kind = 'law'
         AND target_law_id IS NOT NULL
         AND target_law_revision_id IS NULL
         AND target_document_pk IS NULL
         AND target_document_order IS NULL)
        OR
        (target_kind = 'law_revision'
         AND target_law_id IS NULL
         AND target_law_revision_id IS NOT NULL
         AND target_document_pk IS NULL
         AND target_document_order IS NULL)
        OR
        (target_kind = 'provision_node'
         AND target_law_id IS NULL
         AND target_law_revision_id IS NULL
         AND target_document_pk IS NOT NULL
         AND target_document_order IS NOT NULL)
    ),
    FOREIGN KEY (target_document_pk, target_document_order)
        REFERENCES provision_node(document_pk, document_order) ON DELETE RESTRICT
);

COMMENT ON TABLE source_relation IS
  'Logical association between external material and Phase 3/4 entities. The relation row does not itself assert that the association is legally confirmed.';
COMMENT ON COLUMN source_relation.relation_kind IS
  'Domain relation label such as promulgates/discusses/mentions. Its evidentiary status lives in source_relation_assertion.';

CREATE INDEX ix_source_relation_external
    ON source_relation(external_document_id, relation_kind);
CREATE INDEX ix_source_relation_law
    ON source_relation(target_law_id) WHERE target_law_id IS NOT NULL;
CREATE INDEX ix_source_relation_revision
    ON source_relation(target_law_revision_id) WHERE target_law_revision_id IS NOT NULL;
CREATE INDEX ix_source_relation_node
    ON source_relation(target_document_pk, target_document_order)
    WHERE target_document_pk IS NOT NULL;

CREATE TABLE source_relation_assertion (
    relation_assertion_id text PRIMARY KEY,
    source_relation_id text NOT NULL REFERENCES source_relation(source_relation_id) ON DELETE RESTRICT,
    snapshot_id text REFERENCES external_document_snapshot(snapshot_id) ON DELETE RESTRICT,
    ingestion_run_id text NOT NULL REFERENCES ingestion_run(ingestion_run_id) ON DELETE RESTRICT,
    assertion_basis text NOT NULL CHECK (
        assertion_basis IN (
            'provider-explicit',
            'identifier-match',
            'metadata-match',
            'text-match',
            'manual',
            'derived'
        )
    ),
    assertion_status text NOT NULL CHECK (
        assertion_status IN ('candidate', 'confirmed', 'rejected')
    ),
    source_locator text,
    evidence_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (relation_assertion_id ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(evidence_jsonb) = 'object')
);

COMMENT ON TABLE source_relation_assertion IS
  'Evidence-bearing observations for a source_relation. Conflicting candidate/confirmed/rejected assertions coexist instead of overwriting one another.';
COMMENT ON COLUMN source_relation_assertion.assertion_status IS
  'Automated fuzzy/text/metadata matches start as candidate. Confirmation requires provider-explicit evidence or an explicit review decision.';

CREATE INDEX ix_source_relation_assertion_relation
    ON source_relation_assertion(source_relation_id, observed_at);
CREATE INDEX ix_source_relation_assertion_status
    ON source_relation_assertion(assertion_status, assertion_basis);

CREATE OR REPLACE FUNCTION legal_kb.external_relation_provenance(
    p_source_relation_id text
) RETURNS TABLE (
    source_relation_id text,
    relation_assertion_id text,
    assertion_status text,
    assertion_basis text,
    external_document_id text,
    provider_code text,
    provider_document_id text,
    document_kind text,
    issued_on date,
    snapshot_id text,
    source_file_id text,
    source_file_sha256 text,
    target_kind text,
    target_identifier text,
    target_xml_path text,
    relation_kind text
)
LANGUAGE sql
STABLE
AS $$
SELECT
    r.source_relation_id,
    a.relation_assertion_id,
    a.assertion_status,
    a.assertion_basis,
    d.external_document_id,
    d.provider_code,
    d.provider_document_id,
    d.document_kind,
    d.issued_on,
    s.snapshot_id,
    s.source_file_id,
    sf.sha256,
    r.target_kind,
    CASE
        WHEN r.target_kind = 'law' THEN r.target_law_id
        WHEN r.target_kind = 'law_revision' THEN r.target_law_revision_id
        ELSE r.target_document_pk::text || ':' || r.target_document_order::text
    END,
    CASE
        WHEN r.target_kind = 'provision_node'
        THEN legal_kb.provision_node_xml_path(r.target_document_pk, r.target_document_order)
        ELSE NULL
    END,
    r.relation_kind
FROM legal_kb.source_relation r
JOIN legal_kb.external_document d
  ON d.external_document_id = r.external_document_id
LEFT JOIN legal_kb.source_relation_assertion a
  ON a.source_relation_id = r.source_relation_id
LEFT JOIN legal_kb.external_document_snapshot s
  ON s.snapshot_id = a.snapshot_id
LEFT JOIN legal_kb.source_file sf
  ON sf.source_file_id = s.source_file_id
WHERE r.source_relation_id = p_source_relation_id
ORDER BY a.observed_at NULLS LAST, a.relation_assertion_id;
$$;

COMMENT ON FUNCTION legal_kb.external_relation_provenance(text) IS
  'Returns external-provider identity, immutable source_file SHA, relation assertion status, and Phase 3/4 target provenance without promoting external content to law text truth.';

COMMIT;
