# Phase 6.5 Cross-source Linkage Live Validation

検証日: 2026-09-10

## 目的

実際の国会会議録を使い、外部資料中の法令名完全一致が自動的に`confirmed`へ昇格しないことを検証する。

Phase 6.2の国会会議録adapterで会議recordを取得し、Phase 6.5 linkerでPhase 3 law catalogと照合した。live validation用DBは隔離したfresh PostgreSQL 18を使用した。

## 対象

- provider: `kokkai-ndl`
- issueID: `122114080X01420260716`
- 開催日: 2026-07-16
- target e-Gov law ID: `405AC0000000088`
- target title: `行政手続法`
- target law number: `平成五年法律第八十八号`

法令マスタ値はlive validation用fresh DBへseedし、production DBは変更していない。
## 結果

- meeting speech count: 250
- exact law-title mention count: 1
- inserted relation count: 1
- inserted assertion count: 1
- effective state: `candidate`
- default external retrieval count: 0
- candidate citation-ready: false
- raw meeting payload SHA-256: `41b16f9dccb9b9f0fe5b82ae36fe0dcb183ecdf54b78eaec5ebb7ce45e2990c7`
- database URL recorded: false
- credentials recorded: false

Result marker:

`PHASE65_LIVE_CROSS_SOURCE_LINKAGE_OK`

## 判定

**passed**

完全一致の法令名であっても、それだけでは「その外部資料が法的に当該法令と確定的関係を持つ」とは断定しない。自動照合は`text-match / candidate`に留まり、manual reviewまたはprovider-explicit evidenceがない限りcitation-ready retrievalへ入らない。
