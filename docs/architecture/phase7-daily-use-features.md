# Phase 7-5 日常利用機能

## 目的

Phase 7-1〜7-4で構築した質問・時点検索・条文比較・関連資料探索を、毎日使いやすい状態へする。

Phase 7-5では次の4機能を追加する。

- お気に入り法令
- 最近見た法令
- 検索履歴
- 保存テーマ

これらはapplication stateであり、法令本文・revision・Evidence・外部資料の正本にはしない。

## 設計原則

Phase 3〜6のsource truthとPhase 7 application stateを物理的・意味的に分離する。

検索履歴や保存テーマへ法令原文、Evidence本文、生成回答を複製しない。
履歴を再利用するときは保存済み入力を現在のquery APIへ再送し、strict temporal resolverとEvidence構築をもう一度実行する。

application stateの保存失敗は、法令検索やEvidence表示の成功を失敗へ変えてはならない。

## application-state schema

Phase 7-5は単一ローカル利用者向けに`workspace_id = local`を使用する。
認証・マルチユーザー管理は導入しない。

保存表:

- `application_favorite_law`
- `application_recent_law`
- `application_search_history`
- `application_saved_theme`

お気に入り・最近見た法令・履歴・テーマが参照する`law_id`はPhase 3 `law`へFKを張る。
一方、検索履歴そのものは法令revisionやEvidence snapshotを固定しない。

検索履歴には次を保持する。

- query ID
- 質問
- requested / effective as-of date
- resolved law IDと表示名snapshot
- query response status
- temporal status

保存テーマにはtitle、question、law ID、as-of dateだけを保持する。

## HTTP API

- `GET /api/v1/daily-state`
- `PUT /api/v1/favorites/{law_id}`
- `DELETE /api/v1/favorites/{law_id}`
- `POST /api/v1/saved-themes`
- `DELETE /api/v1/saved-themes/{theme_id}`
- `DELETE /api/v1/search-history`
- `DELETE /api/v1/recent-laws`

`GET /api/v1/daily-state`は4機能を1 responseにまとめる。

質問APIは従来どおりPhase 3〜6をread-only transactionで利用する。
query response生成後にapplication-state schemaがreadyなら別transactionで履歴・最近見た法令をbest-effort保存する。
保存失敗はserver logへ記録するが、query response自体は200を維持する。

## UI

Web UIは「マイリスト」パネルとして4機能をまとめる。
お気に入り・最近見た法令は次の検索対象法令を設定する。
検索履歴・保存テーマは質問、法令ID、基準日をquery formへ戻し、`requestSubmit()`で現在のquery APIへ再送する。

ユーザー保存文字列はDOM `textContent`で描画し、HTMLとして注入しない。

## Runtime bootstrap

`031_application_state_bootstrap.py`で4表の存在状態を`empty / ready / partial`に分類する。

- `empty`: Phase 7-5 schemaを適用
- `ready`: 何も変更せずskip
- `partial`: 自動修復せずfail-closed

bootstrap reportへDATABASE URLやcredentialを記録しない。

既存runtimeへschemaを追加するときは、Phase 3〜5主要件数が適用前後で不変であることを確認する。

## Phase 7-6への接続

Phase 7-6法令ウォッチは保存テーマをwatch条件の入力として再利用できる。
ただしPhase 7-5では通知、定期実行、改正検知は行わない。
保存テーマが存在すること自体を法的な関連性やcitation evidenceとして扱わない。

## 完了条件

1. 4つの日常利用機能が同一UIから利用できる
2. application stateがPhase 3〜6 source truthを変更しない
3. 履歴・テーマは現在のquery経路で再検索する
4. query成功がapplication-state保存失敗に巻き込まれない
5. runtime schema bootstrapがpartialをfail-closedにする
6. 実PostgreSQLで4機能のtransactional CRUD smokeが通る
7. HTTP/Web contractと既存Phase 7回帰が通る
8. GitHub Actions cost guardを維持する
