# CMP-20 owner public-demo: 停止検知・自動復旧の安全な実装契約（2026-11-10）

## 現在の障害と採用済み基盤

既存Phase8製品・Public Demoは2026-09-17に正式Completion Gateを通過。2026-11-10はFunnel `:8443` → `127.0.0.1:8878` が残ったまま公開子プロセスだけ不在となりHTTP502。既存Windows Task `LegalKB Public Demo Runtime` を一度起動して公開HTTPS/health200に復帰した。前回の公開stderrには2026-11-01 `WinError 10055` があるが、リソース不足の詳細原因は未確定。手動起動の復旧結果・独立源は [実機記録](cmp20-public-demo-operational-recovery-20261110.md) と [構造化receipt](cmp20-public-demo-operational-recovery-20261110.json)。既存Taskはログオンだけをトリガーとし、起動後に子プロセスが落ちてもTask結果0のまま、親TaskはReadyに戻る。

## 今回実装: 読取専用の判定器

[scripts/cmp20_public_runtime_inspect.py](../../scripts/cmp20_public_runtime_inspect.py) は**唯一のCLI `--inspect`**を持ち、所有者PCで固定された情報を照合して次の一つに分類する。Task・プロセス・ファイル・秘密鍵・データベース・Funnelには一切書かない。

- `HEALTHY`: 公開worktreeが`4acdda5aac833a30189858ff1e43c34ada23c839`、launcher SHA256が`fa806751be935fd93c4650a56171c9615c2ce3550acb222e233b038e0e32a77f`で固定され、Task actionが既存の公開launcher、Funnel rootが正確に`127.0.0.1:8878`、所有者の`pythonw.exe`が127.0.0.1:8878を待ち受け、公開healthが `ok/public-demo/phase8-public-demo`、private8877が`ok`。
- `RECOVERY_CANDIDATE_NOT_AUTHORIZED`: 以上のsource・Task・route・private健全性の条件がPASSし、8878のListenerがゼロ、公開healthも応答なし、TaskはReadyで競合起動がない。**停止状態の候補を検出しただけ**で、既存Taskを起動する権限を意味しない。
- `HOLD`: Source SHA/Task action/Serve route/Private health/ポート所有者等の不一致・不明・実行中Taskの起動途中・別プロセス・公開プロセスが存在するのにhealth不能・二重listener。異常を「再起動して直す」対象へ自動昇格しない。

CLIは`--recover`、`--start`、`--stop`を明示的に拒否。OSコマンドは固定`git` read-only、`Get-ScheduledTask`、`Get-NetTCPConnection`、`Get-CimInstance`、`tailscale serve status --json`のみ。外部引数のshell連結、秘密鍵/WinCred/DPAPI読込なし。localhost HTTP GETのみ。

### Verify / owner Windows実行結果

- 独立Windows隔離QA `%LOCALAPPDATA%\RinkaMissionControl\cmp20-runtime-qa-20261110`: **19/19 unit tests PASS**、誤owner・不明port・disabled/Running task・wrong binary/health/route・誤CLIなどFAIL CLOSED。
- 実owner PCに`--inspect`を一回実行: `HEALTHY`, `source_git_head_pinned=true`, `launcher_sha256_pinned=true`, `funnel_target_pinned=true`, `owner_process_verified=true`, `public_health_verified=true`, `recovery_candidate=false`, `task_triggered=false`, `owner_execution_authority=false`, `read_only=true`。
- 所有者Git checkoutは変更せず、今回のコードは隔離QAにのみ配置した。本番のscript・Task/trigger・service/db/routeを変更していない。生きているサービスに対する再起動試験は実施しない。

## 次工程の明確な権限分離

1. **Source候補**: 既存Taskを固定targetとして再実行するrecover-once runnerを別途設計・source QA。独立owner署名で`CMP20_PUBLIC_DEMO_RESTART_ONLY`、owner release pin、Task action SHA、1起動/時間・排他・発火期限・signed rollback/receiptを束縛する。新規実行プランをTask登録する場合は別途固定のTask-specific owner認可が必要。
2. **Taskライフサイクル**: 後継監視Taskは最初`Disabled`・IgnoreNew・非管理者必要最小権限、固定5分検査、合意した保守期間の前に旧Taskと競合しない。read-only inspect PASSでもTask自動起動を勝手に許可しない。
3. **実機切替**: 真正な署名・同一owner identity・source hash・起動パス・stop/rollback・既存private8877の非干渉、実端末のreadbackを通した後に限り変更可能。
4. **OS再起動**: CMP-08等との**共同メンテナンスまで保留**。共有再起動後に公開Taskの自動復帰とCMP-08 watchdogの非重複を同時に検証。現時点のログオン時Taskの存在から再起動テストPASSを推定しない。
5. **残余**: ソケット`WinError 10055`の根因分析、数日間の稼働継続、外部第三者ネットワーク到達、全文検索/RAG回答品質は今回のread-only診断の受入外。Phase8歴史完成・CMP-20候補台帳の非canonical境界を維持する。

今回の実装で **故障の誤検知から無承認の実行へ進む事故は防止**できる一方、認可済み自動復旧の実運用はまだ未実施。新Taskを登録・稼働させたとは決して記録しない。
