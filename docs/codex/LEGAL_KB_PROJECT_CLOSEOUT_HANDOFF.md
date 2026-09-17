# 法令ナレッジベース Project Closeout Handoff

最終更新: 2026-09-17
状態: **Phase 1〜8 完了 / Public Demo 公開済み**

## 1. Canonical state

- Repository: `watarionn/legal-knowledge-base`
- Canonical branch: `main`
- Final main commit at closeout: `4acdda5aac833a30189858ff1e43c34ada23c839`
- Phase 8 merge: PR #44 `Phase 8: publish read-only Public Demo`
- Public Demo URL: `https://ywshtmr.tail8fd68c.ts.net:8443/`
- GitHub Actions: executable workflowなし。PR #44 feature head / merge commitともworkflow run 0件。

この文書は、チャットを削除・プロジェクトを閉じた後でも、同じ完成状態から再開するための一次ハンドオフです。

## 2. 完了範囲

- Phase 1: 要件・アーキテクチャ設計
- Phase 2: 原本・全量データ検証
- Phase 3: 法令・改正履歴DB
- Phase 4: XML構造DB
- Phase 5: strict temporal resolver + 検索/RAG + Evidence Bundle
- Phase 6: 官報・国会/帝国議会会議録・NDL資料連携
- Phase 7: Daily Legal Assistant Web App、個人機能、法令ウォッチ、ローカル自動更新
- Phase 8: 匿名read-only Public Demo、Internet公開、安全境界、Completion Gate

AIはsource truthではありません。法令回答の根拠は、Phase 3/4/6の一次情報・revision・RAW provenanceへ戻せることを完成条件としています。

## 3. Runtime topology

### Private application

- Runtime worktree: `C:\Users\watar\Documents\LegalKB\phase7-runtime\app-main`
- HTTP: `127.0.0.1:8877`
- Tailscale Serve: `https://ywshtmr.tail8fd68c.ts.net/`（tailnet only）
- 個人機能: favorites / recent laws / search history / saved themes / law watch / refresh
- Local answer provider: Ollama `gemma3:4b`
- Windows Scheduled Task: `LegalKB Phase7 Runtime`

### Public Demo

- Runtime worktree: `C:\Users\watar\Documents\LegalKB\public-demo-runtime\app-candidate`
- HTTP: `127.0.0.1:8878`
- Internet: Tailscale Funnel HTTPS 8443
- Public URL: `https://ywshtmr.tail8fd68c.ts.net:8443/`
- Windows Scheduled Task: `LegalKB Public Demo Runtime`
- `LEGAL_KB_PUBLIC_DEMO=1`
- AI回答無効、Evidence-only

## 4. Database / security boundary

- PostgreSQL container: `legal-kb-phase7-db`
- Windows host port: `45432`
- DB volume/dataは削除禁止。
- Public Demo専用role: `legal_kb_public_demo`
- Public roleはSELECTのみ。superuser / CREATEDB / CREATEROLE / replication / BYPASSRLSなし。
- `default_transaction_read_only=on`
- role側statement timeout: 15秒
- Public runtimeのDB passwordはDPAPI暗号化ファイルで保持し、現在Windowsユーザーのみアクセス可能。
- password / DB URLはrepo・検証証跡・ログへ記録しない。

Public Demoはアプリ側read-onlyに加え、PostgreSQL権限でもDMLを拒否する二重防御です。

## 5. Public Demo safety contract

公開対象は以下のみです。

- Query
- 法令改正履歴
- 条文比較
- confirmed関連資料
- sanitized health

非公開対象は favorites / recent laws / search history / saved themes / watch / refresh / acknowledge / relation detail / Evidence lookup 等です。

- Request body上限: 8 KiB
- Question上限: 800文字
- Query rate: 20回/分（runtime設定）
- 同時Query: 2件
- Request timeout: 15秒
- CORSは開放しない
- CSP / X-Frame-Options / nosniff / Permissions-Policyを付与
- candidate / conflicted / rejected 関連資料はcitation-ready扱いにしない

## 6. Final validation snapshot

Phase 8 Completion Gateでは以下を確認済みです。

- 26 test files / 200 tests / failure 0
- `compileall` pass
- Public Demo JavaScript syntax pass
- `git diff --check` pass
- secret guard 0 issues
- anonymous-style live E2E pass
- malformed JSON / oversized body / oversized question fail-closed
- live rate limit 429 + `Retry-After`
- private endpoints blocked
- confirmed-only related materials enforced
- public DB roleのDML rejection確認
- Public query前後でprivate search history不変
- user端末からPublic Demo閲覧確認
- final external health: HTTP 200

詳細証跡: `docs/validation/phase8-completion-gate-20260917.json`

## 7. 再開時チェックリスト

1. `main` とremote `main`のSHAを確認する。
2. private runtime `phase7-runtime/app-main` と public runtime `public-demo-runtime/app-candidate` のSHA・clean状態を確認する。
3. `http://127.0.0.1:8877/api/v1/health` と `http://127.0.0.1:8878/api/v1/health` を確認する。
4. `tailscale serve status` で8877 tailnet-onlyを確認する。
5. `tailscale funnel status` で8443 → 8878を確認する。
6. PostgreSQL containerとDB volumeを保持したまま作業する。
7. GitHub Actionsは使用しない。`.github/workflows/` に実行可能workflowを追加しない。
8. 変更はmain直commitせず、branch → Draft PR → exact-head validation → Ready for review → mergeの順で進める。

Windowsの実OS再起動を通した完全な再起動耐性テストはcloseout時点では未実施です。Scheduled Taskは手動triggerによる冪等性を確認済みです。

## 8. 将来やるなら

法令ナレッジベース本体は完成扱いです。次に触る場合は本体Phase追加ではなく、以下を別タスクとして扱います。

- Portfolio Cityへ作品登録し、Public Demoへの導線を追加
- 必要ならPhase 7-6e Optional Delivery（メール/push配送）
- Public Demoのper-client rate limit強化
- embedding / ANN / LLM品質評価などPhase 5系の将来最適化

どれも現行完成状態の必須条件ではありません。

## 9. 重要な参照資料

- `README.md`
- `docs/architecture/roadmap.md`
- `docs/architecture/phase7-daily-legal-assistant.md`
- `docs/architecture/phase7-law-watch.md`
- `docs/architecture/phase8-public-demo.md`
- `docs/validation/phase7-completion-gate-20260916.json`
- `docs/validation/phase8-completion-gate-20260917.json`

このハンドオフと最終状態JSONを、プロジェクト再開時の最初の参照点とすること。
