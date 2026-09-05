# Phase 4: XML Structure Database

Phase 4は、法令XMLを検索しやすくしながら、原文構造を損失なく保持する層です。

## なぜ固定の「条・項・号」階層にしないのか

10,711 XML全量scanでは、MainProvision配下のどこにもArticleがない文書が1,219件ありました。また、附則、表、図、Ruby、数式、旧形式属性、mixed contentも実在します。

そのため、Article / Paragraph / Item専用階層ではなく、**全XML要素を一般化した順序付きツリー**として保存します。

## `law_document`

1つの法令XML原本に対応します。

保持するもの:
- `law_revision_id`
- `source_file_id`
- source XML SHA-256
- parser version
- parse status
- XSD validation status/errors
- root情報
- node / attachment counts

well-formedness failure時も、可能な範囲でfailed documentとして来歴を残します。

## `provision_node`

XMLの全要素を表す汎用nodeです。

主な列:
- `parent_node_id`
- `ordinal`
- `document_order`
- `depth`
- `tag_name`
- `namespace_uri`
- `attributes_jsonb`
- `structural_num`
- `display_label`
- `old_num` / `old_style`
- `text_original`
- `mixed_content_jsonb`
- `xml_path`

`attributes_jsonb`が属性観測の本体で、`old_num`等は検索用投影です。

## Mixed content

要素本文は単純な`text()`だけでは保持できません。`mixed_content_jsonb`へ次のsegmentを文書順で保存します。

- `text`
- `child`
- `tail`

空白のみのtailもtrimしません。

## `xml_path`

normalized nodeからRAW XML構造へ戻るため、expanded nameと同名兄弟indexを使った決定的pathを作ります。

例:

```text
/Law[1]/LawBody[1]/MainProvision[1]/Article[2]/Paragraph[1]
```

namespace URIもpath identityへ含めます。

## `attachment`

`src`等で参照された画像・外部resourceを分離します。

- `source_src`: XML原値
- `resolved_locator`: 解決後の場所
- `availability_status`: unresolved / resolved / missing等

解決に成功しても`source_src`を上書きしません。

## XSD invalid

公式RAWがwell-formedであれば、XSD invalidだけを理由に構造化を中止しません。`schema_validation_status=invalid`として記録し、RAWとnormalized treeを両方保持します。

## 現在のゲート

完了済み:
- DDL設計
- XML parser
- synthetic tests
- 10,711 XML全量structural scan
- PostgreSQL importer実装
- 実XML regression fixtures準備

未完了:
- Public repo CIでのPostgreSQL 16 real XML smoke
- 10,711 XML full relational import
- relational validation SQL
- normalized infoset round-trip検査
