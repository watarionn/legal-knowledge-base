# Phase 7-2 時点検索・改正履歴UI

## 目的

Phase 7-1で実装したEvidence-only Web Appに、法令の時間軸を日常的に扱うためのUI/APIを追加する。

利用者は次を一画面で確認できることを目標とする。

- 任意の日付時点で対象revisionをstrictに解決する
- 選択された法令の改正履歴を一覧する
- 同日複数revisionなどのambiguousを隠さない
- 各revisionに本文があるかを確認する
- 履歴上の施行日を選んで同じ質問を再検索する

Phase 7-2でもAIやretrieval chunkを法令の正本にはしない。時間軸の正本はPhase 3、本文とprovenanceの正本はPhase 4とする。

## 非目標

Phase 7-2ではrevision間の条文diffを実装しない。条文比較はPhase 7-3で扱う。

官報・国会会議録・NDL資料の横断探索、お気に入り、通知も後続へ送る。

## strict temporal境界

履歴UIから特定revisionを直接検索対象へ固定しない。

利用者が履歴項目の「この施行日で再検索」を選んだ場合も、UIは`valid_from`を`as_of_date`としてquery APIへ渡し、Phase 5.1 strict resolverを再実行する。

その日がambiguousなら複数候補を表示して停止し、勝手に1 revisionへ丸めない。

対象revisionがresolvedでもPhase 4本文が未収録なら`content_status=missing`を表示し、別revisionの本文へfallbackしない。

## History API

`GET /api/v1/laws/{law_id}/history?as_of_date=YYYY-MM-DD`

返却する主な情報:

- 法令ID・法令番号・法令名
- 指定日とstrict temporal resolution
- revision総数
- 各revisionのsequence / effective date / valid range
- temporal resolution quality
- current revision status
- 改正法令ID・法令番号・法令名・改正種別
- succeeded document数と本文availability
- 一意な本文がある場合のdocument ID / source XML SHA-256
- 指定日時点でselectedかcandidateか

`source_truth`は`phase3-phase4`とする。

## UI

Phase 7-1の1画面構成を維持し、結果領域の下へ「改正履歴」を追加する。

- 基準日入力の横に「今日」操作を追加
- queryで法令が一意解決された場合にhistory APIを取得
- selected revisionを強調
- ambiguous時はcandidate revisionを複数強調
- 各項目に有効期間、quality、本文availability、改正法令を表示
- `valid_from`がある項目は、その日付で同じ質問を再検索可能

## エラー境界

history APIは次を通常の状態として扱う。

- 不正な`law_id`: HTTP 400
- 不正な`as_of_date`: HTTP 400
- 存在しない法令: HTTP 404
- DB未設定・接続不能: HTTP 503
- temporal `ambiguous` / `unresolved` / `not-found`: HTTP 200で状態を返す

履歴取得だけが失敗した場合、既に成功したquery/Evidence表示を破棄しない。UIは履歴領域だけにエラーを表示する。

## Phase 7-2 完了条件

1. history APIがPhase 3全revisionを返せる
2. 指定日についてPhase 5.1 strict resolver結果を返せる
3. selected/candidate revisionをUIで区別できる
4. historical body missingを別revisionで補わない
5. 履歴の施行日から同じ質問を再検索できる
6. source truthがPhase 3/4のまま維持される
7. unit test、実PostgreSQL smoke、HTTP smokeが通る
8. GitHub Actions cost guardを維持する
