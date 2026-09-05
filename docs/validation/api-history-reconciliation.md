# e-Gov API Version 2 / Bulk XML History Reconciliation

## 目的

bulk XMLの法令履歴IDと、e-Gov法令API Version 2が返す全履歴を照合し、XML snapshotとAPI historyの関係を実データで確認しました。

## 2026-09-04時点の検証

この検証で使用したcurrent bulkは10,681 XMLで、6,975法令系列に属していました。

各`law_id`についてAPI `/law_revisions/{law_id}` を取得し、再試行後の最終取得失敗は0件でした。

結果:

| 項目 | 件数 |
| --- | ---: |
| bulk law IDs | 6,975 |
| bulk revision IDs | 10,681 |
| API history revision IDs | 28,793 |
| bulk revision IDのAPI history欠落 | 0 |
| 最終API取得失敗law | 0 |

したがって、この取得窓ではbulk XMLに含まれる10,681 revision IDすべてをAPI history集合内で確認できました。

## Snapshot差への注意

別途保存している10,711 XML snapshotとは30件の差があります。これは取得時点・snapshot条件の異なるデータを件数だけで比較してはいけないことを示します。

本プロジェクトでは:
- acquisition time
- archive SHA-256
- law/revision ID集合

を使ってsnapshotを識別します。

## APIとXMLの役割

API Version 2:
- 法令系列
- 全改正履歴
- revision metadata
- enforcement metadata

bulk XML:
- 各revisionの法令本文・XML構造

どちらか片方で全情報を代替するのではなく、相互補完し、競合値はprovenance付きで保持します。
