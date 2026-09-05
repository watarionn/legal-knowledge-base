# Phase 5.2 Lexical / Structural Search

## 目的

Phase 5.2は、法令本文を検索できること自体よりも、検索hitを必ずPhase 3/4の履歴・XML構造・RAW provenanceへ戻せることを優先する。

## 派生検索層

`legal_kb.search_unit`はPhase 4 `provision_node`のうち非空`text_original`を持つnodeだけを投影する再生成可能な派生層である。`document_pk + document_order`を物理identityとして維持し、`law_id`、`law_revision_id`、logical `node_id`、`source_xml_sha256`を複製して検索結果からcitation provenanceを失わないようにする。

検索層は正本ではない。削除・再構築してもPhase 3/4の履歴・XML・RAW原本は変化しない。

## Lexical search

日本語本文ではPostgreSQL標準の言語別stemmingに依存せず、最小空白正規化後のliteral substring検索を基本契約とする。`pg_trgm` GIN indexを利用してsubstring検索を支援する。

`legal_kb.lexical_search()`は任意の全revision横断検索、または`law_revision_id`固定検索を行い、次を返す。

- `law_id`
- `law_revision_id`
- `document_pk` / `document_order`
- logical `node_id` hex
- Phase 4 treeから再構成した`xml_path`
- `tag_name` / `structural_num` / `display_label`
- `text_original`
- `source_xml_sha256`
- trigram similarity score

scoreはranking用の派生値であり、法的意味・改正時点・引用確度を表さない。

## Structural search

`legal_kb.structural_search()`はrevisionを必須指定し、`tag_name`、`structural_num`、`display_label`でXML構造を検索する。Articleを前提にせず、Phase 4の一般化treeをそのまま対象にする。

## Temporal resolutionとの境界

Phase 5.2自身は「指定日時点でどのrevisionか」を推測しない。日時検索ではPhase 5.1 strict temporal resolverでrevisionを確定し、`resolved`かつ本文availableの場合だけ、その`law_revision_id`をPhase 5.2へ渡す。

Phase 5.1が`ambiguous` / `unresolved` / 本文missingの場合、Phase 5.2が別revisionへfallbackしてはならない。

## 初期validation

PostgreSQL smokeではPhase 4の公式real XML fixtureを投入後に検索unitを再構築し、次を検証する。

- 検索unitが生成される
- revision / RAW SHA / node identity backlinkがPhase 4と一致する
- lexical hitがrevision / node / XML path / RAW SHAを返す
- structural hitがrevision / node / XML path / RAW SHAを返す
- 空のnormalized search rowが存在しない

全量10,705 documentに対するindex build時間・DB増分・検索性能測定はPhase 5.2の次の実測工程で確定する。
