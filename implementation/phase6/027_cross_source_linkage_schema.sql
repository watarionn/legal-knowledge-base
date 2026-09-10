-- Phase 6.5: Cross-source Legal Linkage / Retrieval
-- Relation assertions stay evidentiary; automated matches never become legal truth.

BEGIN;

CREATE SCHEMA IF NOT EXISTS legal_kb;
SET search_path TO legal_kb, public;

CREATE OR REPLACE VIEW source_relation_effective_state AS
SELECT
    r.source_relation_id,
    r.external_document_id,
    r.target_kind,
    r.target_law_id,
    r.target_law_revision_id,
    r.target_document_pk,
    r.target_document_order,
    r.relation_kind,
    count(a.relation_assertion_id) AS assertion_count,
    count(*) FILTER (WHERE a.assertion_status = 'candidate') AS candidate_count,
    count(*) FILTER (WHERE a.assertion_status = 'confirmed') AS confirmed_count,
    count(*) FILTER (WHERE a.assertion_status = 'rejected') AS rejected_count,
    CASE
        WHEN bool_or(a.assertion_status = 'confirmed')
         AND bool_or(a.assertion_status = 'rejected') THEN 'conflicted'
        WHEN bool_or(a.assertion_status = 'confirmed') THEN 'confirmed'
        WHEN bool_or(a.assertion_status = 'rejected') THEN 'rejected'
        ELSE 'candidate'
    END AS effective_state
FROM source_relation r
JOIN source_relation_assertion a USING (source_relation_id)
GROUP BY r.source_relation_id;
COMMENT ON VIEW source_relation_effective_state IS
  'Effective relation status. confirmed+rejected is conflicted; automated candidates never override review evidence.';

CREATE OR REPLACE VIEW external_relation_retrieval AS
SELECT
    st.source_relation_id,
    st.external_document_id,
    d.provider_code,
    p.source_family,
    d.provider_document_id,
    d.document_kind,
    d.issued_on,
    d.title,
    d.canonical_url,
    st.target_kind,
    st.target_law_id,
    st.target_law_revision_id,
    st.target_document_pk,
    st.target_document_order,
    st.relation_kind,
    st.effective_state,
    (st.effective_state = 'confirmed') AS citation_ready,
    snap.snapshot_id,
    snap.source_file_id,
    sf.sha256 AS source_file_sha256
FROM source_relation_effective_state st
JOIN external_document d USING (external_document_id)
JOIN external_source_provider p USING (provider_code)
LEFT JOIN LATERAL (
    SELECT s.*
    FROM external_document_snapshot s
    WHERE s.external_document_id = st.external_document_id
    ORDER BY s.observed_at DESC, s.snapshot_id DESC
    LIMIT 1
) snap ON true
LEFT JOIN source_file sf ON sf.source_file_id = snap.source_file_id;
COMMENT ON VIEW external_relation_retrieval IS
  'External-source retrieval envelope. Only effective_state=confirmed is citation-ready; candidate/conflicted/rejected remain visibly non-citation-ready.';

CREATE INDEX IF NOT EXISTS ix_source_relation_assertion_relation_status
    ON source_relation_assertion(source_relation_id, assertion_status, observed_at);

COMMIT;
