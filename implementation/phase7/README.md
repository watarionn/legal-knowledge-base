# Phase 7 Daily Legal Assistant

Phase 1〜6で完成した法令ナレッジベース v1 を、日常利用できるWebアプリへ接続する最小実装です。

現段階ではLLMを必須にせず、まず **質問 → 対象法令 → strict temporal resolution → hybrid retrieval → Evidence Bundle → Phase 4原文** の経路をWeb UIから確認できることを目的とします。

## 現在の機能

- 自然言語の質問入力
- 任意の基準日指定
- 法令ID、法令番号、法令名、略称によるdeterministic law discovery
- 一意に確定できない場合の法令候補表示
- Phase 5.1 strict temporal resolverの再利用
- `ambiguous` / `unresolved` / `not-found` / 本文missingを推測で隠さない
- Phase 5.3 hybrid retrievalの再利用
- Evidence BundleからPhase 4 source node・XML path・RAW SHAへ戻る根拠表示
- Evidence-only動作。answer providerは未接続でも利用可能
- read-only DB transaction
- 1画面のresponsive Web UI
- Phase 7-2: 法令revision履歴タイムライン
- Phase 7-2: 履歴上の施行日から同じ質問をstrict再検索
- Phase 7-3: 2つの時点をstrictに解決してArticle単位でrevision比較
- Phase 7-3: 本則と附則の同番号を構造スコープで区別
- Phase 7-3: 変更Article一覧と個別文字diffを表示

## 構成

```text
implementation/phase7/
├── 001_application_contract.py
├── 002_query_service.py
├── 003_web_server.py
├── 004_application_contract_test.py
├── 005_query_service_test.py
├── 006_query_service_postgres_smoke.py
├── 012_law_history_service.py
├── 013_law_history_service_test.py
├── 014_law_history_postgres_smoke.py
├── 015_history_web_contract_test.py
├── 016_history_http_smoke.py
├── 017_article_compare_service.py
├── 018_article_compare_service_test.py
├── 019_article_compare_postgres_smoke.py
├── 020_article_compare_http_route_test.py
├── 021_article_compare_snapshot_smoke.py
└── web/
    ├── index.html
    ├── styles.css
    ├── app.js
    └── compare.js
```

## 起動

既存のPhase 3〜5 schemaとretrieval dataが入ったPostgreSQLを使用します。

PowerShell例:

```powershell
$env:LEGAL_KB_DATABASE_URL = 'postgresql://USER:PASSWORD@HOST:PORT/DATABASE'
python implementation/phase7/003_web_server.py
```

既定URL:

```text
http://127.0.0.1:8765
```

任意設定:

```powershell
$env:LEGAL_KB_HOST = '127.0.0.1'
$env:LEGAL_KB_PORT = '8765'
$env:LEGAL_KB_CHUNKING_CONFIG_SHA256 = '<64-char SHA-256>'
```

`LEGAL_KB_CHUNKING_CONFIG_SHA256`未指定時、DB内の`retrieval_chunk`に存在するchunking configが1種類だけなら自動利用します。複数存在する場合は勝手に選ばず、明示設定を要求します。

## API

### `GET /api/v1/health`

アプリ設定状態を返します。外部AI providerへ通信しません。

### `POST /api/v1/query`

例:

```json
{
  "question": "建設業法で請負契約に関係する規定を教えて",
  "as_of_date": "2024-04-01"
}
```

対象法令を安全に一意確定できない場合は`law-candidates`を返し、UIから候補を選択して再実行します。

### `GET /api/v1/laws/{law_id}/history?as_of_date=YYYY-MM-DD`

Phase 7-2の改正履歴APIです。Phase 3のrevision履歴、Phase 5.1 strict temporal result、Phase 4本文availabilityを1つのread responseとして返します。

`ambiguous`を1 revisionへ丸めず、historical body missing時にも別revisionへfallbackしません。UIの「この施行日で再検索」もrevision IDを直接固定せず、日付をquery APIへ渡してstrict resolverを再実行します。

### `GET /api/v1/laws/{law_id}/compare?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD`

Phase 7-3の条文比較APIです。両側の日付をPhase 5.1 strict temporal resolverへ通し、Phase 4原文からArticleを復元します。

任意で`article_num`と`scope_key`を指定できます。本則は`main + Num`、附則は`Supplementary.AmendLawNum + Num`で対応付けし、同番号が複数スコープに存在するときは自動選択しません。本文missing時にも別revisionへfallbackしません。

