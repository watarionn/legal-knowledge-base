-- 法令ナレッジベース Phase 4: XML構造DB read-only validation package
-- Compact-storage v2. All queries are observational.

SET search_path TO legal_kb, public;

-- 1. Every normalized document must bind to an existing revision and immutable RAW XML.
SELECT d.document_id, d.law_revision_id, d.source_file_id
FROM law_document d
LEFT JOIN law_revision r ON r.law_revision_id = d.law_revision_id
LEFT JOIN source_file s ON s.source_file_id = d.source_file_id
WHERE r.law_revision_id IS NULL
   OR s.source_file_id IS NULL
   OR s.immutable IS DISTINCT FROM true
   OR lower(s.sha256) <> lower(d.source_xml_sha256);

-- 2. No duplicate normalized document for the same revision and identical RAW bytes.
SELECT law_revision_id, source_xml_sha256, count(*) AS duplicate_count
FROM law_document
GROUP BY law_revision_id, source_xml_sha256
HAVING count(*) > 1;

-- 3. Every succeeded document has exactly one root.
SELECT d.document_id,
       count(n.document_order) FILTER (WHERE n.parent_document_order IS NULL) AS root_count
FROM law_document d
LEFT JOIN provision_node n ON n.document_pk = d.document_pk
WHERE d.parse_status IN ('succeeded', 'succeeded-with-warnings')
GROUP BY d.document_id
HAVING count(n.document_order) FILTER (WHERE n.parent_document_order IS NULL) <> 1;

-- 4. Sibling ordinal is 1..N. Uniqueness is also enforced by a table constraint.
SELECT document_pk, parent_document_order,
       min(ordinal) AS min_ordinal,
       max(ordinal) AS max_ordinal,
       count(*) AS child_count
FROM provision_node
GROUP BY document_pk, parent_document_order
HAVING min(ordinal) <> 1 OR max(ordinal) <> count(*);

-- 5. document_order is 1..N in every document.
SELECT document_pk,
       min(document_order) AS min_order,
       max(document_order) AS max_order,
       count(*) AS node_count
FROM provision_node
GROUP BY document_pk
HAVING min(document_order) <> 1 OR max(document_order) <> count(*);

-- 6. Stored node count agrees with law_document metadata.
SELECT d.document_id, d.node_count, count(n.document_order) AS stored_node_count
FROM law_document d
LEFT JOIN provision_node n ON n.document_pk = d.document_pk
GROUP BY d.document_id, d.node_count
HAVING count(n.document_order) <> d.node_count;

-- 7. Element nodes retain their local tag name.
SELECT document_pk, document_order, node_kind, tag_name
FROM provision_node
WHERE node_kind = 'element' AND (tag_name IS NULL OR tag_name = '');

-- 8. Deterministic xml_path is reconstructed from compact coordinates.
-- For targeted checks, compare this function with parser xml_path output.
SELECT d.law_revision_id, n.document_order,
       encode(n.node_id, 'hex') AS node_id,
       provision_node_xml_path(n.document_pk, n.document_order) AS xml_path
FROM provision_node n
JOIN law_document d USING (document_pk)
ORDER BY d.law_revision_id, n.document_order
LIMIT 100;

-- 9. MainProvision without a direct Article is valid input, not an error.
WITH mp AS (
  SELECT document_pk, document_order
  FROM provision_node
  WHERE tag_name = 'MainProvision'
), direct_article AS (
  SELECT DISTINCT mp.document_pk, mp.document_order
  FROM mp
  JOIN provision_node a
    ON a.document_pk = mp.document_pk
   AND a.parent_document_order = mp.document_order
   AND a.tag_name = 'Article'
)
SELECT count(DISTINCT mp.document_pk) AS articleless_main_provision_documents
FROM mp
LEFT JOIN direct_article a USING (document_pk, document_order)
WHERE a.document_pk IS NULL;

-- 10. OldNum / OldStyle projections must retain authoritative source attributes.
SELECT document_pk, document_order, old_num, old_style, attributes_jsonb
FROM provision_node
WHERE (old_num IS NOT NULL AND NOT attributes_jsonb ? 'OldNum')
   OR (old_style IS NOT NULL AND NOT attributes_jsonb ? 'OldStyle');

-- 11. Column and TableColumn stay distinct.
SELECT tag_name, count(*) AS node_count, count(DISTINCT document_pk) AS document_count
FROM provision_node
WHERE tag_name IN ('Column', 'TableColumn')
GROUP BY tag_name
ORDER BY tag_name;

-- 12. Mixed-content payloads are arrays.
SELECT document_pk, document_order, jsonb_typeof(mixed_content_jsonb) AS payload_type
FROM provision_node
WHERE jsonb_typeof(mixed_content_jsonb) <> 'array';

