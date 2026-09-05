# XML / XSD Validation

## 対象

保存済み法令XMLスナップショット10,711件を対象に、XML well-formednessと公式日本法令XML Schema v3への適合性を検証しました。

入力snapshotの同一性は [`xml_snapshot_manifest.public.json`](xml_snapshot_manifest.public.json) の4 ZIP SHA-256で固定しています。

## 結果

| 項目 | 件数 |
| --- | ---: |
| XML総数 | 10,711 |
| well-formed | 10,711 |
| XSD valid | 9,932 |
| XSD invalid | 779 |

## 方針

XSD invalidは「公式RAW XMLが存在しない」ことを意味しません。

そのため本プロジェクトでは:

1. RAW XMLをそのまま保持する
2. XSD validation statusとエラーを来歴として記録する
3. well-formedであれば、XSD invalidだけを理由にnormalized structureを捨てない
4. XSDへ合わせるために公式RAWを自動修正しない

という方針を採用します。

## Phase 4との関係

Phase 4の`law_document`には`schema_validation_status`と`schema_validation_errors_jsonb`を持たせています。これにより、`invalid`と`parse failed`を別の状態として扱えます。

2026-09-05のfull corpus structural scanではXSD検証自体は再実行していません。同一4 ZIP SHA-256を確認したうえで、この9,932 / 779分布を既存baselineとして参照しています。