### `GET /api/v1/evidence/{evidence_id}`

現在のprocessで取得済みEvidenceの詳細を返します。Phase 7-1ではin-memory cacheのため、server再起動後の永続lookupは保証しません。

## Offline test

```bash
python implementation/phase7/004_application_contract_test.py -v
python implementation/phase7/005_query_service_test.py -v
python -m py_compile \
  implementation/phase7/001_application_contract.py \
  implementation/phase7/002_query_service.py \
  implementation/phase7/003_web_server.py
```

2026-09-10の実測では、application contract 7件、query service 4件の計11件がすべてpassし、3本のPython実装も`py_compile`を通過しました。

## PostgreSQL smoke

Phase 4 / Phase 5 smokeまで実行済みのDBに対して、Phase 7 query serviceを検証できます。

```bash
python implementation/phase7/006_query_service_postgres_smoke.py
```

`LEGAL_KB_DATABASE_URL`、`DATABASE_URL`、`LEGAL_KB_DSN`の順で接続先を解決します。

2026-09-10には、既存環境を汚さない一時PostgreSQL 16コンテナへPhase 4の実XML fixtureを投入し、Phase 5のtemporal/search/chunk/embedding/hybrid/Evidence smokeを通した後でPhase 7を検証しました。

確認済み:

- deterministic law discovery: resolved
- strict temporal resolution: resolved
- retrieval: ok
- Evidence Bundle再構築: passed
- revision / source XML SHA scope維持: passed
- answer provider未設定のEvidence-only動作: passed
- HTTP `/`: 200
- HTTP `/api/v1/health`: ok / database configured
- HTTP `/api/v1/query`: evidence-only / Evidence 3件
- citation truth: `phase3-phase4`

機械可読証跡は [`../../docs/validation/phase7-1-mvp-smoke-20260910.json`](../../docs/validation/phase7-1-mvp-smoke-20260910.json) に保存しています。

## 現在の制約

Phase 5のlexical retrievalはliteral substringを基礎にしているため、Phase 7-1のquery plannerは質問から法令名・日付・定型語を除き、検索に使う短い語句をdeterministicに抽出します。

これはLLMによる自由なquery rewriteを避けるための初期実装です。複数論点を含む質問、同義語しか含まれない質問、概念的な質問では検索recallが不足する可能性があります。今後の改善では、複数queryへの安全な分解やvector retrievalを追加しますが、citation truthをPhase 3 / 4から変更しません。

## セキュリティ境界

- DB接続情報やAPI keyをrepositoryへ保存しない
- browser入力からSQL文字列を直接組み立てない
- DB queryはread-only transactionで実行する
- browserへtraceback、DATABASE_URL、filesystem pathを返さない
- Web UIはsource/user textを`textContent`で描画し、HTMLとして直接挿入しない
- generated answerはsource truthとして扱わない

## 全量runtime検証

2026-09-10取得のe-Gov公式runtime snapshotを使った全量gateは完了しています。

- Phase 3: 9,551法令 / 53,718 revision、failed law 0、error 0
- Phase 4: 10,680文書 / 31,725,732 provision nodes / 41,886 attachments、failed 0、parse issue 0
- Phase 5.3 retrieval chunk: 10,680文書 / 6,070,516 chunks、failed 0
- trigram GIN indexとlexical / structural retrieval functionを全量DBへ適用済み
- 建設業法「請負契約」、民法第90条、労働基準法「労働時間」でEvidence取得を確認
- 2026-09-10時点でtemporal ambiguityとなる法令はrevisionを推測せずblocked-temporalで停止
- HTTP `/`、health、query、Evidence detail roundtripを全量DBで確認

Phase 4では6 revisionだけPhase 3 API履歴と照合できずdeferredになりました。6件はすべてruntime snapshot日より未来の施行日で、2026-09-10時点の利用対象本文を欠落させていません。別revision本文への代用は行いません。

query plannerは全量テストで見つかった「確認したい」が検索主題より優先される問題を修正し、意図語を除外するようにしました。chunking config検出も全chunk `GROUP BY`からindexを利用できる`DISTINCT ... LIMIT 2`へ変更しています。

機械可読な全量検証証跡は [`../../docs/validation/phase7-1-full-runtime-validation-20260910.json`](../../docs/validation/phase7-1-full-runtime-validation-20260910.json) に保存しています。

## Runtime corpus再構築

