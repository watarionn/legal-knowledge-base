# CMP-20 公開デモ: ソース修復のimmutable無署名候補ステージング（2026-11-10）

`watarionn/legal-knowledge-base/main` の2026-11-10修復コードを、**所有者PCの本番作業領域を一切書き換えず**に独立レビュー可能な2ファイル版immutable source candidateとして準備した。

## 前提 / 元版保全

- 公開サービスの現行worktree: `4acdda5aac833a30189858ff1e43c34ada23c839`、追跡ファイル変更0。
- 元サーバー `003_web_server.py` のGit blob: `a394f509b51fe598eb0f1852339ba7f21e2be9b4`。
- 元launcher `start-public-demo.ps1` SHA256: `fa806751be935fd93c4650a56171c9615c2ce3550acb222e233b038e0e32a77f`。
- 新たなserver/testの正式GitHub main source commit: `14d5d6dae5ca1b238a78860b0e473ebbd795415d`（[PR #49](https://github.com/watarionn/legal-knowledge-base/pull/49)）。公開専用WinError10055の1/2/4秒・最大3回再試行以外、旧private runtimeに新機能は加えない。

## Owner実施と検証

新規 `scripts/cmp20_public_release_candidate_stage.py` は固定2ファイルのGit blobを照合し、所有者実worktreeのHEAD・追跡ファイルのclean状態・元server blob・既存launcher SHAをread-only照合する。パスのjunction/symlinkを拒否。所有者PCの既存隔離QA領域 `%LOCALAPPDATA%/RinkaMissionControl/cmp20-server-retry-qa-20261110` の**新しい子フォルダにだけ**、2ファイルと`manifest.json`をcreate-onlyで書き、すべての内容を読み戻してからrenameする。既存stage/最終版があれば上書きしない。

- Windows隔離Unit: **9/9 PASS**（未知ファイル・変更blob・不足ファイル・既存ステージ・旧source drift時の拒否、権限false）。
- 全本体ソース回帰: **27ファイル / 207/207 PASS**、公開専用エラー再試行の実コードを利用。
- 実owner `--inspect`: `READY_UNSIGNED_SOURCE_ONLY`、元版HEAD・コード・launcher pin照合PASS、既存候補不在。
- 実owner `--stage`: `STAGED_UNSIGNED_NONEXECUTABLE`、**2 source files + manifest、3ファイル**、manifest SHA256 `9b8730abdfe399b9f8d9bf86e95fac0b9063236f214c306c439da4588b80374f`、独立読み戻し一致。候補:
  `%LOCALAPPDATA%/RinkaMissionControl/cmp20-server-retry-qa-20261110/cmp20-public-demo-unsigned-source-candidate-v1`。
- 新版Git blob `003_web_server.py=511f5070c8c3fac8e733b35cb897868dca77369c`、テスト `082_public_demo_socket_retry_test.py=ab157e90a4725d1b8923bc0a68cacdd95b82d5c5`。

## 重要な権限境界

このsource candidateは意図的に `UNSIGNED / NONEXECUTABLE`。**所有者release署名、Task登録、Task有効化、旧プロセス停止、Funnel切替、DB/DPAPI読み書き、Windows再起動のいずれも行っていない**。本番の旧public8878が動いていても、隔離candidate生成は干渉しない。現在公開されているコードが新版へ更新済みと誤報告しない。

次工程は本候補の独立レビュー後に**CMP-20専用の所有者署名付き正式リリースとロールバック権限**を確立し、目的外署名の流用を防ぐこと。実運用への切替は停止/復旧の協調経路、Task actionの独立認可、HTTPS200/private8877不干渉の実測後のみ。OS再起動はCMP-08とほかのキャンペーンとの共同メンテナンスに残す。

構造化証拠: [cmp20-public-demo-immutable-unsigned-stage-20261110.json](cmp20-public-demo-immutable-unsigned-stage-20261110.json)。
