# CMP20 owner-signed V2 public guardian Task: real execution and durability acceptance (2026-11-11 JST)

## Actual reviewed code

LegalKB source [PR #58](https://github.com/watarionn/legal-knowledge-base/pull/58) merged to main **`fd111ed7f09e63994b1f299b7fdd31e44677c028`**, with exact main readback V2 source Git blob `df38e01947cd04a15bf144aecd512f6815945ecf`, independent V2 Ed25519 verifier blob `3e58401b0882022e69ed9a2548d88ab73fcc4448`, test blob `fc2c4c1e87f168193ce13f65e27eab35c7b9d383` and runbook blob `a02d2aacda9ecdbefbc7806197da1b90590418fe`, all independently retrieved from main.

Owner YWSHTMR isolated exact source QA: eight Git blob pins matched, Python3.14 compilation PASS, **32/32 source tests PASS** including Ed25519 tamper and overbroad-Task denial, old/private preservation, fixed Task PT5M+logon trigger and no-pipe launcher behavior. Real original V1 signed packet/release/patch source preflight independently PASS. The old V1 release keys/source were preserved and neither V1 nor original `LegalKB Public Demo Runtime` Task was rewritten.

## Actual owner consent and two-role Task-specific V2 signature

Based on the user's specific approval for a signed automatic recovery Task and permanent cutover, new **purpose-distinct V2 issuer/reviewer keys** were enrolled in the owner-private trust directory `%LOCALAPPDATA%/RinkaMissionControl/owner_approvals/cmp20-public-demo-guarded-once-owner-v2` with separate reviewed fixed consent strings and independent readback trust SHA256:

- V2 trust SHA256 **`b9500871148d8aa015f7a4f3327eca24015f644477af78eae12493ad8ea453ca`**
- Ed25519 signed V2 execution manifest SHA256 **`acc8388de8e64ef367547bb31e9fb6ab569ee86a549a79a0d75a54e728bf2b3e`**
- Actual distinct two-role signed V2 packet SHA256 **`e369c3669f6047b3eff5ac2604efde828d28aa3cf548f9ac8244c34db422d670`**

The independent signed packet verifier returned PASS and prohibited modifying existing Tasks, old public process stop, unrelated processes/DB, Tailscale reset and OS reboot. Owner Windows independent ACL readback **7/7 PASS** for approval root, keys folder, both secret key files, trust, manifest and packet: protected DACL, exact owner/SYSTEM/Administrators FullControl, no extra ACE. No private key bytes were exported.

The exact, protected **V2 release stage** at `%LOCALAPPDATA%/RinkaMissionControl/releases/cmp20-public-demo-guarded-once-owner-v2` contains only source-pinned V2 guardian, V2 independent verifier, and four original reviewed V1 companion sources, plus a 1-byte concurrency lock. Independent owner command `cmp20_public_guarded_task_verify_v2.py --verify` returned **PASS**, including authentic previously issued V1 Ed25519 packet and source proofs. Owner release stage code and lock DACL independently verified protected owner/System/Admin-only; run-time receipt uses inherited owner/SYSTEM/Admin-only ACE from the already protected stage parent and has no broader access. The inherited receipt DACL is intentionally not represented as an independently protected key-file DACL.

## New native Task registration and initial real ACK

A new fixed Task `RinkaLegalKBPublicGuardedOnceV2` was actually registered by the exact signed owner `--register` action. The Task registered PASS and was independently read back: `Ready`, principal `watar`, `Interactive` logon mode / `Limited` runlevel, Python `C:\Python314\python.exe -B <exact owner protected v2 path> --once`, `IgnoreNew`, `AllowHardTerminate=false`, **two triggers**: logon and daily repeating `PT5M`, duration `P1D`. The old original Task `LegalKB Public Demo Runtime` and all other Task identities were left unchanged. No new package or service was installed.

Actual native Task execution was requested through `Start-ScheduledTask` (not by running the script directly); at **2026-11-11 09:58:59 JST**, Task state returned `Ready`, `LastTaskResult=0`, `NumberOfMissedRuns=0`, with actual signed `last-guarded-once.json` `status=PASS`, `source_signed=true`, `candidate_recovered=false`, original public target `http://127.0.0.1:8878`, candidate worker **PID28340**, checked UTC `2026-11-11T00:59:04.777374+00:00`, SHA256 `90d6b009d2f98ce8398a9511fcc843698b13f55120eebd9a3a6f909fbde99105`.

A separately observed **natural 10:00:01 JST** Task Scheduler tick also returned `Ready`, result0 and missed0, with genuine PASS receipt SHA256 `d912e4af1dd9e7d39bf5474af1b8e04b9b508cc25bf963ec7f66514dab98e124`. This proves initial natural 5-minute Task scheduling, not a post-reboot result.

## Candidate-only fault injection, outcome deliberately unclaimed until readback

At **10:00:37–10:00:40 JST**, with external HTTPS8443 still targeting original `:8878`, actual signed V2 `--drill-stop` returned `SIGNED_V2_CANDIDATE_ONLY_FAULT_INJECTED` exit0, **stopped only source/PID-pinned new public worker PID28340**, and did not stop original public PID15900 or private PID5740. Independent Windows port readback showed `:8879` no listener while `:8878` and `:8877` each retained their original live PID. Native Task next scheduled natural tick **10:05:00 JST**.

**Do not claim successful recovery, new worker PID, active permanent cutover, 24-hour soak, logout/relogin, OS reboot or CMP20 canonical closure until actual owner evidence below.** This note preserves the exact pending checkpoint rather than inventing future results. V2 signed Task is now installed and the earlier inherited-pipe deadlock has been corrected in reviewed source; live recovery, final public cutover and further durability need separate proof.

## Next real gates

1. Observe genuine next native Task tick **10:05 JST** and require exit0, fresh `candidate_recovered=true` receipt, new signed process PID not 28340, local :8879 HTTP200, original :8878/private :8877 still HTTP200, original public Funnel target unchanged.
2. Run signed fixed `--activate` only after that actual recovery PASS. Require external HTTPS8443 actually on :8879, exact other Serve routes unchanged, CSP/nosniff/X-Frame-Options and public private-favorites404, original public :8878/private :8877 healthy, new Task Ready.
3. Observe at least one full subsequent **natural** five-minute Task tick while new public route active, with no missed runs, and save receipt SHA.
4. A 24-hour unattended run, owner logoff/relogin, coordinated shared physical owner reboot and actual post-boot Task/public recovery require separate elapsed or physical evidence. The user previously deferred owner OS reboot to multi-campaign maintenance; V2 packet explicitly forbids reboot. CMP20 planning record remains noncanonical OPEN until separately authorized canonical registry/owner final acceptance.

Primary related records: [LegalKB Issue #54](https://github.com/watarionn/legal-knowledge-base/issues/54), [V1 signed canary](cmp20-owner-signed-parallel-release-v1-20261111.md), [V2 Task signed source/runbook](cmp20-owner-guarded-v2-task-release-20261111.md).

## Actual automatic task-only fault recovery and permanent route switch: PASS

At the next **naturally scheduled** Task tick **2026-11-11 10:05:01 JST**, without a manual Start-ScheduledTask, owner Task `RinkaLegalKBPublicGuardedOnceV2` returned `Ready`, `LastTaskResult=0`, `NumberOfMissedRuns=0`, next tick 10:10. The signed native Task receipt was **`status=PASS`, `candidate_recovered=true`**, worker PID **3168**, route still original8878, checked UTC `2026-11-11T01:05:07.697099+00:00`; SHA256 **`8c1de81ad4d9d51bab6fea9f6c1ca900a23826469c149bc183ed0054c68c4ccb`**. The deliberate stopped worker was PID28340; the **new PID3168** is independent direct proof of the worker's recovery. Original public8878 **PID15900** and private8877 **PID5740** stayed running and HTTP200; the new signed8879 was listening/HTTP200. This is proof of **actual autonomous native Windows Task recovery**, and the corrected pipe-free launcher controller returned exit0. No unknown extra process was killed.

With that signed Task's actual recovery PASS and existing original public fallback still ready, owner executed the reviewed V2 source-pinned **`--activate`** at **10:07 JST**. It returned **`SIGNED_V2_PERMANENT_PUBLIC_ROUTE_ACTIVATED` / `SIGNED_V2_ROUTE_SWITCH_PASS` exit0**, previous Funnel8443 `http://127.0.0.1:8878`, current **`http://127.0.0.1:8879`**, V2 guard Task registered. Independent owner `tailscale serve status --json` reread public8443 root proxy exactly new8879 and AllowFunnel=true with other Serve entries intact.

Independent actual external-owner-HTTPS acceptance **10:07:48 JST**: `https://ywshtmr.tail8fd68c.ts.net:8443/` HTTP200 with CSP, `X-Content-Type-Options:nosniff` and `X-Frame-Options:DENY`; `/api/v1/health` HTTP200 `mode=public-demo`, public `/api/v1/favorites` HTTP404, private localhost8877 PID5740 HTTP200, unchanged original public8878 PID15900 HTTP200, active candidate8879 PID3168 HTTP200. **Independent signed V2 owner source/old V1 Ed25519 verifier also PASS**. The old original public process and Task stay healthy as the immediate fixed fallback. No actual physical reboot, older Task change, database alteration or Tailscale reset was performed.

The permanent route was genuinely switched to the reviewed new public-only patch under an **enabled, source-pinned, V2-signed automatic recovery Task**, not merely staged or briefly canaried as in V1. However the elapsed unattended 24-hour and physical logoff/relogin/reboot acceptance have not been performed and are still **OPEN**; do not call those PASS from this short-lived release. The periodic post-cutover scheduled tick and longer stability receipts follow below.
