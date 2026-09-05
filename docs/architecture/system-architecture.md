# System Architecture

## 原則

法令ナレッジベースは、一次情報を一つの巨大な「正規化済み本文」に潰さず、**原本、履歴、XML構造、検索派生物、外部資料**を分離します。

## レイヤー

### 1. Provenance / RAW

`source_file` と `ingestion_run` が入口です。

- 取得元
- 取得時点
- SHA-256
- byte size
- immutableかどうか
- どの取り込みrunで観測したか

を保持します。正規化データはRAWの代替ではありません。

### 2. 法令系列と履歴

`law` は法令系列、`law_revision` は個別履歴を表します。

- 内部識別にはe-Govの`law_id` / `law_revision_id`を使う
- 法令名や法令番号を主キーにしない
- API原値と、履歴IDから解析した値と、派生した有効期間を別列にする
- future / 未施行履歴も削除しない
- current APIで見えなくなった過去履歴を自動DELETEしない

### 3. XML構造

Phase 4では、法令XMLを`law_document`と`provision_node`へ格納します。

`provision_node`はArticle専用テーブルではなく、XML要素を一般化した順序付きツリーです。これにより、Articleなし、旧形式、附則、別表、表、図、Ruby、数式、未知要素を同じモデルで保持できます。

保存する主要情報:
- parent-child関係
- sibling ordinal
- document order
- namespace URI
- tag name
- 全属性
- `Num` / `OldNum` / `OldStyle`投影
- 原文字列
- mixed content segment
- deterministic `xml_path`

### 4. Attachment

XMLの`src`等の参照は`attachment`として分離します。

- XMLに書かれた`source_src`は原値のまま保持
- 解決後locatorで上書きしない
- 未解決・missingも行として残す
- 実バイナリ取得時は別`source_file`へ結合する

### 5. Search / RAG

検索用テキストやembeddingはRAWや`text_original`とは別派生物として作ります。

検索結果は必ず次へ戻れることを要求します。
- `law_id`
- `law_revision_id`
- provision / XML path
- as-of date
- source file
- source SHA-256

## 競合処理

CSV・XML・API等で値が異なる場合、片方を黙って消しません。

`source_assertion`に観測値を保持し、必要な不一致を`reconciliation_issue`へ記録します。canonical値を選ぶ場合も、その根拠を追跡可能にします。

## 時点情報

`valid_from` / `valid_to_exclusive`は派生値です。APIの施行日原値を上書きしません。

同日複数revisionやbaseline境界など、法的順序をデータだけでは一意に断定できない場合は`ambiguous`として保持し、推測で一本化しません。

## XSD

公式XSDは重要な検証基準ですが、公式RAW XMLの存在を否定するゲートにはしません。well-formedな公式XMLがXSDへ非適合でも、RAWを保持し、validation statusとエラーを記録したうえで構造化を継続できます。
