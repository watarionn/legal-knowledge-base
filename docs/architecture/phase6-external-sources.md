# Phase 6 External Sources

Phase 6は、官報・国会会議録・帝国議会会議録・NDL書誌メタデータを、Phase 3/4の法令本文とは別の一次資料系列として取り込む。

## 実装順序

1. **6.1 External Source Foundation**
   - provider registry
   - logical external document identity
   - immutable source snapshot
   - external document → law / revision / provision node relation assertion
2. **6.2 Parliamentary Proceedings Adapters**
   - 国会会議録 `issueID` / `speechID`
   - 帝国議会会議録 `issueID` / `speechID`
3. **6.3 Official Gazette Adapter**
   - 官報発行サイトの発行日・種別・号数・PDFを取得
   - 電子正本のsource_file SHA、電子署名/タイムスタンプ関連metadataを保持
4. **6.4 NDL Legislative Metadata Adapter**
   - NDLサーチ SRU / OAI-PMH metadata
   - provider identifierとraw XMLを保持
5. **6.5 Cross-source Linkage / Retrieval**
   - identifier/metadata/text match候補
   - evidence-backed relation review
   - Phase 5 retrievalへの外部source envelope統合

## 6.1 data model

`external_source_provider`は取得元のauthority、transport、provider ID戦略を定義する。認証情報や有料サービスのcredentialは保存しない。

`external_document`はprovider内の論理レコードであり、`provider_code + provider_document_id`から決定的IDを作る。title/date等は検索用projectionで、引用正本ではない。

`external_document_snapshot`は各取得時のraw payloadをPhase 3 `source_file`へ結ぶ。payload SHAが変われば新snapshotとして共存し、過去観測を上書きしない。

`source_relation`はexternal documentと`law` / `law_revision` / `provision_node`の論理的な関連候補を表す。法的確定性はrelation rowではなく`source_relation_assertion`の証拠とstatusで扱う。

`source_relation_assertion`はprovider明示、identifier match、metadata match、text match、manual、derivedの観測を別々に保持する。自動照合はcandidateから始める。

## Source-specific identity policy

### 官報

2025-04-01以降の官報は内閣府の官報発行サイト上の電子データが正本。サイト上では発行日、種別（本紙・号外・政府調達・特別号外等）、号数、PDFが公開される。

6.3ではサイトに公式document IDがない前提で、`issued-date + publication-kind + issue-number`を**derived provider key**として扱う。これは公式IDと呼ばない。

### 国会会議録 / 帝国議会会議録

NDL APIが返す`issueID`をdocument identityに使い、`speechID`は6.2でsubdocument identityとして追加する。API返却JSON/XML自体をsource_fileとして保存する。

### NDLサーチ

OAI-PMHのidentifier等、providerが返す識別子をlogical document identityに使う。DC-NDL等のmetadata projectionは検索用であり、raw XML snapshotを置換しない。

## Confirmation policy

- `provider-explicit`: confirmed可
- `manual`: confirmed可
- `identifier-match`: candidate
- `metadata-match`: candidate
- `text-match`: candidate
- `derived`: candidate

検索score、embedding similarity、文字列類似度を法的confidenceへ読み替えない。

## 6.1 exit gate

- provider registry: implemented
- deterministic external document identity: implemented
- immutable snapshot → Phase 3 source_file: implemented
- law / revision / provision node relation targets: implemented
- conflicting relation assertions coexist: implemented
- automatic match default candidate: implemented
- Phase 3/4 target + raw SHA provenance roundtrip: implemented
- real provider network ingestion: deferred to 6.2以降
