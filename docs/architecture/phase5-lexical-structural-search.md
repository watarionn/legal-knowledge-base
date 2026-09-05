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

## 全量benchmark protocol

`implementation/phase5/008_full_search_benchmark.py`は、Phase 4 full relational import済みDBへPhase 5.2 DDLを適用した状態で実行する。検索indexは再生成可能な派生層なので、全量測定では`rebuild_search_units(NULL)`を実行し直して測る。

記録する項目は次のとおり。

- succeeded document件数
- search unit対象となる非空text-bearing node件数
- rebuild後のsearch unit件数・document件数・revision件数
- search unit rebuild時間とANALYZE時間
- database全体、search_unit heap、search_unit indexのbyte数と前後差分
- 全revision横断lexical queryの複数回latency
- 最大search unit数を持つrevisionに固定したlexical queryの複数回latency
- 同revisionのArticle structural queryの複数回latency

既定lexical queryは`国民`、`法律`、`政令`、`附則`とし、`--query`で追加・置換できる。latencyはmin / median / p95 / max / meanをJSONへ保存する。

全量測定時にはsearch unit件数がeligible node件数と完全一致しない限り成功扱いにしない。測定結果JSONは実測環境・PostgreSQL version・測定日時を含め、後続のstorage/performance契約の証跡とする。
