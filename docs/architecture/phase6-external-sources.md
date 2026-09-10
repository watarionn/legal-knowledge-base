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


## 6.2 Parliamentary Proceedings Adapters

国会会議録と帝国議会会議録は、公式APIの会議recordを`external_document`へ、各発言を`external_document_part`へ投影する。会議の`issueID`と発言の`speechID`はproviderが返す一意識別子として扱う。

`external_document_part`は親meetingから独立したsource truthではなく、同じimmutable raw response snapshotから再構築可能なsubdocument projectionである。各speech observationは`snapshot_id`、本文SHA、raw record SHAへbacklinkする。

共通projectionは会期、院名、会議名、開催日、発言順、発言者、所属、役職、本文、会議/発言URL等を保持する。国会会議録固有の`speakerRole`、帝国議会会議録固有の`speakerElection` / `officeTerm`、その他未知fieldはprovider metadata JSONへ残す。

取得clientは直列実行し、既定3秒のrequest間隔を強制する。live probeはCIでは実行せず、公開可能な件数・SHA・再現手順だけを`docs/validation/phase6-parliamentary-live.md`へ保存する。

### 6.2 exit gate

- official `issueID` meeting identity: implemented
- official `speechID` subdocument identity: implemented
- Diet / Imperial Diet provider differences preserved: implemented
- unknown provider fields preserved: implemented
- raw API response → Phase 3 `source_file` SHA: implemented
- speech observation → raw snapshot provenance: implemented
- silent speech drift detection within same snapshot: implemented
- serial request throttle: implemented
- fresh PostgreSQL 18 Phase 3→6.2 smoke: passed
- real NDL API live probe for both providers: passed
- cross-source legal linkage automation: implemented in 6.5

## 6.3 Official Gazette Adapter

官報発行サイトは2025-04-01以降、官報の発行面そのものとして扱う。6.3ではサイト全体をcrawlerで巡回せず、operatorが明示した発行日・種別・号数・PDF URLだけを取得する。

官報側に安定した公式document IDが公開されているとはみなさず、`derived:{issued_on}:{publication_kind}:{issue_number}`を内部provider keyとする。これは公式IDではないことをschema・contract・文書で明記する。

冊子PDFまたは分割PDFは`official_gazette_asset`としてpage range付きで保持し、各raw PDFをPhase 3 `source_file`と`external_document_snapshot`へbacklinkする。分割PDFを1つのpayloadへ結合して正本を作り直すことはしない。

電子署名・タイムスタンプは`official_gazette_certificate_observation`へ別観測として保存する。PDF byte構造からsignature field、DocTimeStamp、ByteRange、CAdES detachedの存在を数えても、証明書の暗号学的validityとは判定しない。validation backend未実行時は`not-checked`を維持する。

発行後のプライバシー配慮による閲覧制約を迂回せず、記事単位の大量抽出・indexingは6.3の対象外とする。
### 6.3 exit gate

- explicit issue identity with derived-key labeling: implemented
- no crawler / no link discovery: implemented
- official host/date/PDF URL validation: implemented
- booklet and split PDF page ranges: implemented
- raw PDF → Phase 3 `source_file` SHA: implemented
- Gazette asset → immutable snapshot provenance: implemented
- signature/timestamp structure observation: implemented
- structure presence != cryptographic validity: enforced
- fresh PostgreSQL 18 Phase 3→6.3 smoke: passed
- real explicit Gazette PDF live probe: passed
- automatic legal linkage: implemented in 6.5
- article-level extraction/indexing: deferred

## 6.4 NDL Legislative Metadata Adapter

SRUはprovider recordを発見するためのbounded searchに限定し、logical document identityにはOAI-PMH headerの`identifier`を使う。SRU record projectionを引用正本にはしない。

OAI-PMH `GetRecord`の`dcndl_v3` responseをraw XMLとしてPhase 3 `source_file`へ保存し、`external_document_snapshot`へbacklinkする。bibliographic fieldsは`ndl_metadata_observation`へprojectionする。

OAI repositoryのdeleted recordはtombstone observationとして追加し、既存snapshotを物理削除しない。取得clientは直列実行し、既定3秒以上のrequest間隔を維持する。bulk `ListRecords`は6.4の自動経路では無効とする。

### 6.4 exit gate

- SRU bounded discovery with result cap: implemented
- OAI `identifier` logical identity: implemented
- `dcndl_v3` raw XML → Phase 3 `source_file` SHA: implemented
- metadata observation → immutable snapshot provenance: implemented
- persistent deleted-record tombstone: implemented
- serial request throttle: implemented
- bulk `ListRecords` disabled: implemented
- fresh PostgreSQL 18 Phase 3→6.4 smoke: passed
- real SRU exact discovery + OAI GetRecord live probe: passed
- automatic legal linkage: implemented in 6.5

## 6.5 Cross-source Legal Linkage / Retrieval

自動linkageはexact e-Gov law ID / 法令番号 / 法令名 / 改正法令識別子だけを信号にし、fuzzy matchや検索scoreを法的confidenceへ変換しない。国会・帝国議会は`mentions`、NDL metadataは`bibliographic-reference`としてcandidateを生成する。6.3官報は記事本文抽出を行っていないため自動text linkage対象外とする。

relation statusはcandidate / confirmed / rejectedをassertionとして追記し、confirmedとrejectedが共存する場合は`conflicted`とする。retrievalはconfirmedだけを既定表示・citation-readyとし、non-confirmedは明示opt-inでもcitation-ready=falseを維持する。

### 6.5 exit gate

- exact identifier / law-number / law-title matching only: implemented
- all automatic linkage forced candidate: implemented
- amendment identifier → revision candidate: implemented
- manual confirmed/rejected review without overwrite: implemented
- confirmed+rejected conflict state: implemented
- confirmed-only default retrieval: implemented
- candidate/conflicted/rejected citation-ready false: implemented
- raw external snapshot SHA provenance in retrieval envelope: implemented
- fresh PostgreSQL 18 Phase 3→6.5 smoke: passed
- real National Diet exact-title live candidate probe: passed
- Gazette automatic text linkage: deferred until article-level extraction exists


## Phase 6 closure

2026-09-10にPhase 6.1〜6.5を最新mainから再監査した。external raw payloadはPhase 3 `source_file` SHAへ戻り、projection・relation evidence・retrieval stateはsource truthと分離されたままである。自動linkageはcandidateから開始し、confirmed-only retrievalとconflict blockingを維持する。

全offline回帰、fresh PostgreSQL 18、各PRのexact-head Tests / PostgreSQL Smoke、既存live validation inventoryを再確認し、blocking gapなしとしてPhase 6を完了した。詳細は [`../validation/phase6-closure.md`](../validation/phase6-closure.md) を参照。
