# Phase 7-4 関連資料探索

## 目的

Phase 6で構築した官報・国会会議録・帝国議会会議録・NDL資料の外部source foundationを、Phase 7のDaily Legal Assistantから探索できるようにする。

Phase 7-4では、法令本文と外部資料の役割を混同しない。
法令本文のcitation truthは引き続きPhase 3/4であり、外部資料はPhase 6の独立したsource truth/provenance系列として表示する。

利用者は次を確認できる。

- 法令全体に関連付けられた外部資料
- strict temporal resolverで一意に解決されたrevisionに関連する外部資料
- relationのeffective stateとcitation-ready可否
- relation assertionのstatus / basis / evidence
- external snapshot、Phase 3 source_file、RAW SHA-256
- providerが公開するcanonical URL

## 非目標

Phase 7-4は、新しい自動linkageアルゴリズムを作らない。
Phase 6.5のexact identifier / law number / law title等の既存ルールを再利用する。

候補relationをWeb表示したことを理由にconfirmedへ昇格させない。
AIや検索scoreもrelation confidenceへ変換しない。

## Retrieval policy

既定取得は`effective_state = confirmed`だけとし、`citation_ready=true`のrelationだけを通常表示する。

candidate / conflicted / rejectedは、利用者が「候補も表示」を明示した場合だけ取得する。
その場合も`citation_ready=false`を維持し、UIで「引用不可」を明示する。

同じexternal documentにlaw-levelとrevision-levelの複数relationが存在する場合、資料カードは1枚にまとめる。ただし各relationのtarget、relation kind、effective state、citation-readyは個別に保持する。

relation詳細では`source_relation_assertion`を取得し、assertion status / basis / source locator / evidence / observed_atを表示する。

## Temporal boundary

`GET /api/v1/laws/{law_id}/related-materials`は、指定日をPhase 5.1 strict temporal resolverへ渡す。

law-level relationはtemporal statusにかかわらず検索できる。
revision-level relationはresolverが`resolved`で一意な`selected_revision_id`を返した場合だけ検索する。

`ambiguous` / `unresolved` / `not-found`を別revisionへ丸めない。
その場合、UIは法令全体の資料だけを表示したことを明示する。

## API

`GET /api/v1/laws/{law_id}/related-materials?as_of_date=YYYY-MM-DD&include_nonconfirmed=false`

`include_nonconfirmed`は`true` / `false`だけを許可し、既定は`false`。
responseはmaterial単位でgroupし、relation配列に各関連付けを保持する。

`GET /api/v1/source-relations/{source_relation_id}`

relation単位の詳細を返す。external document identity、target、relation kind、effective state、citation-ready、snapshot、source_file SHA、assertion一覧を含む。

browserへDATABASE_URL、filesystem path、tracebackは返さない。

## UI

質問が法令へ一意に解決された場合、関連資料パネルを表示する。

- confirmed資料を既定表示
- 「候補も表示」は既定OFF
- candidate等は「引用不可」を表示
- source family、発行日、provider、relation targetを表示
- canonical URLはHTTP/HTTPSだけを外部リンク化
- 「関連付けの根拠」でassertionとRAW SHAを確認

provider由来のtitle、metadata、assertion evidenceは`textContent`で描画し、HTMLとして注入しない。
関連資料取得に失敗しても、質問回答、Evidence、改正履歴、条文比較を破棄しない。

## Runtime external-source bootstrap

Phase 7の日常利用runtimeはPhase 3〜5だけで構築されていたため、Phase 7-4でPhase 6 schemaを追加materializeする。

`025_runtime_external_source_bootstrap.py`はPhase 6.1〜6.5のschemaを依存順に扱う。
各stepをrequired relation/view集合で検査し、次の3状態に分類する。

- `empty`: 未導入。DDLを適用可能
- `ready`: 完全導入済み。skip
- `partial`: 一部だけ存在。自動修復せずfail-closed

bootstrap前にPhase 3/4の`ingestion_run`、`source_file`、`law`、`law_revision`、`provision_node`、`provision_node_xml_path()`の存在を確認する。
DB credentialはreportへ保存しない。

schema materializeは外部資料を自動取得しない。実資料のingestionはPhase 6のprovider adapter / persistence / linkage経路を使う。
過去のvalidation fixtureを本番資料として流用しない。

## Runtime verification

2026-09-11の日常利用runtimeへPhase 6.1〜6.5 schemaを追加した。
適用前後で既存主要件数は不変だった。

- law: 9,551
- law_revision: 53,718
- law_document: 10,680
- retrieval_chunk: 6,070,516

transaction内でcandidate / confirmed、law / revision relation、RAW SHA provenanceを挿入してretrieval viewとprovenance functionを検証し、最後にROLLBACKした。
smoke dataはruntimeへ残していない。

## Phase 7-4 完了条件

1. Phase 6 retrieval envelopeをapplication layerから再利用する
2. confirmed-onlyを既定表示する
3. non-confirmedは明示opt-inかつcitation-ready=falseを維持する
4. strict temporal ambiguityをrevision資料の推測で埋めない
5. relation assertionとRAW SHA provenanceまでdrill-downできる
6. 外部URL・provider textを安全に描画する
7. runtimeへPhase 6 schemaを再現可能にmaterializeできる
8. 既存Phase 3〜5 runtime件数を変更しない
9. 実runtime DBでtransactional retrieval smokeが通る
10. Phase 7-1〜7-3回帰とGitHub Actions cost guardを維持する
