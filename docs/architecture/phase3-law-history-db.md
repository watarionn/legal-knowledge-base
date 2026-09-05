# Phase 3: Law / Revision Database

Phase 3は、e-Gov法令API Version 2の法令系列と全履歴をPostgreSQLへ保存する層です。

## 主要テーブル

- `ingestion_run`: 取り込みrun
- `source_file`: APIレスポンスやRAW sourceの来歴
- `law`: 法令系列
- `law_revision`: 個別改正履歴
- `source_assertion`: ソース別の観測値
- `reconciliation_issue`: 競合・曖昧性

## Identity

`law_id`は15文字のe-Gov法令IDです。

`law_revision_id`は次の形式を扱います。

```text
LAW_ID_YYYYMMDD_AMENDING_LAW_ID
```

中央日付と末尾IDを解析しますが、解析値はAPI原値と別列に保存します。

## 時点情報

`revision_id_effective_date`、APIの`amendment_enforcement_date`、派生した`valid_from`は別物として保持します。

- 非baselineでAPI施行日とID日付が一致: `confirmed-api`
- API施行日がないがID日付が使える: `confirmed-revision-id`
- 日付が競合: 勝者を選ばず`ambiguous`
- suffix `000000000000000`: 根拠なしにoriginal/data-baselineを断定しない

`valid_to_exclusive`は同一法令内の次のstrictly greater `valid_from`から導出します。同日revision同士をゼロ長区間にしません。

## Provenance

API、XML、CSV、派生値が競合しても観測値を消しません。canonical値の選択と、ソースが主張した値を分離します。

## Full bootstrap evidence

2026-09-04実行では:
- 9,551法令
- 53,711履歴
- 最終取得失敗0
- error-class reconciliation issue 0
- same-day group 3,064
- unresolved amendment reference 46,598行

詳細は [`../validation/phase3_full_bootstrap_result.public.json`](../validation/phase3_full_bootstrap_result.public.json) を参照してください。

## 注意点

現在のresumable runnerは、既存`law_revision`の存在をAPI履歴取得済み判定に使います。将来、API由来でないrevisionを同じテーブルへ先行投入する場合は、API履歴完了を明示するcheckpointへ変更する必要があります。
