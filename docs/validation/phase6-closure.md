# Phase 6 Closure Validation

検証日: 2026-09-10

Phase 6「官報・議会資料連携」のclosure監査結果を記録する。
Phase 6.1〜6.5のcorrectness / provenance / retrieval境界について、main `bb0ebf7d54abfe184a7c7403d5b28002a096105e` を基準に再検証した。

## 判定

**Phase 6 基盤実装: 完了**

官報、国会会議録、帝国議会会議録、NDL metadataをPhase 3/4法令本文とは別の外部一次情報系列として保持し、raw取得物・projection・relation evidence・retrieval状態を分離できている。

## Closure gate

- provider-scoped logical external document identity: passed
- raw external payload → immutable `source_file` SHA: passed
- external snapshot provenance roundtrip: passed
- speech / bibliographic metadata projectionをsource truthへ昇格しない: passed
- 国会・帝国議会 `issueID` / `speechID` identity: passed
- provider固有field / unknown field preservation: passed
- provider request serialisation / throttle boundary: passed
- 官報 `explicit-issue-only` 取得境界: passed
- 官報署名構造presenceとcryptographic validityの分離: passed
- NDL OAI `identifier` identity / persistent tombstone: passed
- automatic linkageはexact signalでも必ずcandidate: passed
- manual / provider-explicit evidenceと自動match evidenceの分離: passed
- confirmed + rejected coexistence → conflicted: passed
- confirmed-only default retrieval: passed
- candidate / rejected / conflicted citation-ready false: passed
- Phase 3/4 law source truth不変: passed

## Exact-head CI再確認

Phase 6の各実装PRについて、merge前に固定したhead SHAのGitHub Actionsをclosure時に再確認した。

| Phase | PR | head SHA | Tests | PostgreSQL Smoke |
| --- | ---: | --- | --- | --- |
| 6.1 | #21 | `b293240d1add07846fd82941c73d08c8a360c21e` | #83 success | #83 success |
| 6.2 | #22 | `c77f96cda9a811974d2ec1c34cb719dc7c318c3d` | #85 success | #85 success |
| 6.3 | #23 | `304655677335595ac6b7bafb11ba560b2f350118` | #87 success | #87 success |
| 6.4 | #24 | `b6c1ebf8409faa3472592f3b5134431070e057e3` | #89 success | #89 success |
| 6.5 | #25 | `4fa091ba06bed9309e6505122ac0206f2165fd1d` | #91 success | #91 success |

## Closure再実測

### 全offline回帰

最新mainからPhase 3〜6.5のoffline test suiteを再実行し、`PHASE65_FULL_REGRESSION_OK`を確認した。

### fresh PostgreSQL 18

空のtemporary PostgreSQL 18 clusterへPhase 3 → 4 → 5 → 6.1 → 6.2 → 6.3 → 6.4 → 6.5のDDLを連続適用し、各Phase 6 DB smokeを同じschema stack上で実行した。

`PHASE65_CROSS_SOURCE_LINKAGE_SMOKE_OK`と`PHASE65_FULL_FRESH_CLUSTER_SMOKE_OK`を確認した。

## Live validation inventory

closureでは外部providerへ重複アクセスせず、各Phaseで2026-09-09〜10に取得済みのlive validationとraw SHA証跡を再確認した。

- Phase 6.2: 国会9発言 + 帝国議会94発言、合計103 speech observations、raw SHA provenance missing 0
- Phase 6.3: 官報本紙第1765号 4,750,926 bytes、SHA-256 `7d48f5b33c5ca6147c151017e8920287080aec03a270bb293f4bd67c34ea227b`
- Phase 6.3: signature field 1 / DocTimeStamp 1 / ByteRange 2 / CAdES detached 1、cryptographic validityは`not-checked`
- Phase 6.4: OAI identifier `oai:ndlsearch.ndl.go.jp:R000000004-I026731256`、raw XML 6,250 bytes
- Phase 6.5: 国会会議録250発言中「行政手続法」完全一致1件 → candidate relation 1件
- Phase 6.5: 未review candidateはdefault retrieval 0、`citation_ready=false`

## Deferred but non-blocking

以下はPhase 6 correctness / provenance closureのblocking条件には含めない。

- 官報PDFのarticle-level本文抽出・索引化
- 官報電子署名・タイムスタンプの暗号学的validator接続
- 外部providerの大規模・定期harvest orchestration
- candidate relationのreview UI / operator workflow
- fuzzy / semantic cross-source matchingの品質評価
- external retrievalのserving API / UI

これらを追加する場合も、自動matchを法的確定へ昇格させず、raw source SHAとreview evidenceを保持するPhase 6境界を維持する。

## 次工程

現在のroadmapはPhase 6.5までであり、正式なPhase 7は未定義である。
次工程では、Phase 6のsource-truth境界を維持したままproduction ingestion / review / servingの優先順位を設計する。