-- 13. Aggregate child-segment count must equal all non-root nodes.
SELECT
  (SELECT coalesce(sum(jsonb_array_length(
      jsonb_path_query_array(mixed_content_jsonb, '$[*] ? (@.kind == "child")')
    )), 0) FROM provision_node) AS mixed_child_segments,
  (SELECT count(*) FROM provision_node WHERE parent_document_order IS NOT NULL) AS non_root_nodes;

-- 14. Targeted full-reference check. On very large corpora this is intentionally expensive.
SELECT p.document_pk, p.document_order,
       (seg.value ->> 'document_order')::integer AS missing_child_order
FROM provision_node p
CROSS JOIN LATERAL jsonb_array_elements(p.mixed_content_jsonb) AS seg(value)
LEFT JOIN provision_node c
  ON c.document_pk = p.document_pk
 AND c.document_order = (seg.value ->> 'document_order')::integer
WHERE seg.value ->> 'kind' = 'child'
  AND c.document_order IS NULL;

-- 15. Tail segments must point at an existing node in the same document.
SELECT p.document_pk, p.document_order,
       (seg.value ->> 'after_document_order')::integer AS missing_after_order
FROM provision_node p
CROSS JOIN LATERAL jsonb_array_elements(p.mixed_content_jsonb) AS seg(value)
LEFT JOIN provision_node c
  ON c.document_pk = p.document_pk
 AND c.document_order = (seg.value ->> 'after_document_order')::integer
WHERE seg.value ->> 'kind' = 'tail'
  AND c.document_order IS NULL;

-- 16. Phase 4 search-normalized text remains non-authoritative/null.
SELECT count(*) AS phase4_nodes_with_search_normalized_text
FROM provision_node
WHERE text_search_normalized IS NOT NULL;

-- 17. Attachment count agrees with law_document metadata.
SELECT d.document_id, d.attachment_reference_count, count(a.attachment_id) AS stored_attachment_count
FROM law_document d
LEFT JOIN attachment a ON a.document_pk = d.document_pk
GROUP BY d.document_id, d.attachment_reference_count
HAVING count(a.attachment_id) <> d.attachment_reference_count;

-- 18. source_src is exact source text. Empty src="" is a valid RAW observation and is inventoried.
SELECT
  count(*) FILTER (WHERE source_src = '') AS empty_source_src_count,
  count(DISTINCT document_pk) FILTER (WHERE source_src = '') AS empty_source_src_document_count,
  count(*) FILTER (WHERE source_src <> '') AS nonempty_source_src_count
FROM attachment;

-- 19. Resolved attachments require a source_file; source_src is never overwritten.
SELECT attachment_id, availability_status, source_file_id, sha256
FROM attachment
WHERE availability_status = 'resolved' AND source_file_id IS NULL;

-- 20. attachment revision agrees with law_document.
SELECT a.attachment_id, a.law_revision_id AS attachment_revision,
       d.law_revision_id AS document_revision
FROM attachment a
JOIN law_document d USING (document_pk)
WHERE a.law_revision_id <> d.law_revision_id;

-- 21. ZIP members are unique within a container and both source rows exist.
SELECT m.container_source_file_id, m.member_path, count(*) AS duplicate_count
FROM source_file_member m
GROUP BY m.container_source_file_id, m.member_path
HAVING count(*) > 1;

SELECT m.member_source_file_id, m.container_source_file_id
FROM source_file_member m
LEFT JOIN source_file ms ON ms.source_file_id = m.member_source_file_id
LEFT JOIN source_file cs ON cs.source_file_id = m.container_source_file_id
WHERE ms.source_file_id IS NULL OR cs.source_file_id IS NULL
   OR ms.immutable IS DISTINCT FROM true OR cs.immutable IS DISTINCT FROM true;

-- 22. Revisions present in RAW snapshot but absent from reconciled Phase 3 API history remain explicit issues.
SELECT entity_id AS law_revision_id, severity, observed_values_jsonb
FROM reconciliation_issue
WHERE issue_code = 'LAW_REVISION_NOT_RECONCILED'
  AND resolved_at IS NULL
ORDER BY entity_id;

-- 23. XSD status is observational and never an ingestion gate.
SELECT schema_validation_status, parse_status, count(*) AS document_count
FROM law_document
GROUP BY schema_validation_status, parse_status
ORDER BY schema_validation_status, parse_status;

-- 24. Parse issue distribution.
SELECT severity, issue_code, count(*) AS issue_count
FROM xml_parse_issue
GROUP BY severity, issue_code
ORDER BY severity, issue_code;

-- 25. Corpus tag inventory.
SELECT tag_name, count(*) AS node_count, count(DISTINCT document_pk) AS document_count
FROM provision_node
WHERE node_kind = 'element'
GROUP BY tag_name
ORDER BY document_count DESC, node_count DESC, tag_name;
