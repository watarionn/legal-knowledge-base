# Phase 7-1 Daily Legal Assistant MVP

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

## 構成

```text
implementation/phase7/
├── 001_application_contract.py
├── 002_query_service.py
├── 003_web_server.py
├── 004_application_contract_test.py
├── 005_query_service_test.py
└── web/
    ├── index.html
    ├── styles.css
    └── app.js
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

### `GET /api/v1/evidence/{evidence_id}`

現在のprocessで取得済みEvidenceの詳細を返します。Phase 7-1ではin-memory cacheのため、server再起動後の永続lookupは保証しません。

## テスト

```bash
python implementation/phase7/004_application_contract_test.py -v
python implementation/phase7/005_query_service_test.py -v
python -m py_compile \
  implementation/phase7/001_application_contract.py \
  implementation/phase7/002_query_service.py \
  implementation/phase7/003_web_server.py
```

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

## 次の検証

Phase 7-1 MVPの次のgateは、実際の全量PostgreSQLを使ったlocal smokeです。

確認項目:

1. 法令名から`law_id`を一意解決できる
2. 指定日がPhase 5 strict temporal resolverへそのまま渡る
3. resolved revision以外を検索しない
4. Evidence BundleがPhase 4原文へroundtripする
5. Web UIで原文・revision・RAW SHAを確認できる
6. ambiguous / unresolved / no-hitの表示が崩れない

このsmokeを通過した後に、answer provider接続の要否とquery planner改善を判断します。
