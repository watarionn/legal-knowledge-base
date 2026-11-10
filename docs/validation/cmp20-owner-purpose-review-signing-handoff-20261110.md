# CMP-20 Public Demo: 所有者専用 Ed25519 レビュー署名と実行権限の分離

2026-11-10、LegalKB Phase8公開デモ用に `WinError 10055` のbounded retry修正版を作成し、owner PC隔離環境で **27ファイル/207テスト全PASS**、2-source-file+manifest無署名候補の owner readback SHA256 `9b8730abdfe399b9f8d9bf86e95fac0b9063236f214c306c439da4588b80374f` を確認した。その候補への**レビュー署名**だけを提供するのが今回の工程。既存の匿名read-only公開デモ、個人用 `:8877`、DB、Tailscale、起動Taskには何も適用しない。

## 作成したソース（実行と分離）

- [cmp20_public_release_review.py](../../scripts/cmp20_public_release_review.py) はowner公開デモのstaging manifest SHA、固定2ファイルの Git blob、元版 `4acdda5...`、旧server blob `a394f509...`、review済修正版main `14d5d6d...`、既存 `LegalKB Public Demo Runtime` のlauncher SHA `fa80675...`、rollback元の不変更、Funnel公開 `:8443→:8878` / private `:8877` の不変更を**完全一致**で検査する。
- `owner_approvals/cmp20-public-demo-release-review` 専用の公開鍵信頼宣言には役割の異なるissuer/reviewer **Ed25519鍵2個**が必要。JSONフィールドの増減、鍵重複、署名変更、異なるcampaign purpose、stage file増分、stage SHA/patch SHA改ざんをFAIL-CLOSEDとする。署名本文の `approval_scope` は `REVIEW_ONLY_NOT_EXECUTION` に固定。
- [cmp20_public_release_owner_signer.py](../../scripts/cmp20_public_release_owner_signer.py) は Windows owner-only のcreate-only signerで、`enroll-review` と `issue-review` しか受け付けない。`LOCALAPPDATA/RinkaMissionControl/owner_approvals/cmp20-public-demo-release-review` にのみ秘密鍵を配置する。鍵は所有者PCからexportしない。独立trust SHA pinが不一致の発行は拒否、署名済みpacketは独立verifier `--verify` 読戻しPASSが必要。owner Windows ACLでは過去CMP-08の具体的失敗対策を継承し、余分な `OWNER RIGHTS` ACE、PowerShell SACL privilege不足、子鍵のinherit ACL欠落を防止するため`icacls.exe`のDACL専用操作、`(OI)(CI)`とACL読戻しを採用した。
- 署名が正しくても **Task登録・有効化・起動・旧publicプロセス停止・ファイル差替え・DBアクセス・rollback実行・PC再起動の権限は全てfalse**。レビュー署名を実行認可へ変換する仕組みはこのmoduleには存在しない。Rollback元のPINはレビュー対象であり、rollbackを実行する命令ではない。

## QA と具体的状態

`scripts` と `tests` の4ファイルについて GitHub branch上のGit blobと、ローカルLinux QAへ展開した実バイトのGit blobが一致することを確認した。Python3.13 / cryptography 46のローカル隔離試験で **正式テスト21/21 PASS**、追加のstaged source合成/byte mutationを含む独立smoke **22/22 PASS**。実行テストはすべて生成した**一時的な検証用鍵**で行い、所有者の実鍵を使用せず保存していない。Python syntaxコンパイルもPASS。

**owner PC `YWSHTMR` は今回の時点でRemote Desktop Commander接続 Offline**（直前の同日回ではOnline、最終オンラインの状態や実機ファイルはこのチャットで以前確認済み）。従ってこのターンでは Windows上での鍵登録、owner ACL実機テスト、owner署名パケット発行、owner stage再確認、本番切替を一切実施していない。`OWNER_REVIEW_NOT_ENROLLED` と断定できる現時点のPC読戻しもないため、**未確認**と扱う。

## 将来の正式実機実施ゲート（実行依頼ではない）

1. owner PCがOnlineになり、既存公開WebがHTTPS200・private8877が200、現行worktreeが `4acdda5...` か、無署名候補のSHAが一致、既存署名材料に異常がないか読み戻す。
2. 本体GitHub mainの署名ツール/検証器のsource blobを固定QA領域に導入し、Windows実機の所有者身元・鍵フォルダ不在/継承ACL安全性を確認する。実鍵作成の**明示owner consent**を受けた場合に限って、`enroll-review` の固定操作を実行し、trust SHA256の独立読み戻しを行う。
3. 署名発行にも独立owner consentと同一trust SHA256を渡し `issue-review`。独立 `--verify` の`PASS / REVIEW_ONLY_NOT_EXECUTION` と実packet SHAを記録する。失敗したら、元の秘密鍵やownerフォルダを不用意に削除・上書きしない。
4. **別**のowner署名済みの実行権限、復元承認、旧公開子プロセスの安全な協調終了・新Task action、DB/DPAPI、rollback/read-after-write/HTTPS検証がそろうまで実リリースはしない。CMP08との共同再起動もownerの次回メンテナンスまで保留。

## 可視的な未完

- Windows owner実鍵・署名 packet = **未発行/実機未確認**。レビュー実施すら自動認可ではない。
- 新版production release = **未適用**。現行公開appは旧Git head、公開HTTP200が最後に確認された状態。
- 旧publicプロセスの安全終了、Task新認可、Windows共同再起動後の再接続確認、WinError 10055のOS-level根因解消 = **OPEN**。
- CMP-20計画台帳の `PROJECT_SOURCE_VERIFIED_CAMPAIGN_OPEN` / `creation_authorized=false` / `canonical_campaign_registered=false` を維持する。
