# Phase 5.3 Vector / RAG Retrieval

Phase 5.3は、Phase 5.1のstrict temporal resolutionとPhase 5.2のlexical / structural searchの上に、交換可能なchunk・embedding・vector retrievalを追加する。

## 実装順序

1. **5.3a Retrieval Chunk Foundation**
   - model-independent chunkをPhase 4 nodeから決定的に生成する
   - chunkからrevision、XML node、RAW SHAへ必ず戻れるようにする
2. **5.3b Embedding Adapter**
   - provider / model / version / dimensionsを記録する
   - embeddingは`chunk_id`へ従属する再生成可能な派生層とする
3. **5.3c Hybrid Retrieval / Context Assembly**
   - strict temporal resolution後のrevisionだけを対象にする
   - lexical / structural / vector hitを同一provenance envelopeへ統合する
4. **5.3d RAG Answer Contract**
   - 回答本文と根拠chunkを分離する
   - 引用はchunk本文ではなくPhase 4原文へ戻して確定する

## 5.3aの設計

`retrieval_chunk`はembeddingモデルに依存しない。chunk identityには`chunking_version`、`chunking_config_sha256`、revision、source XML SHA、anchor/start/end node ID、retrieval text hashを含める。`chunking_config_sha256`はalgorithm versionとruntime parameter（現在は`soft_max_chars`）を固定し、同じalgorithm version内の設定差を再現可能にする。

chunkは最寄りの法的・構造的anchorを越えない。初期anchorはArticle / Paragraph / Item / Subitem / Supplementary Provision / appendix / table / figure等とし、未知構造は削除せずdirect parentへfallbackする。

character limitはtokenizer非依存のsoft limitとして1,200文字を既定値にする。分割はPhase 4 source nodeの境界だけで行い、単一nodeが上限を超える場合はnode内部を推測分割せず`is_oversize=true`で保持する。

## Chunk provenance

各chunkは最低限、次へbacklinkする。

- `law_id`
- `law_revision_id`
- `document_pk`
- `source_xml_sha256`
- anchor / start / end `document_order`
- contributing `source_document_orders[]`
- anchor / start / end logical `node_id`
- `chunking_version`
- `chunking_config_sha256` / `soft_max_chars`
- `retrieval_text_sha256`

`legal_kb.retrieval_chunk_provenance()`でanchor/start/endのdeterministic XML pathを再構成できる。

## Retrieval textの位置付け

`retrieval_text`はPhase 4の`text_original`をsource-unitごとに最小空白正規化し、検索・embedding用に連結した派生値である。`context_prefix`も構造ラベルから作る派生値である。

これらは引用正本ではない。最終引用は`source_document_orders[]`とPhase 4 normalized infoset / immutable RAWへ戻して取得する。

## 禁止事項

- chunkerがrevisionを選択すること
- ambiguous / unresolved時点をvector scoreで解消すること
- 本文missing時に別revisionのchunkへfallbackすること
- embedding textを引用原文として扱うこと
- model変更時に過去embeddingのmetadataを上書きすること
- unknown XML structureをchunking都合で捨てること

## 5.3a exit gate

- deterministic chunk ID: implemented
- structural anchorを跨がない: implemented
- unknown structure fallback: implemented
- source node list / RAW SHA backlink: implemented
- PostgreSQL provenance roundtrip: implemented
- embedding model非依存: implemented

5.3aは完了。embedding生成・vector backend選定・hybrid retrievalは5.3b以降で実装する。


## 5.3b Embedding Adapter

Embedding Adapterはprovider-neutralなinterfaceとし、provider / model / model version / dimensions / input policyを`embedding_profile`へimmutable metadataとして保存する。profile identityはこれらの生成条件からSHA-256で決定する。

既定input policyは`context-prefix-plus-retrieval-text-v1`とする。`context_prefix`があれば`context_prefix + "\n\n" + retrieval_text`、なければ`retrieval_text`そのものを入力とし、そのexact UTF-8 bytesを`embedding_input_sha256`で固定する。入力は検索用派生値であり引用対象ではない。

provider出力はfiniteなfloat32へ正規化し、dimensions完全一致を必須にする。vectorはIEEE-754 binary32 big-endian列のSHA-256を`embedding_values_sha256`として固定する。PostgreSQLでは5.3cでvector backendを選ぶまでtransport-neutralな`real[]`として保持する。

