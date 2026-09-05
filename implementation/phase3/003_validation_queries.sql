-- 法令ナレッジベース Phase 3 validation queries
-- Read-only checks for legal_kb.law and legal_kb.law_revision.

SET search_path TO legal_kb, public;

-- 1. 基本件数
SELECT count(*) AS law_count FROM law;
SELECT count(*) AS law_revision_count FROM law_revision;

-- 2. ID形式違反。DDLのCHECKが有効なら0件であること。
SELECT law_id
FROM law
WHERE law_id !~ '^[0-9A-Z]{15}$';

SELECT law_revision_id
FROM law_revision
WHERE law_revision_id !~ '^[0-9A-Z]{15}_[0-9]{8}_[0-9A-Z]{15}$';

-- 3. revision ID内law_idとFK列の不一致。0件であること。
SELECT law_revision_id, law_id
FROM law_revision
WHERE split_part(law_revision_id, '_', 1) <> law_id;

-- 4. revision ID末尾と解析済みamending law IDの不一致。0件であること。
SELECT law_revision_id, revision_id_amending_law_id
FROM law_revision
WHERE split_part(law_revision_id, '_', 3) <> revision_id_amending_law_id;

-- 5. 非baseline履歴でAPI amendment_law_idと履歴ID末尾が不一致。
SELECT
    law_revision_id,
    amendment_law_id,
    revision_id_amending_law_id
FROM law_revision
WHERE revision_id_amending_law_id <> '000000000000000'
  AND amendment_law_id IS NOT NULL
  AND amendment_law_id <> revision_id_amending_law_id;

-- 6. 非baseline履歴で履歴ID中央日とAPI施行日が不一致。
SELECT
    law_revision_id,
    revision_id_effective_date,
    amendment_enforcement_date,
    temporal_resolution_quality
FROM law_revision
WHERE revision_id_amending_law_id <> '000000000000000'
  AND amendment_enforcement_date IS NOT NULL
  AND revision_id_effective_date <> amendment_enforcement_date;

-- 7. 同一法令内の同日revision群。
--    0件を必須としない。Phase 5で時点解決する前に必ず件数と対象を把握する。
SELECT
    law_id,
    valid_from,
    count(*) AS revisions_on_same_day,
    array_agg(law_revision_id ORDER BY law_revision_id) AS revision_ids
FROM law_revision
WHERE valid_from IS NOT NULL
GROUP BY law_id, valid_from
HAVING count(*) > 1
ORDER BY revisions_on_same_day DESC, law_id, valid_from;

-- 8. 時点区間異常。0件であること。
SELECT law_revision_id, valid_from, valid_to_exclusive
FROM law_revision
WHERE valid_from IS NOT NULL
  AND valid_to_exclusive IS NOT NULL
  AND valid_to_exclusive < valid_from;

-- 9. revision_sequence重複。0件であること。
SELECT law_id, revision_sequence, count(*) AS duplicate_count
FROM law_revision
WHERE revision_sequence IS NOT NULL
GROUP BY law_id, revision_sequence
HAVING count(*) > 1;

-- 10. amendment_law_idがlawに未解決の参照。
--     取り込み失敗条件ではない。件数とIDを来歴として記録する。
SELECT DISTINCT r.amendment_law_id
FROM law_revision r
LEFT JOIN law a ON a.law_id = r.amendment_law_id
WHERE r.amendment_law_id IS NOT NULL
  AND a.law_id IS NULL
ORDER BY r.amendment_law_id;

-- 11. temporal quality分布。
SELECT temporal_resolution_quality, count(*)
FROM law_revision
GROUP BY temporal_resolution_quality
ORDER BY temporal_resolution_quality;

-- 12. revision date kind分布。
SELECT revision_date_kind, count(*)
FROM law_revision
GROUP BY revision_date_kind
ORDER BY revision_date_kind;

-- 13. current revision status分布。値を固定列挙せず観測値を確認する。
SELECT current_revision_status, count(*)
FROM law_revision
GROUP BY current_revision_status
ORDER BY current_revision_status;

-- 14. API原値と派生値を混ぜていないかの監査用一覧。
SELECT
    law_revision_id,
    amendment_enforcement_date AS api_enforcement_date,
    revision_id_effective_date AS id_effective_date,
    valid_from AS derived_valid_from,
    valid_to_exclusive AS derived_valid_to_exclusive,
    revision_date_kind,
    temporal_resolution_quality
FROM law_revision
ORDER BY law_id, valid_from NULLS LAST, law_revision_id;

-- 15. 未解消reconciliation issue件数。
SELECT severity, issue_code, count(*)
FROM reconciliation_issue
WHERE resolved_at IS NULL
GROUP BY severity, issue_code
ORDER BY severity, issue_code;
