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

embedding生成・vector backend選定・hybrid retrievalは5.3b以降で実装する。
