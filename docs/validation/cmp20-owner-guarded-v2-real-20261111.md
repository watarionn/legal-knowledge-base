# CMP-20 V2 本番署名Task・候補障害復旧の実機検収（2026-11-11 JST）

## 検収結果

**SIGNED V2 OWNER TASK + REAL CANDIDATE-ONLY FAULT AND NATIVE RECOVERY: PASS.** この文書は実際の所有者PC `YWSHTMR` で取得した限定的な受入証拠。ソースPRのマージだけで本番や耐久を合格扱いしない。

- 正本GitHub `watarionn/legal-knowledge-base` main [PR #58](https://github.com/watarionn/legal-knowledge-base/pull/58) のV2登録・保護・復旧ソースを使用。V2原本Git blob `df38e01947cd04a15bf144aecd512f6815945ecf`、独立V2 verifier Git blob `3e58401b0882022e69ed9a2548d88ab73fcc4448` は所有者PCに登録済みの保護済みV2 release内で一致を確認した。PR #58のmain squashコミット `fd111ed7f09e63994b1f299b7fdd31e44677c028`。
- 所有者専用のV2実行署名 trust SHA256 `b9500871148d8aa015f7a4f3327eca24015f644477af78eae12493ad8ea453ca`、manifest SHA256 `acc8388de8e64ef367547bb31e9fb6ab569ee86a549a79a0d75a54e728bf2b3e`、packet SHA256 `e369c3669f6047b3eff5ac2604efde828d28aa3cf548f9ac8244c34db422d670` を実際に読戻した。独立 `cmp20_public_guarded_task_verify_v2.py --verify` は **PASS**、V1真正署名・レビュー署名と異なるV2用途を確認し、旧公開停止、既存Task変更、DB変更、OS再起動の実行権限はいずれもfalse。
- 正式Task `RinkaLegalKBPublicGuardedOnceV2` が所有者PC上で実在し、`Ready`、`Interactive`、Logon + Daily PT5M（2トリガー）、`IgnoreNew`、`AllowHardTerminate=false`、`LastTaskResult=0`、`NumberOfMissedRuns=0`。独立 `--inspect` もPASS。12:25:01 JSTの自然周期実行は、12:25:05 JSTの `last-guarded-once.json` `PASS`、署名済みV2、旧8878 PID15900、新8879 PID3168、HTTPS8443→8879、非公開8877正常、SHA256 `12e842f72ebaacc545cbaf3d87de0714d6a00aae52e4322eb825932d046d9f77` と一致。

## 候補だけを実際に停止して復旧を確認

2026-11-11 12:27 JST、元の公開サービスを提供したまま以下を**実操作**した。すべてV2保護ソースと既存の目的限定署名に基づく。外部サービスの停止やOS再起動は行っていない。

1. 保護済みV2 `--restore` 実行で公開Funnel `8443: 8879→8878`。署名済み固定スコープ、HTTPと実Serve状態の読戻しPASS。**旧版8878 PID15900が引き続き公開を提供**。
2. 同一V2 `--drill-stop` は署名・元公開8878・Python workerのPID/コマンド/receipt整合を確認して**候補8879 PID3168だけを停止**。8879 LISTENが消えたことを独立確認。個人用8877 PID5740と元公開8878 PID15900は停止していない。
3. 既存Task `RinkaLegalKBPublicGuardedOnceV2` に対する `Start-ScheduledTask` を実行。これは**実際のTask Schedulerによる手動起動**であり、12:27の自動時刻トリガーとは呼ばない。Task最後の実行日時は**12:27:05 JST**、`LastTaskResult=0`、再生成worker **PID8976**。旧worker **PID3168とは異なる**こと、`last-guarded-once.json` 12:27:11 JSTが `status=PASS`, `candidate_recovered=true`, `old_public_pid=15900`, `public_route=8878` であることを読戻した。回復レシートSHA256 **`34f9513c1ecd88d7625ec9338038e69a8512aa318f235b343b9b75aee1c9cabf`**。
4. 復旧完了後、保護済みV2 `--activate` で `8443:8878→8879` を再実行、署名検証・Task・実Windows PID・public HTTPSを確認。返値 `SIGNED_V2_ROUTE_SWITCH_PASS`、`candidate_pid=8976`, `v2_guard_task_registered=true`, `postboot_unverified=true`。実際のHTTPS8443ヘルスは**HTTP200**。
5. **12:28:42 JST** の独立読戻しで Funnel8443→`http://127.0.0.1:8879`・AllowFunnel true、元公開8878 **PID15900 HTTP200**、新公開8879 **PID8976 HTTP200**、個人用8877 **PID5740 HTTP200**、公開HTTPS8443 HTTP200。試験前に存在した元のプライベートサービスやTaskは変更していない。

**検収の限界**: 12:27レシートはTask手動起動時に8878へ退避中の値であり、12:28現在のFunnel8443→8879を反映するレシートではない。これは不整合ではなく、後続の自然5分周期を待ってその時点の最新レシートを独立に照合する必要がある。試験したのは**V2 Taskによる実際の候補障害復旧、旧版の継続、署名付き切替・復元**だけであって、再起動後の自動復帰や24時間耐久はまだ証明していない。

## 保存と次の受入

所有者PC OS boot は **`2026-11-10T05:24:48.5000000Z`** のまま、物理再起動を実施していない。長期耐久の既存一回タスク **「CMP-20 24時間耐久検収」** は **2026-11-12 10:30 JST** に設定済み。既存の起点は **2026-11-11 10:07 JST** だが、終了時点をもって途中288回すべてを逐一証明したと表現しないこと。既存タスクを複製・無断変更しない。

残るゲートは、(a) 真正な自然周期を継続して検証、(b) 24時間経過時の実機署名/PID/HTTPS/Queue/Private境界検査、(c) 共有PC調整済みの**物理再起動・実ログイン後**のTaskとHTTPS自動復帰、(d) iPhone/PWAと外部第三者による別受入、(e) CMP20キャンペーン正本への適切な正式登録と最終終了判定。過去のPhase1〜8製品完成は別に完了済みで、計画台帳の `PROJECT_SOURCE_VERIFIED_CAMPAIGN_OPEN` を推測で正式DONEへ変えない。

本番の秘密鍵は所有者PCの保護領域に残し、GitHubへアップロードしない。原版8878のGit・Taskと個人用8877/PostgreSQLを破壊せず、V2発行済みの署名・固定実行アクションに限定して継続する。
