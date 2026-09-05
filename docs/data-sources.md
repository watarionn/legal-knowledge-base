# Data Sources

このプロジェクトでは、ソースごとの役割を分離して扱います。

## e-Gov法令API Version 2

主な役割:
- 法令系列の列挙
- `law_info`
- `revision_info`
- 個別法令の全改正履歴
- 施行・改正関連メタデータ

APIの構造化値はPhase 3の法令・履歴DBで中心的に利用します。

公式API: https://laws.e-gov.go.jp/api/2/swagger-ui

## e-Gov法令XML

主な役割:
- 法令本文のRAW原本
- 条・項・号だけではないXML構造
- 附則、別表、表、図、Ruby、数式等
- `OldNum` / `OldStyle`等の旧形式情報

XMLはPhase 4で一般化した順序付きツリーへ構造化しますが、正規化DBがRAW XMLを置き換えることはありません。

## 公式XSD

主な役割:
- XML構造検証
- schema validation statusの記録

XSD非適合だけで公式RAWを拒否・自動修正しません。

## 将来連携する一次資料

Phase 6では、次を法令本文とは別の`external_document`として接続する予定です。

- 官報
- 国会会議録
- 帝国議会会議録
- 国立国会図書館の立法・法令関連資料

関係例:
- promulgated_in
- bill_for
- deliberated_in

## Snapshotについて

このリポジトリに記録された件数は、取得日時・取得方法・フィルタが異なるsnapshotを含みます。たとえばAPIの法令集合、保存済みXML snapshot、別時点のcurrent bulkは同じ母集団とは限りません。

件数だけでsnapshot同士を同一視せず、取得時点・SHA-256・revision ID集合を使って比較します。

## Gitへ入れないもの

- 大容量RAW ZIP
- PostgreSQL dump
- 大量の展開済みXML
- 取得済み添付画像・バイナリ
- credentialsやprivate locator

Gitには、実装、公開可能な小規模fixture、ハッシュ、集計値、再現手順を置きます。
