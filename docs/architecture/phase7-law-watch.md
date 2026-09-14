# Phase 7-6 法令ウォッチ

## 目的

Phase 7-5の保存テーマを入口に、対象法令の変更を継続的に確認できるapplication layerを追加する。

Phase 7-6では次を目標とする。

- 保存テーマに紐づく対象法令の変更を決定論的に検知する
- 観測された新revisionと、指定日時点で適用されるrevisionを区別する
- 変更前後をPhase 7-3の比較経路へ接続する
- 施行日、公布日、関連資料へ安全に遷移できるようにする
- 変更がない場合も「確認済み」であることを表示できるようにする

AIは変更有無、施行日、法的効果、対応期限のsource truthにはしない。
変更検知の正本はPhase 3の法令・revision・ingestion provenance、時点解決はPhase 5.1、本文diffはPhase 4/7-3とする。

## 非目標

Phase 7-6では、AIによる改正影響判定や「対応が必要」といった法的結論を自動生成しない。
外部通知サービスへの送信、メール配信、スマートフォンpush通知も初期実装の必須要件にはしない。

## 用語と状態の分離

法令ウォッチでは次の状態を混同しない。

- `observed-change`: 新しいrevisionがローカルDBへ観測された
- `effective-change`: strict resolverの結果として基準日時点の適用revisionが前回評価から変わった
- `scheduled-change`: API原値として将来の施行予定日が確認できる
- `ambiguous` / `unresolved`: strict resolverが一意に確定できない
- `no-change`: 評価は成功したが対象revisionに変化がない
- `initialized`: 初回baselineを確立したが変更イベントは作成していない

`first_seen_run_id`と`ingestion_run.started_at`は「このDBで初めて観測した時点」のprovenanceとして使う。
これを公布日、施行日、法的な発生日の代替にはしない。

`amendment_promulgate_date`、`amendment_enforcement_date`、`amendment_scheduled_enforcement_date`はAPI原値として表示する。
`revision_id_effective_date`は`revision_date_kind`と組み合わせて扱い、単独で意味を推測しない。

## ウォッチ対象

Phase 7-5 `application_saved_theme`を入口にできるが、保存テーマ自体はcitation evidenceではない。
ウォッチ作成時には対象`law_id`を明示的に固定する。
`law_id`の無い保存テーマから自動で法令を推測してウォッチを作成しない。

## application-state schema案

Phase 7-6で追加するapplication stateはsource truthを複製しない。

`application_law_watch`:

- `watch_id`
- `workspace_id`
- `theme_id` 任意
- `law_id` 必須
- `baseline_revision_id` 任意。初回評価後に設定
- `baseline_ingestion_run_id` 任意
- `enabled`
- `last_evaluated_at`
- `created_at` / `updated_at`

`application_law_watch_event`:

- `event_id`
- `watch_id`
- `event_type`
- `from_revision_id` / `to_revision_id`
- `detected_at`
- `effective_date` 任意
- `source_ingestion_run_id` 任意
- `temporal_status`
- `acknowledged_at` 任意

法令本文、Evidence本文、生成回答、diff本文は保存しない。表示時に既存APIから再構築する。

## 初回baselineと評価日

初回評価は過去revisionを新着イベント化せず、現在のstrict resolver結果と最新の成功ingestion runをbaselineとして初期化する。
初期化そのものは`initialized`状態として返し、変更イベントは作成しない。

watchの評価日は既定で評価実行日のローカル日付とする。
保存テーマの`as_of_date`は検索再生用入力であり、watchの現在時計には流用しない。
過去日・将来日を評価したい場合は、手動evaluate APIへ明示的な`evaluation_date`を渡す。

## 評価アルゴリズム

1. enabledなwatchから明示`law_id`を取得する
2. Phase 3のrevision集合とingestion provenanceを読む
3. 評価日のrevisionをPhase 5.1 strict resolverで解決する
4. `ambiguous` / `unresolved` / `not-found`なら変更を確定せず、その状態をイベント候補として返す
5. baseline revisionとresolved revisionが同じなら`no-change`
6. 異なる場合だけ`effective-change`を生成する
7. baseline以後に初観測されたrevisionがあれば`observed-change`として別に扱う
8. 将来施行日がAPI原値で確認できる場合だけ`scheduled-change`として表示する
9. 比較が必要な場合はPhase 7-3へ`from_date` / `to_date`を渡し、本文をその場で再構築する

評価成功後にのみbaselineと`last_evaluated_at`を更新する。
DB接続不能、partial schema、temporal ambiguityではbaselineを前進させない。

