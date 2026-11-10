# CMP-20 / LegalKB Phase 8 公開デモ: 2026-11-10 実機復旧・運用受入記録

## 正本と変更境界

法令ナレッジベースの正本は `watarionn/legal-knowledge-base/main`。Phase 1〜8の歴史的完成と、現在のサービス稼働は**別の検収結果**。2026-09-17 `phase8-completion-gate-20260917.json` の `passed` / 200回帰 / failure 0、Funnel公開実績、別private runtimeの保護は変更しない。今回の運用復旧を根拠に新しい機能、法令検索精度、最新条文の完全更新をPASSと断定しない。

## Owner PC実測: 公開デモ HTTP502 の修復

2026-11-10、owner Windows PC `YWSHTMR` で `https://ywshtmr.tail8fd68c.ts.net:8443/` と `/health` は **HTTP502**。Tailscale Funnel `:8443→http://127.0.0.1:8878` は設定済みだが、ローカル8878は接続拒否でリスナーなし。一方、個人用 `:8877` はLISTENでHTTP200を返していた。

既存のWindows Task `LegalKB Public Demo Runtime` は`Ready`、既存ログオン専用トリガー有効、最終Task実行は10月31日、最終実行結果0。正規の`start-public-demo.ps1`は起動後子プロセスを切り離して終了する。公開デモはこのTaskの最後の成功結果だけでは生存確認できない。

公開デモstderrの **2026-11-01 07:13:20** 最終記録に `OSError: [WinError 10055]` があり、`socketserver.serve_forever → selectors.select → select.select` でsocketリソース利用に失敗していた。**そのOSリソース不足の根本原因・再現条件は未確定**。この例外が公開サービス停止の直接の証拠であり、最終アクセス不能を自動復帰できなかったのはログオン専用Taskが死んだ子プロセスを監視していないためと判断できる。

## 復旧操作と読み戻し

公開worktreeは`4acdda5aac833a30189858ff1e43c34ada23c839`で追跡ファイル変更0、既存launcher SHA256は`fa806751be935fd93c4650a56171c9615c2ce3550acb222e233b038e0e32a77f`。TaskのActionがこのlauncherを指し、8878が未LISTENであることを確認し、**既存Task `Start-ScheduledTask` を一度起動**。ソース再配布、DB・private runtime・Funnel設定変更、PC再起動、未認可の新Task作成は行っていない。

起動後、次を独立した実HTTP/プロセス読戻しで確認した。

- localhost `127.0.0.1:8878/` と `/api/v1/health` はHTTP200、health `status=ok, mode=public-demo`。
- Funnel `https://ywshtmr.tail8fd68c.ts.net:8443/` と `/api/v1/health` はHTTP200、公開UIマーカーあり。
- 公開側の `/api/v1/favorites` は404、CSPと `X-Content-Type-Options: nosniff` のHTTPヘッダあり。
- 個人用 `127.0.0.1:8877/api/v1/health` は引き続きHTTP200。
- `127.0.0.1:8878` は期待された公開worktreeの `003_web_server.py` を実行する `pythonw.exe` PID 21296がLISTEN。
- Windows Taskの最終結果0、2026-11-10 13:43:54 JST実行。Taskは子を起動して`Ready`へ戻るため、Task `Ready` はサービス停止の証拠ではない。

**今回の受入範囲**はowner PCからのFQDN経由HTTPSとloopback HTTP、生存プロセス、公開private境界。別ネットワークからの独立到達テスト、全Query再検証、実OS再ログイン耐久性は未実施。

## 再発防止と保留工程

現行のログオン専用Taskには子プロセス異常終了時の周期的な修復機構がない。再起動後の自動復帰・稼働中crash recoveryは、**新しい監視／Task変更の審査・許可が必要な独立運用保守ゲート**で扱う。現行Task設定、DB認証/DPAPI、Funnel、private runtimeを許可なく変更しない。

CMP-20はプロジェクト本体の歴史的完成と**今回の公開面復旧PASS**を維持するが、RLO候補台帳では依然 `creation_authorized=false` / `canonical_campaign_verified=false` であり、正式キャンペーンとしての終了・実行権限の新規付与は主張しない。運用保守ゲートの切り出しが済むまでは、未確認の常時稼働をPASSにしない。

詳細な構造化readback: [cmp20-public-demo-operational-recovery-20261110.json](cmp20-public-demo-operational-recovery-20261110.json)。
