-- 法令ナレッジベース Phase 5.1: strict temporal resolution
-- Target: PostgreSQL 16+

BEGIN;

CREATE OR REPLACE FUNCTION legal_kb.law_revision_as_of_candidates(
    p_law_id text,
    p_as_of date
) RETURNS TABLE (
    law_revision_id text,
    valid_from date,
    valid_to_exclusive date,
    temporal_resolution_quality text,
    revision_sequence integer,
    law_title text,
    succeeded_document_count bigint,
    document_pk bigint,
    document_id text,
    source_xml_sha256 text
)
LANGUAGE sql
STABLE
AS $$
WITH document_summary AS (
    SELECT
        d.law_revision_id,
        count(*) FILTER (
            WHERE d.parse_status IN ('succeeded', 'succeeded-with-warnings')
        ) AS succeeded_document_count,
        CASE
            WHEN count(*) FILTER (
                WHERE d.parse_status IN ('succeeded', 'succeeded-with-warnings')
            ) = 1
            THEN min(d.document_pk) FILTER (
                WHERE d.parse_status IN ('succeeded', 'succeeded-with-warnings')
            )
            ELSE NULL
        END AS document_pk
    FROM legal_kb.law_document d
    GROUP BY d.law_revision_id
), selected_document AS (
    SELECT
        s.law_revision_id,
        s.succeeded_document_count,
        s.document_pk,
        d.document_id,
        d.source_xml_sha256
    FROM document_summary s
    LEFT JOIN legal_kb.law_document d
      ON d.document_pk = s.document_pk
)
SELECT
    r.law_revision_id,
    r.valid_from,
    r.valid_to_exclusive,
    r.temporal_resolution_quality,
    r.revision_sequence,
    r.law_title,
    coalesce(sd.succeeded_document_count, 0) AS succeeded_document_count,
    sd.document_pk,
    sd.document_id,
    sd.source_xml_sha256
FROM legal_kb.law_revision r
LEFT JOIN selected_document sd
  ON sd.law_revision_id = r.law_revision_id
WHERE r.law_id = p_law_id
  AND r.valid_from IS NOT NULL
  AND r.valid_from <= p_as_of
  AND (r.valid_to_exclusive IS NULL OR p_as_of < r.valid_to_exclusive)
ORDER BY
    r.valid_from DESC,
    r.revision_sequence NULLS LAST,
    r.law_revision_id;
$$;

COMMENT ON FUNCTION legal_kb.law_revision_as_of_candidates(text, date) IS
  '指定日を包含する全revision候補を返す。same-day/ambiguous候補を1件へ丸めず、本文availabilityも併記する。';

COMMIT;
