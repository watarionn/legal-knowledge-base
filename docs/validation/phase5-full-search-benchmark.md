# Phase 5.2 Full Search Benchmark

2026-09-07に、固定済み4 ZIPのXML snapshotとe-Gov API Version 2の再取得履歴を使い、Phase 3 → Phase 4 → Phase 5.2 hardened search benchmarkを全量実行した。

## 実行環境

- PostgreSQL: 18.6 (Ubuntu 26.04 / WSL2)
- pipeline: `015_full_search_pipeline_hardened.py`
- benchmark: `013_full_search_benchmark_v2.py`
- Phase 3 workers: 2
- history request interval: 0.6秒
- benchmark repeats: 5
- input archive: `all_xml_01.zip` ～ `all_xml_04.zip`
- input total bytes: 330,651,407
- DSNは証跡へ記録していない

## Phase 3

Phase 3はresumeを使って完走した。

| 指標 | 値 |
| --- | ---: |
| requested laws | 9,551 |
| resume skipped laws | 1,296 |
| pending laws at final resume | 8,255 |
| revision observations in final run | 44,453 |
| final `law_revision` rows | 53,711 |
| failed laws | 0 |
| warning issues | 47,569 |
| error issues | 0 |

最終runは `result_status=succeeded`。同日revision groupや未解決amendment参照は契約どおりwarningであり、errorは0件だった。

## Phase 4

固定XML 10,711件を再照合した結果、今回の公式API観測では10,704件を`law_document`へ投入し、7件をRAW-onlyでdeferした。

| 指標 | 値 |
| --- | ---: |
| input XML | 10,711 |
| reconciled / inserted documents | 10,704 |
| deferred unreconciled | 7 |
| normal import failures | 0 |
| `provision_node` | 32,105,947 |
| `attachment` | 42,571 |
| `source_file_member` | 10,711 |
| XML parse issues | 0 |
| elapsed | 945.861 sec |

2026-09-05のPhase 4正式証跡は10,705 documents / 6 deferredだった。今回増えた1件は `326CO0000000319_20270331_508AC0000000032` であり、調査の結果、importer不具合ではなく固定snapshotと後日の公式API履歴のsource driftと確認した。既存証跡は当時の観測として上書きしない。詳細は `phase5-reconciliation-drift-326CO0000000319.md` を参照する。

## Search index build

Phase 5.2では10,704 documentsから14,679,077 search unitsを構築した。

| 指標 | 値 |
| --- | ---: |
| eligible nodes | 14,679,077 |
| inserted search units | 14,679,077 |
| indexed documents | 10,704 |
| indexed revisions | 10,704 |
| rebuild | 1,223.940 sec |
| ANALYZE | 2.383 sec |

### Storage

| 指標 | bytes |
| --- | ---: |
| DB before search build | 20,841,289,407 |
| DB after search build | 33,648,203,455 |
| DB build delta | 12,806,914,048 |
| `search_unit` total | 12,806,963,200 |
| `search_unit` heap | 6,581,829,632 |
| `search_unit` indexes | 6,188,425,216 |

search layerだけで約12.8 GB増えるため、`search_unit`は再構築可能な派生indexとして扱い、citation truthには使わない。

## Query latency

代表4語を各5回測定した。値はms。

### Global lexical search

| query | median | p95 |
| --- | ---: | ---: |
| 国民 | 4,865.278 | 5,100.305 |
| 法律 | 15,222.491 | 15,487.137 |
| 政令 | 24,324.878 | 26,183.696 |
| 附則 | 27,090.662 | 27,965.709 |

全revision横断のglobal lexical searchは中央値約4.9～27.1秒で、interactive searchとしては遅い。これは探索用途の基準値であり、法的回答のrevision選択には使わない。

### Revision-scoped lexical search

| query | median | p95 |
| --- | ---: | ---: |
| 国民 | 25.780 | 143.740 |
| 法律 | 36.116 | 65.470 |
| 政令 | 38.737 | 124.510 |
| 附則 | 34.327 | 164.863 |

strict temporal resolverでrevisionを決めた後のlexical searchは中央値約25.8～38.7msだった。

### Structural article search

- returned rows: 100
- median: 4.544ms
- p95: 105.522ms

## Interpretation

1. Phase 5.2の全量buildは成功した。
2. revision-scoped lexical / structural searchは十分高速な基準値を得た。
3. global lexical searchは数秒～数十秒で、改善対象である。
4. search layerは約12.8 GBの追加storageを必要とする。
5. 今回の10,704 document benchmarkは2026-09-07公式API観測に基づく。2026-09-05の10,705 document証跡との差はsource driftとして明示的に保持する。
6. search rankingはlegal confidenceではない。法的回答ではtemporal resolutionを先に行い、ambiguous / unresolved時に別revisionへ暗黙fallbackしない。

機械可読なpublic-safe結果は `phase5_full_search_benchmark_result.json` に記録する。
