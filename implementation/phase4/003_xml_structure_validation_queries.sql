-- 法令ナレッジベース Phase 4: XML構造DB read-only validation package
-- All queries are observational. They must not mutate normalized or RAW data.

SET search_path TO legal_kb, public;

-- 1. law_document must bind to an existing revision and immutable source file.
SELECT d.document_id, d.law_revision_id, d.source_file_id
FROM law_document d
LEFT JOIN law_revision r ON r.law_revision_id = d.law_revision_id
LEFT JOIN source_file s ON s.source_file_id = d.source_file_id
WHERE r.law_revision_id IS NULL
   OR s.source_file_id IS NULL
   OR s.immutable IS DISTINCT FROM true;

-- 2. document_id and source hash format / deterministic uniqueness surface.
SELECT law_revision_id, source_xml_sha256, count(*) AS duplicate_count
FROM law_document
GROUP BY law_revision_id, source_xml_sha256
HAVING count(*) > 1;

-- 3. Every succeeded document must have exactly one root node.
SELECT d.document_id,
       count(n.node_id) FILTER (WHERE n.parent_node_id IS NULL) AS root_count
FROM law_document d
LEFT JOIN provision_node n ON n.document_id = d.document_id
WHERE d.parse_status IN ('succeeded', 'succeeded-with-warnings')
GROUP BY d.document_id
HAVING count(n.node_id) FILTER (WHERE n.parent_node_id IS NULL) <> 1;

-- 4. No orphaned parent references inside the document tree.
SELECT c.document_id, c.node_id, c.parent_node_id
FROM provision_node c
LEFT JOIN provision_node p
  ON p.document_id = c.document_id
 AND p.node_id = c.parent_node_id
WHERE c.parent_node_id IS NOT NULL
  AND p.node_id IS NULL;

-- 5. Sibling ordinal must be unique and contiguous from 1 within each parent.
SELECT document_id, parent_node_id,
       min(ordinal) AS min_ordinal,
       max(ordinal) AS max_ordinal,
       count(*) AS node_count,
       count(DISTINCT ordinal) AS distinct_ordinal_count
FROM provision_node
GROUP BY document_id, parent_node_id
HAVING min(ordinal) <> 1
    OR max(ordinal) <> count(*)
    OR count(DISTINCT ordinal) <> count(*);

-- 6. document_order must be unique and contiguous from 1 in every document.
SELECT document_id,
       min(document_order) AS min_order,
       max(document_order) AS max_order,
       count(*) AS node_count,
       count(DISTINCT document_order) AS distinct_order_count
FROM provision_node
GROUP BY document_id
HAVING min(document_order) <> 1
    OR max(document_order) <> count(*)
    OR count(DISTINCT document_order) <> count(*);

-- 7. xml_path must be unique per document and non-empty.
SELECT document_id, xml_path, count(*) AS duplicate_count
FROM provision_node
GROUP BY document_id, xml_path
HAVING xml_path = '' OR count(*) > 1;

-- 8. Element nodes must retain a tag name; non-element kinds may not need one.
SELECT document_id, node_id, node_kind, tag_name
FROM provision_node
WHERE node_kind = 'element'
  AND (tag_name IS NULL OR tag_name = '');

-- 9. MainProvision without direct Article is legal input and must be measurable, not rejected.
SELECT count(DISTINCT mp.document_id) AS articleless_main_provision_documents
FROM provision_node mp
WHERE mp.tag_name = 'MainProvision'
  AND NOT EXISTS (
      SELECT 1
      FROM provision_node c
      WHERE c.document_id = mp.document_id
        AND c.parent_node_id = mp.node_id
        AND c.tag_name = 'Article'
  );

-- 10. Preserve OldNum / OldStyle in authoritative attributes_jsonb when projected.
SELECT document_id, node_id, old_num, old_style, attributes_jsonb
FROM provision_node
WHERE (old_num IS NOT NULL AND NOT attributes_jsonb ? 'OldNum')
   OR (old_style IS NOT NULL AND NOT attributes_jsonb ? 'OldStyle');

