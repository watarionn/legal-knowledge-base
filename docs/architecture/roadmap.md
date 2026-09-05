# 6 Phase Roadmap

法令ナレッジベースの正式な工程はPhase 1〜6です。

## Phase 1 要件・アーキテクチャ設計

目的は、一次情報、履歴、検索、出典を分離した全体設計を確定することです。

主な成果:
- `source_file` / `ingestion_run` を起点とするprovenance設計
- `law` と `law_revision` の分離
- RAW原本、構造化データ、検索用派生データの責務分離

状態: 完了

## Phase 2 原本・全量データ検証

目的は、bulk XML、公式XSD、API履歴を実データで検証し、取り込み前提を固定することです。

主な完了条件:
- XML well-formedness確認
- XSD検証結果の記録
- bulk revision IDとAPI履歴の照合
- XSD非適合RAWを拒否・自動修正しない方針の固定

状態: 完了

## Phase 3 法令・履歴DB実装

目的は、法令系列と全履歴をPostgreSQLへ保存し、API原値と派生時点情報を分離することです。

主要entity:
- `law`
- `law_revision`
- `source_assertion`
- `reconciliation_issue`

状態: 完了

## Phase 4 XML構造DB

目的は、法令XMLを損失なく構造化することです。

主要entity:
- `law_document`
- `provision_node`
- `attachment`

完了条件:
- 古法令・現代法令・附則・表・図を保持できる
- Article層なしを扱える
- unknown element / attributeを落とさない
- mixed content / tail textを保持できる
- `OldNum` / `OldStyle`を保持できる
- normalized nodeからRAW XMLとSHA-256へ戻れる
- PostgreSQL実データsmokeと全量import validationが通る

2026-09-05に10,711 XMLを全量処理し、10,705 revisionをcompact v2 PostgreSQLへ正規化、Phase 3 API履歴に存在しない6 revisionをRAW provenance付きでdeferしました。通常import failureは0、32,189,514ノードと42,571 attachment参照の全入力accountingが事前scanと一致し、全量relational validationも通過しています。

状態: 完了

## Phase 5 時点検索＋検索/RAG

目的は、指定日時点の適用法令版を解決し、全文・構造・ベクトル検索から原文・履歴・出典へ戻れる検索回答基盤を構築することです。

### Phase 5.1 Temporal Resolution

`law_id + as_of_date`からrevision候補を解決します。Phase 3ではsame-day複数revisionやtemporal ambiguityが実在するため、一意に確定できない場合は候補を保持し、`revision_sequence`やAPI配列順で勝手に1件へ丸めません。

完了条件:
- interval条件で全候補を返す
- confirmedな単一候補だけを`resolved`とする
- same-day複数候補を`ambiguous`とする
- 単一でも低品質境界は`unresolved`とする
- 本文availabilityをtemporal resolutionと分離する
- 本文未収録時に別revisionへfallbackしない

2026-09-05にPostgreSQL 16.15でPhase 3→4→5.1 DDLを連続適用し、8件のsynthetic testsとtemporal resolution smokeを通過しました。same-day複数候補、exclusive境界、本文missing、低品質単一候補を含め、strict resolverがrevisionを推測選択しないことを確認しています。

状態: **完了**

### Phase 5.2 Lexical / Structural Search

revision-awareな検索unitを構築し、検索hitから`law_revision_id`、XML構造path、RAW SHAへ戻れるようにします。

状態: **次工程**

### Phase 5.3 Vector / RAG Retrieval

embedding/chunkを交換可能な派生層として追加し、RAG回答の根拠をPhase 3/4へbacklinkします。

状態: 未着手

## Phase 6 官報・議会資料連携

目的は、官報、国会会議録、帝国議会会議録、国立国会図書館の立法資料を、法令本文とは別ソースとして関連付けることです。

想定entity:
- `external_document`
- `source_relation`

状態: 未着手
