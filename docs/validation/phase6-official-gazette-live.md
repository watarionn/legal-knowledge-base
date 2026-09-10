# Phase 6.3 Official Gazette live validation

実施日: 2026-09-10

## 公式提供面の確認

官報発行サイトの「ご利用に当たって」「よくあるご質問」を基準にした。

- 官報は原則8:30に官報発行サイトへ掲載されることで発行される。
- 官報の真正性確保のため電子署名・タイムスタンプが付与される。
- PDFはブラウザからダウンロード可能。
- 検索ロボットやクローラによるデータ収集は禁止されている。
- 発行後90日経過後は、プライバシー配慮対象の記事に閲覧制約が生じ得る。

参照:
- https://www.kanpo.go.jp/guidance.html
- https://www.kanpo.go.jp/faq.html

このため6.3 adapterは一覧巡回・リンク探索を実装せず、operatorが発行日・種別・号数・PDF URLを明示する`explicit-issue-only`方式とした。
## live probe

対象:
- 発行日: 2026-08-10
- 種別: 本紙 (`regular`)
- 号数: 第1765号
- 頁: 1-32
- URL: https://www.kanpo.go.jp/20260810/20260810h01765/pdf/20260810h01765full00010032.pdf

取得結果:
- byte size: 4,750,926
- SHA-256: `7d48f5b33c5ca6147c151017e8920287080aec03a270bb293f4bd67c34ea227b`
- signature field count: 1
- document timestamp count: 1
- ByteRange count: 2
- ETSI CAdES detached count: 1
- cryptographic verification status: `not-checked`
- crawler used: false

署名・タイムスタンプの存在はPDF byte構造から観測しただけであり、証明書チェーン・失効・タイムスタンプ局を含む暗号学的検証が成功したことを意味しない。
## PostgreSQL provenance

isolated fresh PostgreSQL 18へ、Phase 3 / Phase 4 / Phase 6.1 / Phase 6.3 DDLを適用してlive PDFを保存した。

- `official_gazette_asset`: 1
- `official_gazette_certificate_observation`: 1
- 自動生成された`source_relation`: 0
- source file SHAとdownloaded PDF SHA: 一致
- raw PDFはGitへコミットしていない

provider document IDは `derived:2026-08-10:regular:1765` とした。この値は官報発行サイトが提供する公式IDではなく、6.3 adapter内部のderived keyである。

## regression

- Phase 6.3 adapter unit tests: 13 / 13 passed
- Phase 3→4→5→6.3 fresh PostgreSQL 18: `PHASE63_FULL_FRESH_CLUSTER_SMOKE_OK`
- live explicit PDF ingestion: `PHASE63_LIVE_GAZETTE_INGEST_OK`

## deferred

- 電子証明書の暗号学的validation backend
- 記事単位抽出・indexing
- 官報から法令への自動linkage

これらを追加してもraw PDF SHAとderived projectionの境界は変更しない。
