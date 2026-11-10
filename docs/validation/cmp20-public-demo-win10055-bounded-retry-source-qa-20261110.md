# CMP-20 Phase 8: WinError 10055 accept-loop 再試行のsource QA（2026-11-10）

## Goal と根拠

2026-11-01の公開デモ `127.0.0.1:8878` のstderrに `OSError: [WinError 10055]`、`socketserver.serve_forever() → selectors.select() → select.select()` の例外が実記録されていた。2026-11-10に公開HTTPSが502、8878 listener不在となり、所有者PCの既存 `LegalKB Public Demo Runtime` Taskを一度起動してHTTP200復旧した。以前の失敗は**一時的なWinSock資源不足を示す**が、資源不足を起こしたプロセス・Windows全体の根因は未特定。新しい依存やOS設定変更で原因を推測修正しない。

2026-09-17のPhase 8 historical completion（200 offline regressions、Public Demo read-only、private 8877保護）を維持したまま、同じ公開プロセスのaccept-loopが一時的な指定エラーで落ちないようにする。

## Produce: サーバーの公開側のみ厳密に回数限定

`implementation/phase7/003_web_server.py` に `_serve_with_bounded_public_win10055_retry` を追加し、従来の `server.serve_forever()` をこのヘルパー経由に変更した。

- `public_demo=True` かつ `os.name='nt'` かつ `OSError.winerror == 10055` の時だけ、**既存と同じserver socket / 同じプロセス**で `1s→2s→4s` の最大3回再試行。
- 成功時にはそのまま継続し、4回目の10055、他のOSエラー、非Windows、privateモードの例外は従来どおり上へ通知する。無限スピン・新プロセス起動・port再bind・privateへのfallback・外部接続設定変更はしない。
- `KeyboardInterrupt` と元の `finally: server.server_close()` の終了順序を保持。
- `time.sleep` 以外の追加依存なし。メッセージには再試行回数と秒数だけを出し、DB URL/WinCred/DPAPI/passwordは出力しない。

## Verify: Owner Windows隔離実行結果

所有者 `YWSHTMR` Windows 11 / Python 3.14の既存公開worktree `4acdda5aac833a30189858ff1e43c34ada23c839` から、`implementation/phase3〜phase7` を独立した `%LOCALAPPDATA%\RinkaMissionControl\cmp20-server-retry-qa-20261110` へ**コピーのみ**。GitHubの変更対象2ファイルだけを隔離領域へ上書きし、稼働中公開worktreeやDB・Task・Funnelには一切編集・停止を行わなかった。

- source blob: `003_web_server.py = 511f5070c8c3fac8e733b35cb897868dca77369c`
- test blob: `082_public_demo_socket_retry_test.py = ab157e90a4725d1b8923bc0a68cacdd95b82d5c5`
- Python AST syntax PASS。
- 新規テストはWinError 10055の一過性回復、恒常エラーで3回後再送出、private/非Windowsの非リトライ、別例外を隠さない、Ctrl-C伝播、通常終了の**7/7 PASS**。
- 本来の番号付き`*_test.py`を個別実行（`unittest discover`は先頭数字のmodule名を認識せず0件となる）。**27ファイル / 207テスト PASS、fail 0**。過去の26ファイル/200件に新規7テストを加えた数。呼出しは既存アプリと同じファイルを実ロードして検証。
- source-only QAであり、**本番8878プロセスのコードは旧headのまま**。シミュレーションによる例外再試行のPASSを、実OSのWinError 10055根因解消、再起動後の自動復帰、継続稼働や実本番の新版投入PASSとして扱わない。

## Review / Ship / Preserve / Next

変更は`watarionn/legal-knowledge-base`の通常branch→PR→main手順で保全。新たなTask、自己回復service、予定Task、外部コネクタ、秘密鍵は一切追加しない。既存 `LegalKB Public Demo Runtime` Taskはログオン起動のみで、子プロセスが落ちても`Ready/LastResult=0`になりうるため、WinError 10055以外の障害は今後も運用復旧を要する。

次工程は、現行ownerリリース `4acdda5...` の差分を採用した**目的特定・所有者承認済みimmutable release/rollback**の準備と、[guarded health inspector](cmp20-public-demo-guarded-monitor-plan-20261110.md)による異常検知。新Task登録と実行は別の所有者署名/認可境界とし、共同Windows再起動はCMP-08等と同じメンテナンス機会まで実施しない。実機の古いserverを強制終了したり、稼働プロセスのソースをin-place更新したりしない。
