# Phase 4: XML Structure Database

Phase 4は、法令XMLを検索しやすくしながら、原文構造とRAW provenanceを損失なく保持する層です。

## 汎用順序付きツリー

10,711 XML全量scanでは、MainProvision配下のどこにもArticleがない文書が1,219件あり、附則、表、図、Ruby、数式、旧形式属性、mixed contentも実在しました。そのためArticle / Paragraph / Item専用階層ではなく、全XML要素を一般化した順序付きツリーとして扱います。

## `law_document`

1つの照合済み法令XML原本に対応し、`law_revision_id`、`source_file_id`、source XML SHA-256、parser version、parse/XSD status、root情報、node/attachment件数を保持します。RAW XMLは置換せず、必ずimmutable `source_file`へ戻れるようにします。

## `provision_node`: compact storage v2

32Mノード全量に耐えるため、論理IDと物理参照を分離しています。

- 物理PK: `document_pk + document_order`
- 親参照: `parent_document_order`
- sibling順: `ordinal`
- 同expanded-name兄弟index: `path_index`
- logical `node_id`: parserが決定的に作るSHA-256を32-byte `bytea`で保持
- `tag_name` / `namespace_uri` / `attributes_jsonb` / `OldNum` / `OldStyle`等を保持
- `text_original`: text-bearing node用のdenormalized cache。構造コンテナでは子孫本文の大量重複を避けてNULLを許容
- `text_search_normalized`: Phase 5用。Phase 4ではNULL

初期物理schemaは500 XMLで約1GBまで膨張しました。compact v2では同じ500 XMLが約222MBとなり、10,705 normalized文書を約17.35GBで完走しました。

## Mixed content

`mixed_content_jsonb`へ`text` / `child` / `tail`を文書順に保持します。child/tail参照はdocument-local `document_order`を使用します。空白のみのtailもtrimしません。

全量DBではmixed-content child segment **32,105,625件**が全non-root normalized node **32,105,625件**と一致しました。

## `xml_path`

full pathを32M行へ反復保存せず、親鎖・expanded name・`path_index`から必要時に決定的に再構成します。

```sql
SELECT legal_kb.provision_node_xml_path(document_pk, document_order);
```

例:

```text
/Law[1]/LawBody[1]/MainProvision[1]/Article[2]/Paragraph[1]
```

4件の公式回帰fixtureでは、DBに保存したlogical `node_id`と再構成`xml_path`がparser出力と全ノードで一致しました。

## `attachment`

XMLの`src`観測を参照行として分離し、`source_src`原値、解決後locator、availability status等を保持します。解決しても`source_src`を上書きしません。

全量42,571参照のうち3,770件（199文書）は公式XMLそのものが`src=""`です。空文字列もRAW観測としてそのまま保持します。

## Phase 3とのrevision binding

10,711 XMLのうち10,705 revisionはPhase 3 API履歴へ照合できました。6 revisionはPhase 3の53,711履歴にも2026-09-05の公式API再照合にも存在しなかったため、XMLから`law_revision`を作成していません。

この6件はRAW `source_file` / `source_file_member`を保持し、`LAW_REVISION_NOT_RECONCILED`として`reconciliation_issue`へdeferします。

## XSD

XSD invalidは取り込み拒否条件ではありません。同一snapshotのPhase 2集計は9,932 valid / 779 invalidです。今回のrelational importでは個々の`law_document.schema_validation_status`は`not-checked`であり、XSDを再実行したとは扱いません。個別status backfillは独立したfollow-upです。

## Phase 4 full relational import

2026-09-05の全量結果:

- input: **10,711**
- normalized `law_document`: **10,705**
- expected deferred revision: **6**
- normal import failure: **0**
- normalized `provision_node`: **32,116,330**
- deferred 6 XMLのparser node: **73,184**
- accounted total: **32,189,514**（事前corpus scanと一致）
- `attachment`: **42,571**（事前corpus scanと一致）
- `source_file_member`: **10,711**
- `xml_parse_issue`: **0**

RAW backlink、root、sibling/document order、node/attachment counts、OldNum/OldStyle投影、attachment revision、source member、Phase 4 search text等の全量validationで不整合0を確認しています。

証跡:
- [`../validation/phase4-full-relational-import.md`](../validation/phase4-full-relational-import.md)
- [`../validation/phase4_full_relational_import_result.json`](../validation/phase4_full_relational_import_result.json)

Phase 4の実装・全量relational validationゲートは完了しています。次工程はPhase 5の時点検索＋検索/RAGです。
