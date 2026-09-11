# Phase 7-3 条文・revision比較

## 目的

Phase 7-2で選択できる法令の時点履歴を、2つの時点の条文比較へつなげる。

Phase 7-3では、利用者が次を確認できることを目標とする。

- 比較元・比較先をそれぞれstrict temporal resolverで解決する
- 同じ法令の2 revision間でArticle単位の追加・削除・変更・不変を確認する
- 個別Articleについて原文を左右に並べ、文字差分を確認する
- 本則と附則で同じArticle Numが再利用されても混線させない
- Articleの対応関係が曖昧な場合は自動選択しない

比較の正本はPhase 3の時間軸とPhase 4の構造・原文であり、retrieval chunkや生成回答をdiffの正本には使用しない。

## 非目標

Phase 7-3では、官報・国会会議録・NDL資料との横断比較は行わない。
それらはPhase 7-4で扱う。

また、法令間の意味的な類似条文推定や、AIによる「実質同一条文」の自動対応付けは行わない。

## Article対応キー

Article Num単独では対応付けしない。
e-Gov XMLでは、本則と多数の附則で同じNumが再利用されるためである。

Phase 7-3は次の構造スコープを使う。

- 本則: `main + Article Num`
- 附則: `supplementary:{SupplProvision.AmendLawNum} + Article Num`

Phase 4の`provision_node`を祖先方向へ辿り、`MainProvision`または`SupplProvision`を特定する。
附則では原本XML属性`AmendLawNum`を使用する。

スコープまたはNumが欠落しているArticleは推測で補わず、比較対象から除外してwarningへ記録する。
同一スコープ+Numが複数存在する場合も自動対応付けしない。

個別条文をNumだけで指定し、複数スコープに候補がある場合は`ambiguous`として候補一覧を返す。
UIで候補を選んだ場合のみ`scope_key`を付けて再比較する。

## 原文復元

Article本文はPhase 4 `mixed_content_jsonb`を再帰的に辿って復元する。
`text_search_normalized`やPhase 5 retrieval chunkは使用しない。
原文SHAは左右それぞれのPhase 4 `source_xml_sha256`へ戻れる。

## Compare API

`GET /api/v1/laws/{law_id}/compare`

Query parameters:

- `from_date=YYYY-MM-DD` 必須
- `to_date=YYYY-MM-DD` 必須
- `article_num` 任意。`90`、`398_2`、実データに存在する`155:157`等を許可
- `scope_key` 任意。`main`または`Supplementary`由来のキー

両側の日付はPhase 5.1 strict temporal resolverへ個別に投入する。
片側でも`ambiguous` / `unresolved` / `not-found`なら`blocked-temporal`で停止する。

両側がresolvedでもPhase 4本文が片側に無ければ`blocked-content`で停止し、別revisionへfallbackしない。
同じrevisionへ解決された場合は`same-revision`とする。

全文比較は`added / removed / changed / unchanged`件数と、変更Article一覧を返す。
変更一覧は最大500件とし、上限超過時はwarningを返す。
個別Article指定時は左右原文と`SequenceMatcher`による文字差分segmentを返す。

`source_truth`は`phase3-phase4`を維持する。

## UI

Phase 7-2の改正履歴各項目から「比較元にする」「比較先にする」を選択できる。
比較パネルでは2日付と任意の条番号を指定する。

条番号を空欄にした場合はrevision全体のArticle変更一覧を表示する。
変更Articleを選択すると`scope_key`を引き継いで個別比較する。

条番号を手入力し、複数スコープに同番号がある場合は候補を表示し、利用者が選択するまで比較を確定しない。
差分描画はHTML文字列を注入せず、DOM要素へ`textContent`で設定する。

## Phase 7-3 完了条件

1. 両時点をstrict temporal resolverで解決する
2. Phase 4原文からArticleを復元する
3. 本則・附則を構造スコープで区別する
4. 曖昧なArticle対応を自動選択しない
5. historical本文missing時にfallbackしない
6. 全文変更一覧と個別文字diffを表示できる
7. 実PostgreSQL由来データで比較smokeが通る
8. 実HTTP handlerのcompare route契約が通る
9. 既存Phase 7-1/7-2回帰を壊さない
10. GitHub Actions cost guardを維持する
