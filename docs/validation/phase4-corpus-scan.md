# Phase 4 Full XML Corpus Scan

2026-09-05に、保存済み4 ZIPの10,711 XMLをストリーミングscanしました。

## Input identity

4 ZIPのSHA-256は [`xml_snapshot_manifest.public.json`](xml_snapshot_manifest.public.json) に記録しています。scan開始時に実ファイルのSHA-256とXML件数を照合します。

## 結果

| 指標 | 値 |
| --- | ---: |
| attempted XML | 10,711 |
| parsed XML | 10,711 |
| failed XML | 0 |
| total nodes | 32,189,514 |
| distinct tags | 114 |
| distinct attributes | 29 |
| max nodes / document | 201,013 |
| max depth | 23 |
| MainProvision内にArticleが一切ない文書 | 1,219 |
| nonblank tail text文書 | 2,626 |
| OldNum文書 | 458 |
| OldStyle文書 | 1,155 |
| src参照を持つ文書 | 2,176 |
| src参照総数 | 42,571 |

このsnapshotで観測した`src`参照はすべて`Fig`要素上でした。ただしparserは`Fig` whitelistとして実装せず、属性名に基づく一般的なattachment discoveryを維持します。

## 設計への含意

### Articleは必須層にできない

MainProvision直下にArticleがない文書は4,886件あり、さらにMainProvision配下のどこにもArticleがない文書が1,219件ありました。

したがって、Articleを必須とする固定schemaでは全量データを表現できません。

### Tail textを落とせない

2,626文書で非空tail textが観測されました。Ruby等のinline構造を含む本文を再現するため、child nodeだけでなくtail character dataを順序付きで保持する必要があります。

### 旧形式属性は実在する

`OldNum`と`OldStyle`は十分な件数で現存します。未知属性と同様、attributes本体をJSONBへ保持し、検索用列への投影だけを別に行います。

## Evidence

機械可読の全集計は [`phase4_full_corpus_scan_result.json`](phase4_full_corpus_scan_result.json) にあります。

このscanはXML構造の全量観測であり、PostgreSQLへの全量relational importではありません。FK、mixed-content node reference、`xml_path`等のDB上の不変条件は後続のPostgreSQL smoke/full importで検証します。
