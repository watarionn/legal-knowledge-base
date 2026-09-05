# Phase 4 Full Relational Import

2026-09-05に、保存済み4 ZIPの10,711 XMLをPostgreSQL 16へ全量投入しました。

## 結果

| 指標 | 値 |
| --- | ---: |
| input XML | 10,711 |
| Phase 3 API履歴へ照合済み | 10,705 |
| RAWのみ保持してdefer | 6 |
| 通常import failure | 0 |
| normalized `law_document` | 10,705 |
| normalized `provision_node` | 32,116,330 |
| deferred 6 XMLのparser node | 73,184 |
| 全入力としてaccounted nodes | **32,189,514** |
| `attachment` | **42,571** |
| `source_file_member` | 10,711 |
| `xml_parse_issue` | 0 |
| DB size after import | 17,354,128,407 bytes |

事前corpus scanの32,189,514ノード、42,571 `src`参照と完全一致しました。

## 6件を無理に結合しない

次の6 revision IDはPhase 3の53,711 API履歴に存在せず、2026-09-05の公式e-Gov API再照合でも存在を確認できませんでした。

- `211AC0000000070_20270518_505AC0000000031`
- `314AC0000000073_20270518_505AC0000000031`
- `342AC0000000035_21171231_507AC0000000013`
- `342AC0000000035_21171231_507AC0000000032`
- `342AC0000000081_20270518_505AC0000000031`
- `411AC0000000097_20270620_506AC0000000060`

XMLから`law_revision`を捏造せず、個別XMLのRAW `source_file`と`source_file_member`を保持し、`LAW_REVISION_NOT_RECONCILED`として`reconciliation_issue`へ記録しました。6件のXML自体はすべてwell-formedで、parserでは合計73,184ノード・attachment 0件です。

## Compact storage v2

初期schemaを500 XMLで実測したところ約1 GBまで膨張したため、32Mノード全量に耐えるよう物理表現をcompact化しました。

- 物理PK: `document_pk + document_order`
- 親参照: `parent_document_order`
- logical `node_id`: SHA-256を32-byte `bytea`で保持
- full `xml_path`: 各行へ反復保存せず`path_index`と親鎖から再構成
- `legal_kb.provision_node_xml_path()`で必要時に決定的pathを取得
- `text_original`: text-bearing nodeのdenormalized cache。構造コンテナでは子孫本文の重複を避けてNULL可
- mixed contentの正本は`mixed_content_jsonb` + child nodes + immutable RAW

同じ500 XMLの実測ではDB全体が約222 MBとなり、その後10,705文書を16 GB級で完走できました。

## 全量validation

次の不整合は0件でした。

- RAW source SHA / immutable backlink
- `(law_revision_id, source_xml_sha256)`重複
- root数
- sibling ordinalの欠落
- document orderの欠落
- `law_document.node_count`不一致
- attachment count不一致
- element tag欠落
- `OldNum` / `OldStyle`投影とattributes原値の不一致
- attachment revision不一致
- source-file-member backlink / duplicate
- Phase 4での`text_search_normalized`非NULL
- deferred 6件のRAW backlink不一致

さらにmixed-content child segmentは32,105,625件で、10,705文書の全non-root node数32,105,625と一致しました。4件の公式回帰fixtureでは、DBへcompact保存した`node_id`と`provision_node_xml_path()`の結果がparserのlogical node ID / xml_pathと全ノードで一致しました。

## `src=""`について

42,571 attachment参照のうち3,770件（199文書）は公式XML自体が`src=""`を持っています。これは欠損を推測補完せず、source valueの空文字列をそのまま保持します。

## XSD status

今回のrelational importでは各`law_document.schema_validation_status`は`not-checked`です。Phase 2で固定済みの同一snapshotに対する公式v3 XSD結果 **9,932 valid / 779 invalid** は引き続き集計証跡として保持していますが、個別文書へのstatus backfillは別工程です。XSD invalidは取り込み拒否条件ではありません。

機械可読結果は [`phase4_full_relational_import_result.json`](phase4_full_relational_import_result.json) にあります。
