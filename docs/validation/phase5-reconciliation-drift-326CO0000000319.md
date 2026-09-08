# Phase 5.2 Reconciliation Source Drift

対象revision: `326CO0000000319_20270331_508AC0000000032`

## 結論

今回の7件目のdeferはimporter不具合ではなく、固定XML snapshotと後日のe-Gov API履歴のsource driftである。

2026-09-05のPhase 4正式証跡は当時の観測として保持し、上書きしない。2026-09-07 benchmarkでは10,704 documents / 7 deferredとして別観測を記録する。

## 固定XML snapshot

- archive: `all_xml_04.zip`
- member: `326CO0000000319_20270331_508AC0000000032/326CO0000000319_20270331_508AC0000000032.xml`
- bytes: 1,162,781
- SHA-256: `cadb33731ba2e30bd5b10d3a63b803af8d688eeecbba5b89237e68129a257014`
- law title: 出入国管理及び難民認定法
- XML is well-formed and remains immutable snapshot evidence.

## Phase 3 API observation

2026-09-07 full rebuildで保存した `/law_revisions/326CO0000000319` のRAW応答は次のとおり。

- response bytes: 38,067
- SHA-256: `6e82f8eaa661575dc85c11f7cee871ce180b549ebb3ed8a8b2266a20c5cb5824`
- revision count: 42
- target revision present: false

2026-09-08の再照合でも同endpointは同一SHA-256で、targetは存在しなかった。

`/law_data/326CO0000000319_20270331_508AC0000000032` をrevision ID指定で取得するとHTTP 404、e-Gov error code `404004` を返し、現在その本文revisionは公式APIから取得できない。

## Official API drift signal

同じ改正法 `508AC0000000032` による現行revisionには次が存在する。

- `326CO0000000319_20290331_508AC0000000032`, updated `2026-09-07T09:33:53+09:00`
- `326CO0000000319_20281031_508AC0000000032`, updated `2026-09-07T09:32:12+09:00`
- `326CO0000000319_20261001_508AC0000000032`, updated `2026-09-07T09:24:58+09:00`
- `326CO0000000319_20260605_508AC0000000032`, updated `2026-08-24T17:51:22+09:00`

2026-09-05のPhase 4正式証跡ではAPI非照合は6件で、targetはその6件に含まれていなかった。したがって2026-09-05観測後に公式履歴が更新され、固定snapshotとの照合状態が変化したと判断する。

## Handling rule

- XMLから`law_revision`を捏造しない。
- 固定XMLはimmutable provenanceとして保持する。
- 後日のAPI非観測も別の公式観測として保持する。
- 時点の異なる2つの公式観測をどちらも上書きしない。
- benchmark document countの差はこのsource driftを明記した上で解釈する。

機械可読証跡は `phase5-reconciliation-drift-326CO0000000319.json` に記録する。
