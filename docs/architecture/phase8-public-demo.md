# Phase 8 Public Demo

## 目的

Phase 1〜7で完成した個人用法令ナレッジベースを壊さず、第三者が匿名で実際に触れられる公開デモを追加する。
公開デモは法的助言サービスではなく、法令の時点解決・根拠追跡・改正比較を体験できるread-only surfaceとする。

## 絶対境界

- AIを法令・改正・関連資料のsource truthにしない。
- strict temporal resolverの`ambiguous` / `unresolved`を自動確定しない。
- candidate / conflicted / rejected relationを公開citation-readyにしない。
- 公開リクエストからapplication-stateを書き換えない。
- 個人用runtime、Watch、検索履歴、保存テーマを公開しない。
- 公開環境から法令データ更新・refresh・acknowledgeを実行させない。
- GitHub Actionsを公開runtimeやschedulerに使用しない。

## 公開対象

- 法令質問 `POST /api/v1/query`
- 法令履歴 `GET /api/v1/laws/{law_id}/history`
- 条文比較 `GET /api/v1/laws/{law_id}/compare`
- confirmed関連資料 `GET /api/v1/laws/{law_id}/related-materials`
- sanitized health `GET /api/v1/health`
- Public Demo専用static UI

## 非公開対象

- favorites / recent laws / search history
- saved themes
- law watch / watch events / refresh / acknowledge
- source relation detail API
- in-memory Evidence lookup API
- DB接続状態、LLM model名など内部health情報
- 任意の書き込み系endpoint

公開Demoでは存在を詳しく説明せず、private endpointは原則404とする。
PUT / DELETE等の書き込みmethodは405で拒否する。

## Query方針

公開QueryはEvidence-onlyを既定とし、LLM providerを接続しない。
Phase 7 QueryServiceとEvidence生成経路は再利用し、検索結果をapplication-stateへ記録しない。
request bodyは8 KiB以下、questionは800文字以下とする。
Query contractが許可するfieldは`question` / `as_of_date` / `law_id`だけとする。

## 関連資料

Public Demoでは`include_nonconfirmed=true`が指定されても無視し、confirmed-onlyへ固定する。
relation detail endpoint自体は公開しない。
これにより未review候補やconflicted relationを公開Citationへ昇格させない。

## HTTP安全境界

Public Demoはprivate UIと別static directoryを使用する。
CSP、`X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`、`X-Frame-Options: DENY`、camera/microphone/geolocationを禁止するPermissions-Policyを返す。
server software/versionやDB/LLM構成を公開healthへ含めない。
CORSは既定で開放しない。Public UIは同一origin APIを使用する。

## 公開runtime分離

最終deployでは現在のTailscale専用8877をそのままInternet公開しない。
Public Demoは別process、別port、別設定で起動する。
DBは最終的にread-only roleを使用し、公開runtimeにDDL/DML権限を与えない。
個人用application-state schemaへの権限も公開roleから外す。

## Abuse / resource control

Phase 8後段で次を追加する。

- peer単位rate limit
- reverse proxy側rate limit / connection limit
- request timeout
- concurrent query上限
- 公開ログの最小化とrotation
- LLMを将来有効化する場合の独立quota

rate limit実装時に`X-Forwarded-For`を無条件に信用しない。trusted reverse proxy境界を明示する。

## 実装工程

### Phase 8-1 Public Boundary

公開/非公開endpoint、Evidence-only、confirmed-only、health sanitization、request上限を固定する。

### Phase 8-2 Demo Mode

`LEGAL_KB_PUBLIC_DEMO=1`で専用UIとread-only routingを有効化し、private runtimeの既定挙動を変更しない。

### Phase 8-3 Public UI

匿名利用者が質問、履歴、比較、confirmed関連資料を一画面で試せるUIを提供する。
個人機能への導線は含めない。

### Phase 8-4 Internet Hardening

rate limit、同時実行制御、timeout、reverse proxy境界、公開ログを追加する。

### Phase 8-5 Isolated Deployment

公開用read-only DB roleと別runtimeを構築する。Internet公開はCompletion Gate直前に明示的に有効化し、private runtimeを直接公開しない。

### Phase 8 Completion Gate

private endpoint非露出、DML不能、全回帰、匿名E2E、異常入力、rate limit、source-truth境界、Tailscale個人環境非干渉を確認する。

## Phase 8-5 実装結果（2026-09-17）

- PostgreSQL role `legal_kb_public_demo` を作成し、SELECTのみ付与した。
- `default_transaction_read_only=on`、15秒statement timeoutをrole側にも設定した。
- 公開runtimeは `public-demo-runtime/app-candidate` のdetached worktreeへ固定し、127.0.0.1:8878のみで待受する。
- DB passwordはWindows DPAPIで暗号化し、現在ユーザーだけが読めるACLで保存する。
- 公開runtimeは個人用8877、Watch scheduler、Ollamaを共有・起動しない。AI回答はPublic Demo modeで無効。
- Windows Scheduled Task `LegalKB Public Demo Runtime` はログオン時に8878を復帰し、二重起動を避ける。
- Tailscale Serve/Funnel設定は変更せず、現時点の外部公開は0。
- Internet公開候補はTailscale Funnel等のlocalhost reverse proxyであり、公開スイッチはCompletion Gateでのみ入れる。