同じ`embedding_profile_id + chunk_id`へ異なるinput hashまたはvector hashを返した場合は上書きせずdriftとして失敗させる。model version変更は別profileを作り、過去embeddingを残したまま共存させる。認証情報はprofile、DB、public artifactのいずれにも保存しない。

CIでは`deterministic-test / sha256-float32` providerだけを使用する。このproviderは品質評価やproduction retrievalには使用せず、adapter contract、hash、dimension、drift detection、provenance roundtripの検証専用とする。

### 5.3b exit gate

- provider/model/version/dimensions/input policyのimmutable profile: implemented
- exact embedding input SHA: implemented
- canonical float32 vector SHA: implemented
- dimension / nonfinite rejection: implemented
- same-profile silent drift rejection: implemented
- model-version coexistence: implemented
- embedding → chunk → revision → RAW SHA provenance roundtrip: implemented
- credentials persistence: prohibited

実embedding provider接続とvector backend / ANN indexの選定は、provider contractを変えず次工程へ接続する。


## 5.3c Hybrid Retrieval / Context Assembly

5.3cは検索チャネルより先にstrict temporal resolutionを実行し、`resolved + content_status=available`の単一revision/documentだけを検索scopeとする。`ambiguous` / `unresolved` / `not-found` / content missingではlexical・structural・vectorの全チャネルを実行しない。

同一documentに異なるchunk設定が共存できるため、hybrid retrievalは`chunking_config_sha256`を必須入力とし、異なるchunk setを同一rankingへ混在させない。vectorを使う場合は`embedding_profile_id`とquery vectorを必ず対で指定する。

候補はlexical / structural / vectorごとに独立順位を保持し、異種raw scoreを直接比較せずweighted Reciprocal Rank Fusionで統合する。tie breakはchunk identityで決定的にする。context assemblyは文字数budgetを持つが、引用境界を推測してchunk内部を切断しない。

初期`exact-real-array-v1` vector backendは`real[]`をcosine exact scanするcorrectness validation backendであり、全量production ANN用途ではない。ANN backendは同じscope/provenance contractを満たす差し替え実装として追加する。

各context itemは`chunk_id`、revision、document、source XML SHA、source node order、deterministic XML pathを保持する。context本文とranking scoreは引用正本ではなく、5.3dで最終引用を確定するときはPhase 4 normalized infoset / immutable RAWへ戻る。

### 5.3c exit gate

- strict temporal gate before all retrieval channels: implemented
- chunking config isolation: implemented
- lexical / structural / vector common chunk envelope: implemented
- deterministic weighted RRF: implemented
- context budget without mid-chunk truncation: implemented
- exact vector correctness backend: implemented
- Phase 4 / RAW provenance roundtrip: implemented
- ANN backend: deferred behind replaceable interface

5.3c完了後は5.3d RAG Answer Contractへ進み、回答文と根拠・最終引用を分離する。


## 5.3d RAG Answer Contract

5.3dは5.3cのretrieval contextと生成回答の間にEvidence Bundle境界を置く。contextの`retrieval_text`は検索用派生値なので引用には使わず、`source_document_orders[]`からPhase 4 `provision_node`を再取得し、logical node ID、deterministic XML path、source XML SHAを持つ根拠bundleへ固定する。

Answer Providerはprovider/model/versionを記録する交換可能interfaceとし、回答draftはclaimごとにEvidence IDを1件以上参照する。未知Evidence ID、重複claim ID、根拠なしclaim、空回答はfinalize時にblockedとする。生成回答はsource truthではなく、Evidence BundleもPhase 4 / immutable RAWへの参照envelopeである。

`citation-ready`は、回答claimが既知Evidence Bundleだけを参照し、bundleがstrict temporal scope内のPhase 4 source nodeとRAW SHAへ戻れることを機械検証した状態を表す。根拠が主張を意味的に支持するかというsemantic entailmentは自動でtrueにせず、`semantic_entailment_verified=false`を明示する。

### 5.3d exit gate

- retrieval contextからPhase 4 source nodeへのEvidence Bundle再構築: implemented
- deterministic Evidence ID: implemented
- claimごとのknown Evidence ID必須: implemented
- unknown / duplicate / unsupported evidence reference blocking: implemented
- generated answerとsource truthの分離: implemented
- semantic entailmentを自動assertしない: implemented
- fresh PostgreSQL / full DB provenance roundtrip: implemented