Phase 7の日常利用環境では、v1完成時の歴史snapshotをそのまま復元するのではなく、e-Govの最新公式「すべての法令データ / XMLのみ」を新しいruntime snapshotとして取得します。

取得したZIPはGitへ入れず、`007_official_bulk_snapshot.py`でSHA-256、ZIP CRC、XML件数、revision filename、重複を検証してPhase 4互換manifestを生成します。

```powershell
python implementation/phase7/007_official_bulk_snapshot.py `
  --archive "<runtime-data>/snapshot-YYYYMMDD/all_xml.zip" `
  --manifest-out "<runtime-data>/snapshot-YYYYMMDD/manifest.json" `
  --captured-on YYYY-MM-DD
```

全量runtime DBは`009_runtime_corpus_builder.py`で構築します。現MVPが必要とするmaterializationは、Phase 3履歴、Phase 4構造、Phase 5.3 retrieval chunkです。`search_unit`全量populationとembedding全量生成はPhase 7-1の必須条件ではありません。

```powershell
python implementation/phase7/009_runtime_corpus_builder.py `
  --archive "<runtime-data>/snapshot-YYYYMMDD/all_xml.zip" `
  --manifest "<runtime-data>/snapshot-YYYYMMDD/manifest.json" `
  --captured-on YYYY-MM-DD `
  --work-dir "<runtime-data>/run-YYYYMMDD"
```

`009_runtime_corpus_builder.py`はPhase 3 / Phase 4 / retrieval chunkをそれぞれresume可能な境界で実行します。chunk text用GIN indexは全chunk投入後に作成し、全量insert中のindex更新コストを避けます。

Phase 7-1ではvector channelを無効化しているため、embedding providerやembedding tableのpopulationがなくてもEvidence-only Web UIを利用できます。後続でvector retrievalを有効化するときは、同じcitation truthを維持したまま派生層として追加します。

runtime snapshotとDBについて:

- RAW ZIP、runtime manifest、Phase 3 RAW API response、DB volumeはGitへコミットしない
- 公開GitにはSHA-256、件数、検証結果だけを記録する
- runtime snapshotはv1検証snapshotと別identityとして扱う
- 新しいsnapshotで件数が変化しても、旧snapshotの記録を上書きしない
- DB接続情報はreportへ記録しない

全量chunk再構築だけを再実行する場合:

```powershell
python implementation/phase7/008_retrieval_chunk_full_rebuild.py `
  --result "<runtime-data>/run-YYYYMMDD/phase7-retrieval-chunks.json"
```

同一chunking configの既存documentは既定でskipするため、中断後の再開時に完成済みchunkを作り直しません。

## Phase 7-2 validation

2026-09-10の全量runtime DBで、民法の現時点resolved、2023-04-01の同日2 revision ambiguous、2024-04-01の本文missing非fallbackを確認しています。設計は [`../../docs/architecture/phase7-point-in-time-history.md`](../../docs/architecture/phase7-point-in-time-history.md) を参照してください。

公開用の統合証跡は [`../../docs/validation/phase7-2-history-validation-20260911.json`](../../docs/validation/phase7-2-history-validation-20260911.json) に保存しています。offline回帰27/27、history HTTP runnerの契約チェック10/10、GitHub Actions cost guard passedを記録しています。

## Phase 7-3 validation

2026-09-11に全量runtime DBから民法2 revisionのPhase 4ノード33,033件を抽出し、`021_article_compare_snapshot_smoke.py`で比較しました。

- 左16,462ノード / 1,374 Article
- 右16,571ノード / 1,377 Article
- スコープ重複0 / スコープ欠落0
- added 3 / changed 14 / unchanged 1,360
- 本則第891条: changed、文字diff 5 segment
- Article Num `1`をスコープなしで指定: 39候補のambiguousとして停止
- `155:157`等のe-Gov範囲Numを原値のまま扱う

HTTP routeは`020_article_compare_http_route_test.py`で実`003_web_server.py`を起動して検証します。DB接続とcompare serviceだけをfakeに分離し、health、静的UI、`scope_key`伝搬、範囲Num、400/503境界を確認します。

設計は [`../../docs/architecture/phase7-article-revision-compare.md`](../../docs/architecture/phase7-article-revision-compare.md)、機械可読証跡は [`../../docs/validation/phase7-3-compare-validation-20260911.json`](../../docs/validation/phase7-3-compare-validation-20260911.json) を参照してください。
