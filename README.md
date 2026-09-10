# 法令ナレッジベース

日本の法令について、e-Gov法令API・法令XMLなどの一次情報を基盤に、**改正履歴、時点指定、XML構造、出典追跡、検索/RAG**を一貫して扱える法令知識基盤を構築するプロジェクトです。

Phase 1〜6で法令ナレッジベース v1 基盤を完成し、現在はその知識基盤を日常的に使えるWebアプリへ変換する **Phase 7 Daily Legal Assistant Web App** に進んでいます。

## 目標

単なる「最新法令の全文検索」ではなく、次の問いに根拠付きで答えられる基盤を目指します。

- ある日付時点で、どの法令版が適用対象だったか
- その条文がどの改正履歴に属するか
- 検索結果がどの原XML・法令履歴・取得時点に由来するか
- 現行法だけでなく、旧法令、附則、別表、図表、mixed contentを損失なく扱えるか
- 将来、官報・国会会議録・帝国議会会議録・国立国会図書館の立法資料へ根拠付きで接続できるか
- 自然言語の質問から、回答・根拠条文・対象revision・RAW provenanceまで一続きで確認できるか

## 現在地

v1基盤の正式工程はPhase 1〜6で、すべて完了しています。Phase 7は完成済みv1の上に利用者向けapplication layerを構築するpost-v1フェーズです。

| Phase | 名称 | 状態 |
| --- | --- | --- |
| 1 | 要件・アーキテクチャ設計 | 完了 |
| 2 | 原本・全量データ検証 | 完了 |
| 3 | 法令・履歴DB実装 | 完了 |
| 4 | XML構造DB | **完了** |
| 5 | 時点検索＋検索/RAG | **完了** |
| 6 | 官報・議会資料連携 | **完了** |
| 7 | Daily Legal Assistant Web App | **Phase 7-1 MVP実装中** |

Phase 7-1では、AIを法令の正本にせず、既存のstrict temporal resolver、hybrid retrieval、Evidence Bundleを薄いWeb application layerから再利用します。自然言語の質問から対象法令を安全に特定し、回答生成providerが未設定でも、根拠原文・revision・XML path・RAW SHAまで確認できるEvidence-only経路を先に完成させます。設計は [`docs/architecture/phase7-daily-legal-assistant.md`](docs/architecture/phase7-daily-legal-assistant.md)、画面構成は [`docs/architecture/phase7-webapp-screen-layout.md`](docs/architecture/phase7-webapp-screen-layout.md)、API境界は [`docs/architecture/phase7-webapp-api.md`](docs/architecture/phase7-webapp-api.md) を参照してください。

Phase 5.1では、`law_id + as_of_date`からrevision候補を解決するstrict resolverを実装しました。Phase 3の実データにはsame-day複数revisionとtemporal ambiguityがあるため、**一意に確認できない候補を勝手に1 revisionへ丸めません**。時点revisionの確定とPhase 4本文のavailabilityも分離し、本文未収録時に別revisionへfallbackしません。

2026-09-05のPostgreSQL 16.15 smokeでは、最初のrevision以前の`not-found`、exclusive境界、same-day `ambiguous`、低品質単一候補の`unresolved`、本文missingの非fallbackを確認し、8件のsynthetic resolver testsもfailure 0でした。

Phase 5.2の全量実測とPhase 5.3a〜dを完了しました。strict temporal resolution後の単一revisionを対象にlexical / structural / vector候補を統合し、Evidence Bundleを経由して最終根拠をPhase 4原文・RAW provenanceへ戻すRAG回答基盤まで実装しています。Phase 5 closure監査結果は [`docs/validation/phase5-closure.md`](docs/validation/phase5-closure.md) に記録しています。詳細は [`docs/architecture/roadmap.md`](docs/architecture/roadmap.md) と [`docs/architecture/phase5-vector-rag-retrieval.md`](docs/architecture/phase5-vector-rag-retrieval.md) を参照してください。

Phase 6.1のExternal Source Foundationを完了し、Phase 6.2では国会会議録・帝国議会会議録の実provider adapterを実装しました。`issueID`を会議record、`speechID`をspeech subdocumentとして保持し、raw API payloadはPhase 3 `source_file`へimmutable snapshotとして保存します。2026-09-09のlive probeでは国会9発言・帝国議会94発言、計103 speech observationsを取得し、全件でraw SHAへのprovenance欠落0を確認しました。詳細は [`docs/architecture/phase6-external-sources.md`](docs/architecture/phase6-external-sources.md) と [`docs/validation/phase6-parliamentary-live.md`](docs/validation/phase6-parliamentary-live.md) を参照してください。

Phase 6.3では官報発行サイトのOfficial Gazette Adapterを実装しました。サイトのcrawler禁止を尊重し、発行日・種別・号数・PDF URLを明示する`explicit-issue-only`方式でraw PDFを取得します。PDF SHAを`source_file`へ保存し、電子署名・タイムスタンプの構造観測と暗号学的validityを分離します。live probeの詳細は [`docs/validation/phase6-official-gazette-live.md`](docs/validation/phase6-official-gazette-live.md) を参照してください。

Phase 6.4ではNDLサーチのSRUをbounded discovery、OAI-PMH `GetRecord`をmetadata evidence取得に分離しました。OAI `identifier`をlogical document identityとし、`dcndl_v3` raw XMLをimmutable `source_file` snapshotへ保存します。削除済みOAI recordも過去snapshotを消さずtombstone observationとして保持します。live probeの詳細は [`docs/validation/phase6-ndl-metadata-live.md`](docs/validation/phase6-ndl-metadata-live.md) を参照してください。

