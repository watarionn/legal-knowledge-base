# 法令ナレッジベース

日本の法令について、e-Gov法令API・法令XMLなどの一次情報を基盤に、**改正履歴、時点指定、XML構造、出典追跡、検索/RAG**を一貫して扱える法令知識基盤を構築するプロジェクトです。

## 目標

単なる「最新法令の全文検索」ではなく、次の問いに根拠付きで答えられる基盤を目指します。

- ある日付時点で、どの法令版が適用対象だったか
- その条文がどの改正履歴に属するか
- 検索結果がどの原XML・法令履歴・取得時点に由来するか
- 現行法だけでなく、旧法令、附則、別表、図表、mixed contentを損失なく扱えるか
- 将来、官報・国会会議録・帝国議会会議録・国立国会図書館の立法資料へ根拠付きで接続できるか

## 現在地

正式な工程は6 Phaseです。

| Phase | 名称 | 状態 |
| --- | --- | --- |
| 1 | 要件・アーキテクチャ設計 | 完了 |
| 2 | 原本・全量データ検証 | 完了 |
| 3 | 法令・履歴DB実装 | 完了 |
| 4 | XML構造DB | **進行中** |
| 5 | 時点検索＋検索/RAG | 未着手 |
| 6 | 官報・議会資料連携 | 未着手 |

Phase 4では、`law_document` / `provision_node` / `attachment` を中心に、法令XMLを**一般化した順序付きツリー**として保持します。Articleを必須階層にはせず、未知要素・未知属性、`OldNum` / `OldStyle`、mixed content、tail text、表・図も同じモデルで保存します。

詳細は [`docs/architecture/roadmap.md`](docs/architecture/roadmap.md) を参照してください。

## 実測済みデータ

2026-09-05時点の検証では、保存済みXMLスナップショット10,711件について次を確認しています。

- XML parse: **10,711 / 10,711 成功**
- parse failure: **0**
- 総XMLノード数: **32,189,514**
- タグ: **114種類**
- 属性: **29種類**
- 最大: **201,013ノード / 文書**
- MainProvision配下のどこにもArticleがない文書: **1,219件**
- 非空tail textを含む文書: **2,626件**
- `OldNum`: **458文書**
- `OldStyle`: **1,155文書**
- `src`参照: **42,571件 / 2,176文書**

同じスナップショットの公式v3 XSD検証では、9,932件適合、779件非適合でした。**公式RAW XMLは、XSD非適合だけを理由に拒否・自動修正しません。** 検証状態とエラーを来歴として保持します。

Phase 3の全量bootstrapでは、e-Gov法令API Version 2から9,551法令・53,711履歴をPostgreSQLへ取り込み、最終取得失敗0、error-class reconciliation issue 0を確認しています。

詳細な集計値は [`docs/validation/`](docs/validation/) に置いています。

## ディレクトリ

```text
.
├── docs/
│   ├── architecture/       # 公開設計文書
│   └── validation/         # 公開可能な検証証跡・集計値
├── implementation/
│   ├── phase3/             # law / law_revision、API bootstrap
│   └── phase4/             # XML parser、構造DB、corpus scan、DB importer
└── .github/workflows/      # 自動テスト・PostgreSQL smoke
```

## クイックテスト

Phase 3のオフラインテスト:

```bash
python implementation/phase3/005_bootstrap_import_test.py -v
python implementation/phase3/008_resumable_full_bootstrap_test.py -v
```

Phase 4 XML parserのsynthetic tests:

```bash
python implementation/phase4/006_xml_parser_test.py -v
```

PostgreSQLを使う手順は各Phaseの実装ファイルとCIを参照してください。

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
- 不明なものを推測して確定値にしない

## ライセンス

コード・文書・データ由来fixtureのライセンスは、公開方針を確認したうえで明示的に決定します。**現時点ではLICENSEファイルを置いていません。**

## 注意

このプロジェクトは法令データの構造化・検索基盤を開発するものであり、個別案件について法律上の助言を提供するものではありません。