-- 11. Column and TableColumn remain separate tag identities.
SELECT tag_name, count(*) AS node_count
FROM provision_node
WHERE tag_name IN ('Column', 'TableColumn')
GROUP BY tag_name
ORDER BY tag_name;

-- 12. Mixed-content payloads must be arrays.
SELECT document_id, node_id, jsonb_typeof(mixed_content_jsonb) AS payload_type
FROM provision_node
WHERE jsonb_typeof(mixed_content_jsonb) <> 'array';

-- 13. Any child segment in mixed_content_jsonb must resolve to a node in the same document.
SELECT p.document_id, p.node_id, seg.value ->> 'node_id' AS missing_child_node_id
FROM provision_node p
CROSS JOIN LATERAL jsonb_array_elements(p.mixed_content_jsonb) WITH ORDINALITY AS seg(value, ord)
LEFT JOIN provision_node c
  ON c.document_id = p.document_id
 AND c.node_id = seg.value ->> 'node_id'
WHERE seg.value ->> 'kind' = 'child'
  AND c.node_id IS NULL;

-- 14. Tail segments must refer to an existing preceding child in the same document.
SELECT p.document_id, p.node_id, seg.value ->> 'after_node_id' AS missing_after_node_id
FROM provision_node p
CROSS JOIN LATERAL jsonb_array_elements(p.mixed_content_jsonb) WITH ORDINALITY AS seg(value, ord)
LEFT JOIN provision_node c
  ON c.document_id = p.document_id
 AND c.node_id = seg.value ->> 'after_node_id'
WHERE seg.value ->> 'kind' = 'tail'
  AND c.node_id IS NULL;

-- 15. Phase 4 must not accidentally make search-normalized text authoritative.
SELECT count(*) AS phase4_nodes_with_search_normalized_text
FROM provision_node
WHERE text_search_normalized IS NOT NULL;

-- 16. Attachment references keep source src even when unresolved.
SELECT attachment_id, document_id, ref_node_id, availability_status
FROM attachment
WHERE source_src IS NULL OR source_src = '';

-- 17. Resolved attachment must have a source_file and valid checksum when checksum is present.
SELECT attachment_id, availability_status, source_file_id, sha256
FROM attachment
WHERE availability_status = 'resolved'
  AND source_file_id IS NULL;

-- 18. attachment law_revision_id must agree with its law_document.
SELECT a.attachment_id, a.law_revision_id AS attachment_revision, d.law_revision_id AS document_revision
FROM attachment a
JOIN law_document d ON d.document_id = a.document_id
WHERE a.law_revision_id <> d.law_revision_id;

-- 19. ZIP member paths must be unique inside their container and source rows must exist.
SELECT m.container_source_file_id, m.member_path, count(*) AS duplicate_count
FROM source_file_member m
GROUP BY m.container_source_file_id, m.member_path
HAVING count(*) > 1;

-- 20. XSD-invalid documents are expected observations and must not imply parse failure by themselves.
SELECT schema_validation_status, parse_status, count(*) AS document_count
FROM law_document
GROUP BY schema_validation_status, parse_status
ORDER BY schema_validation_status, parse_status;

-- 21. Parse issue distribution for review. Unknown elements/attributes are not automatically errors.
SELECT severity, issue_code, count(*) AS issue_count
FROM xml_parse_issue
GROUP BY severity, issue_code
ORDER BY severity, issue_code;

-- 22. Corpus tag inventory, used to detect parser whitelist regressions.
SELECT tag_name, count(*) AS node_count, count(DISTINCT document_id) AS document_count
FROM provision_node
WHERE node_kind = 'element'
GROUP BY tag_name
ORDER BY document_count DESC, node_count DESC, tag_name;

-- 23. Root and top-level child inventory, useful for old-law / unusual-document regression fixtures.
SELECT child.tag_name, count(*) AS node_count, count(DISTINCT child.document_id) AS document_count
FROM provision_node root
JOIN provision_node child
  ON child.document_id = root.document_id
 AND child.parent_node_id = root.node_id
WHERE root.parent_node_id IS NULL
GROUP BY child.tag_name
ORDER BY document_count DESC, child.tag_name;