同一watch・event type・from/to revision・source ingestion runの組合せは冪等に扱い、再評価で同じイベントを重複作成しない。
acknowledgeは検知事実を削除せず、利用者が確認済みかどうかだけをapplication stateとして更新する。

## 日付と「対応期限」の扱い

施行日や公布日を自動的に「対応期限」と表示しない。
初期実装では「重要日付」として、公式データ由来の日付種別と値をそのまま表示する。

将来「対応期限」を追加する場合は、公式資料に明示された期限を構造化してprovenance付きで取得できる場合、または利用者が明示入力した期限に限定する。
AI推測日付を期限として永続化・通知しない。

## HTTP API案

- `GET /api/v1/watches`
- `POST /api/v1/watches`
- `DELETE /api/v1/watches/{watch_id}`
- `POST /api/v1/watches/{watch_id}/evaluate`
- `POST /api/v1/watches/evaluate`
- `POST /api/v1/watch-events/{event_id}/acknowledge`

watch作成時は`law_id`必須、`theme_id`任意とする。
全watch評価はローカルDBに対するbounded operationとし、1回のHTTP requestから外部e-Gov全量取得を開始しない。

評価APIのsource truthは`phase3-phase5`、diffへの導線は`phase3-phase4`とする。
application eventは「検知記録」であって法令根拠そのものではない。

## UI

「マイリスト」内または直後に「法令ウォッチ」を追加する。
各watchには法令名、最終確認日時、状態、重要日付、未確認イベント件数を表示する。

変更イベントからは次へ遷移できる。

- 改正履歴
- 変更前後の条文比較
- confirmed関連資料
- 同じ保存テーマで現在時点を再検索

`ambiguous` / `unresolved`は警告状態として表示し、変更確定のバッジを付けない。

## 実行方式

Phase 7-6の初期実装は手動評価APIとWeb UIから開始する。
ウォッチ評価器は既にローカルDBへ取り込まれたデータだけを評価し、外部取得と変更判定を1処理に混在させない。

定期実行は後段でローカル専用schedulerへ追加できる。
GitHub Actionsを定期実行基盤には使用しない。
外部通知を追加する場合も、まずapplication eventを確定してから別配送層で扱う。

法令データ更新処理が失敗・partialの場合、watch baselineを前進させない。
通知配送の失敗もwatch eventそのものを消さない。

## 実装順

### Phase 7-6a Watch Core

- schemaとservice
- watch CRUD
- 手動evaluate
- deterministic state machine

### Phase 7-6b Change Evidence

- ingestion provenanceによるobserved-change
- strict resolverによるeffective-change
- 将来施行予定日の表示

### Phase 7-6c Diff / Related Navigation

- Phase 7-3 compareへの導線
- Phase 7-4 confirmed関連資料への導線
- 未確認/確認済みイベント管理

### Phase 7-6d Local Refresh / Scheduling

- 既存の安全な法令データ更新経路、またはwatched-law限定refreshをローカルで実行
- refresh成功後だけwatch評価を実行
- ローカル定期評価
- Web UI上の未確認件数

更新処理とwatch評価は別transaction / 別stepに分ける。
refresh失敗・partial時は評価をスキップし、baselineを前進させない。
GitHub Actionsは更新・定期評価の実行基盤にしない。

### Phase 7-6e Optional Delivery

必要な場合だけ、確定済みapplication eventをメール・push等へ配送する層を追加する。
配送失敗はイベント検知結果へ逆流させない。

## エラー境界

- 不正な`law_id` / `watch_id`: HTTP 400
- 存在しない法令・watch: HTTP 404
- application-state schema未導入/partial: HTTP 503
- DB接続不能: HTTP 503
- temporal `ambiguous` / `unresolved` / `not-found`: HTTP 200で状態を返す

watch評価だけが失敗しても、通常のquery、Evidence、履歴、比較機能を失敗へ巻き込まない。

## Phase 7-6 完了条件

1. 明示law IDからwatchを作成・削除できる
2. 保存テーマを入力として再利用してもsource truthに昇格させない
3. observed / effective / scheduled changeを区別できる
4. strict resolverのambiguousを変更確定へ丸めない
5. baseline更新が成功評価時だけ行われる
6. 変更イベントからPhase 7-3比較とPhase 7-4関連資料へ遷移できる
7. 法令本文・Evidence・生成回答をwatch表へ複製しない
8. 施行日を自動で法的な対応期限と断定しない
9. 実PostgreSQL smoke、HTTP/Web contract、既存Phase 7回帰が通る
10. 初回評価で過去revisionを新着イベント化しない
11. refresh失敗・partial時にbaselineを前進させない
12. GitHub Actions cost guardを維持する