Phase 6.5ではexternal documentと法令・revisionのrelationをevidence-backed candidateとして生成し、manual/provider-explicit reviewとretrievalを分離します。自動照合は完全一致のみを使用し、candidate/conflicted/rejectedはcitation-readyにしません。live probeの詳細は [`docs/validation/phase6-cross-source-linkage-live.md`](docs/validation/phase6-cross-source-linkage-live.md) を参照してください。

2026-09-10のclosure監査でPhase 6.1〜6.5の全offline回帰、fresh PostgreSQL 18、exact-head CI、live validation inventoryを再確認し、Phase 6を完了扱いにしました。詳細は [`docs/validation/phase6-closure.md`](docs/validation/phase6-closure.md) を参照してください。

## 実測済みデータ

2026-09-05時点の保存済みXMLスナップショット10,711件について:

- XML parse: **10,711 / 10,711 成功**
- 総XMLノード数: **32,189,514**
- タグ: **114種類** / 属性: **29種類**
- 最大: **201,013ノード / 文書**
- MainProvision配下のどこにもArticleがない文書: **1,219件**
- 非空tail textを含む文書: **2,626件**
- `OldNum`: **458文書** / `OldStyle`: **1,155文書**
- `src`参照: **42,571件 / 2,176文書**

Phase 4 full relational importでは:

- input XML: **10,711**
- Phase 3 API履歴へ照合して正規化: **10,705**
- API履歴に存在せずRAW provenance付きdefer: **6**
- 通常import failure: **0**
- normalized `provision_node`: **32,116,330**
- deferred 6 XMLのparser node: **73,184**
- accounted nodes: **32,189,514**（事前scanと一致）
- `attachment`: **42,571**（事前scanと一致）
- `source_file_member`: **10,711**
- full DB size: **17,354,128,407 bytes**

全量結果は [`docs/validation/phase4-full-relational-import.md`](docs/validation/phase4-full-relational-import.md) に記録しています。

同一snapshotの公式v3 XSD検証は9,932件適合、779件非適合です。公式RAW XMLはXSD非適合だけを理由に拒否・自動修正しません。なおPhase 4 relational importでは個別XSD statusを再実行・backfillしていません。

Phase 3の全量bootstrapでは、e-Gov法令API Version 2から9,551法令・53,711履歴をPostgreSQLへ取り込み、最終取得失敗0を確認しています。temporal metricsとして、`confirmed-api` 43,301件、ambiguous 10,410件、same-day group 3,064 group / 7,345 revisionを観測しています。

## ディレクトリ

```text
.
├── docs/
│   ├── architecture/       # 公開設計文書
│   └── validation/         # 公開可能な検証証跡・集計値
├── implementation/
│   ├── phase3/             # law / law_revision、API bootstrap
│   ├── phase4/             # XML parser、構造DB、full importer
│   ├── phase5/             # temporal resolver、検索/RAG
│   ├── phase6/             # 官報・議会資料・NDL external source foundation
│   └── phase7/             # Daily Legal Assistant application API / Web UI
└── .github/workflows/      # 自動テスト・PostgreSQL smoke
```

## クイックテスト

```bash
python implementation/phase3/005_bootstrap_import_test.py -v
python implementation/phase3/008_resumable_full_bootstrap_test.py -v
python implementation/phase4/006_xml_parser_test.py -v
python implementation/phase4/012_full_relational_import_test.py -v
python implementation/phase5/004_temporal_resolver_test.py -v
python implementation/phase6/004_external_source_identity_test.py -v
python implementation/phase6/010_parliamentary_adapter_test.py -v
python implementation/phase6/017_official_gazette_adapter_test.py -v
python implementation/phase6/024_ndl_metadata_adapter_test.py -v
python implementation/phase6/031_cross_source_linkage_test.py -v
python implementation/phase7/004_application_contract_test.py -v
python implementation/phase7/005_query_service_test.py -v
```

Phase 7-1のローカル起動方法とPostgreSQL smoke手順は [`implementation/phase7/README.md`](implementation/phase7/README.md) を参照してください。2026-09-10のMVP smoke証跡は [`docs/validation/phase7-1-mvp-smoke-20260910.json`](docs/validation/phase7-1-mvp-smoke-20260910.json) に保存しています。

PostgreSQL smokeは `.github/workflows/postgres-smoke.yml` を参照してください。Phase 5.1の機械可読証跡は [`docs/validation/phase5_temporal_resolution_smoke_result.json`](docs/validation/phase5_temporal_resolution_smoke_result.json) に保存しています。

## データの扱い

このリポジトリには、巨大な法令RAW ZIP、DB dump、取得済み添付バイナリはコミットしません。代わりに、再現に必要なSHA-256、件数、取得元の種類、検証方法、公開可能なfixtureを保持します。

一次情報と役割分担は [`docs/data-sources.md`](docs/data-sources.md) にまとめます。

## 設計原則

- `law_id` と `law_revision_id` を分離する
- 法令名・法令番号を内部主キーにしない
- API原値、履歴ID解析値、派生した時点情報を別々に保持する
- CSV・XML・APIの競合値を上書きせず、来歴として残す
- 原文と検索用正規化文を分離する
- normalized dataから必ずRAW原本とSHA-256へ戻れるようにする
- ambiguousな時点境界を推測で確定値にしない
- 本文未収録revisionを別revisionの本文で代用しない
- AI生成文を法令原文やcitation truthの代替正本にしない

## ライセンス

コード・文書・データ由来fixtureのライセンスは、公開方針を確認したうえで明示的に決定します。**現時点ではLICENSEファイルを置いていません。**

## 注意

このプロジェクトは法令データの構造化・検索基盤を開発するものであり、個別案件について法律上の助言を提供するものではありません。
