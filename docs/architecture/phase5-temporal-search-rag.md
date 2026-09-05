# Phase 5: 時点検索・検索/RAG

Phase 5は、Phase 3の法令履歴とPhase 4のXML構造をつなぎ、**指定日時点の法令版を解決したうえで、検索結果・RAG回答を原文と来歴へ戻せる層**を構築します。

## Phase 5の順序

Phase 5は次の3段階で進めます。

1. **Phase 5.1 Temporal Resolution**
   - `law_id + as_of_date`から候補`law_revision_id`を返す
   - 一意解決できない場合は曖昧性を明示する
   - Phase 4本文が存在しないrevisionを別状態として扱う
2. **Phase 5.2 Lexical / Structural Search**
   - revision-awareな検索unitを構築する
   - 法令名、条・項・号、表、附則などの構造と検索本文を結ぶ
   - lexical search結果から`law_revision_id` / `document_pk` / `document_order` / RAW SHAへ戻れるようにする
3. **Phase 5.3 Vector / RAG Retrieval**
   - embedding modelやvector実装を交換可能な派生層として追加する
   - vector結果だけを根拠にせず、必ずPhase 4原文・Phase 3履歴へbacklinkする
   - model名、model version、chunking versionを来歴として保存する

Phase 5.1が確定する前に、検索結果から時点版を推測してはいけません。

## Temporal Resolutionの前提

Phase 3全量bootstrapでは53,711 revisionを取得していますが、時点境界には実データ上の曖昧性があります。

- `temporal_resolution_quality = confirmed-api`: 43,301
- ambiguous: 10,410
- same-day group: 3,064 group / 7,345 revision
- baseline suffix由来のunknown: 3,109

したがって、`revision_sequence`やAPI配列順だけを使って同日revisionを1件へ丸めることは禁止します。

## Resolverの結果状態

### `resolved`

候補revisionが1件で、`temporal_resolution_quality`が次のいずれかである場合だけです。

- `confirmed-api`
- `confirmed-revision-id`

このときだけ`selected_revision_id`を返します。

### `ambiguous`

同一日時点で候補revisionが複数存在します。

候補をすべて返し、1件を自動選択しません。

### `unresolved`

候補は1件ですが、その時点品質が厳密選択に足りません。

例:
- `baseline-boundary`
- `ambiguous`
- `unknown`

revisionを候補として提示できますが、`selected_revision_id`は返しません。

### `not-found`

`valid_from <= as_of_date < valid_to_exclusive`を満たすrevisionがありません。

過去最古版や直近版への自動fallbackは禁止します。

## 本文availabilityは時点解決と分離する

Phase 3には53,711 revisionがありますが、現在のPhase 4 snapshotは10,705 revisionを正規化しています。

そのため、時点revisionが一意に解決できても本文がPhase 4に存在しないことがあります。この場合:

- temporal statusは`resolved`のまま
- content statusは`missing`
- 別revisionのXMLを代用しない

同一revisionに複数の成功済み`law_document`が存在する場合も、勝手に1件を選ばず`multiple`として扱います。

## Citation / provenance契約

検索・RAGが最終的に返す根拠には最低限、次を保持します。

- `law_id`
- `law_revision_id`
- as-of date
- temporal resolution status / quality
- `document_id`
- `source_xml_sha256`
- `document_pk`
- `document_order`
- `provision_node_xml_path(document_pk, document_order)`

検索用正規化文やembeddingは引用の正本ではありません。引用本文はPhase 4 normalized infosetまたはimmutable RAWへ戻して取得します。

## Search/RAG設計上の禁止事項

- ambiguousな時点をLLMに推測させて1 revisionへ丸めない
- 本文未収録revisionを近い日付の別revisionで代替しない
- embedding/chunk本文をRAW原文の代替正本にしない
- `law_title`だけをidentityとして使用しない
- 現行版検索結果を過去時点回答へ無条件で混ぜない

## Phase 5.1 validation

2026-09-05にPostgreSQL 16.15でPhase 3 → Phase 4 → Phase 5.1 DDLを連続適用し、strict resolverの実DBsmokeを通過しました。

確認済み:
- 最初のrevision以前の日付は`not-found`
- confirmedな過去revisionは、本文未収録でもrevision自体は`resolved`
- `valid_to_exclusive`境界当日は新revisionだけを選択
- confirmedな単一候補＋成功済み本文は`resolved + available`
- same-day複数候補は`ambiguous`で、`selected_revision_id`を返さない
- 低品質な単一候補は`unresolved`で、`selected_revision_id`を返さない
- 8件のsynthetic resolver testsはfailure 0

機械可読証跡は [`../validation/phase5_temporal_resolution_smoke_result.json`](../validation/phase5_temporal_resolution_smoke_result.json) に保存しています。

## Phase 5.1 exit gate

- PostgreSQL関数がas-of候補をinterval条件で返す: **passed**
- same-day複数候補を保持する: **passed**
- strict resolverが曖昧候補を自動選択しない: **passed**
- temporal statusとcontent availabilityを分離する: **passed**
- 本文missing時にfallbackしない: **passed**
- synthetic testsとPostgreSQL smokeが通る: **passed**

**Phase 5.1の技術ゲートは完了です。次工程はPhase 5.2 Lexical / Structural Searchです。**
