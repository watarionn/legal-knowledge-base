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

## Phase 6 external sources

Phase 6では、次を法令本文とは別の`external_document`系列として接続します。raw payloadは既存`source_file`へ保存し、外部資料のmetadata projectionを法令本文の正本として扱いません。

- 官報: https://www.kanpo.go.jp/
  - 2025-04-01以降の官報発行サイトを対象とする。サイトのcrawler禁止を尊重し、6.3はoperator指定の単一PDFだけを取得する。
  - raw PDFの電子署名・タイムスタンプ構造を観測するが、暗号学的validation未実行時は有効と断定しない。
- 国会会議録: https://kokkai.ndl.go.jp/
- 帝国議会会議録: https://teikokugikai-i.ndl.go.jp/
- NDLサーチ: https://ndlsearch.ndl.go.jp/

2025-04-01以降の官報は内閣府の官報発行サイト上の電子データが正本です。国会・帝国議会会議録APIでは会議録`issueID`、発言`speechID`をprovider識別子として利用できます。NDLサーチはSRU/OpenSearch/OpenURL/OAI-PMHを提供しており、Phase 6では返却識別子とraw responseを分離して保持します。

法令との関連は`source_relation`と`source_relation_assertion`へ保存します。自動照合はcandidateとして保持し、provider明示または明示的reviewなしにpromulgation・amendment等の法的関係を確定しません。

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
