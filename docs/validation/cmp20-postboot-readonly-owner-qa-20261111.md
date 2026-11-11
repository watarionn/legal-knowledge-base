# CMP20 postboot read-only gate: actual owner QA and baseline (2026-11-11)

## Purpose
The existing V2 signed Task and 24-hour public canary are **unchanged**. This additional **source-only** [postboot reader](../../scripts/cmp20_postboot_readonly_acceptance.py) performs no Task/OS/Serve/process/database mutation, does not enroll keys, does not invoke any recovery or cutover action and does not create any automation. It evaluates the exact already approved V2 owner's signed state.

The reader supports two explicit modes:
- `--baseline`: owner-host-only exact present signed Task/receipt, Task action and triggers, listener/process identity, public/private HTTP privacy boundary and Serve/Funnel proof. Reports `reboot_since_baseline_proven=false`.
- `--after-relogin --baseline-boot-utc <actual preboot UTC>`: all baseline gates, **plus genuinely later boot and native postboot Task+receipt**. Unchanged boot yields `HOLD/NO_NEW_BOOT_PROVEN`, never a simulated reboot PASS.

The existing live task is `RinkaLegalKBPublicGuardedOnceV2` under owner `watar`, one exact action, owner Interactive, one logon trigger + one daily PT5M trigger, IgnoreNew and no hard terminate. The reader checks `LastTaskResult=0`, zero missed runs, an up-to-date matching receipt, signed V2 independent verifier PASS, exact three pythonw listeners/private health and secure public root/health/404. It does **not** prove 288 individual ticks, genuine independent third-party external reachability, logon without actual relogin, or the OS-wide historical cause of WinError10055.

## Actual isolated owner Windows QA

On owner YWSHTMR, two exact source files were copied only to an isolated QA workspace below `%LOCALAPPDATA%\RinkaMissionControl\cmp20-postboot-readonly-qa-20261111`, not to the production V2 signed stage or old public worktree. Independent owner Git blob readbacks:

| Artifact | Git blob matched on owner |
|---|---|
| `scripts/cmp20_postboot_readonly_acceptance.py` | `e181d98f10f84c6deca642324ec656d74611e069` |
| `tests/test_cmp20_postboot_readonly_acceptance.py` | `d8153ea6c0609f4ef5bc9f8048888fe75212b0e3` |

Python3.14 `-B` independent **16/16** unit tests PASS. Negative cases include false reboot, stale Task receipt, bad Ed25519 verifier, extra Task action or wrong owner, trigger drift, old PID mismatch, wrong Serve target, process predating boot, private unhealthy, widened signature authority. The original source revision had 14/14 tests PASS; after a concrete review improvement to require exact owner, one action and two trigger identities, the final exact-source owner run was **16/16 PASS**.

**Actual baseline execution at ~16:15 JST:** `status=PASS` exit0, boot `2026-11-10T05:24:48.500000+00:00` unchanged, native Task last run `2026-11-11T07:15:01Z`, result0, fresh guard receipt `2026-11-11T07:15:05.769044Z`, SHA256 `fdf66fcb4f856858bffa6d61e564228356fb77ef49d6b0ea325eb329aef9d9b6`. Candidate PID8976, original PID15900, private PID5740 all owned/healthy. Existing Ed25519 V2 signer verifier PASS. Funnel8443→8879, external FQDN from **owner host** root/health200, private favorites404, CSP/nosniff/XFrame DENY. `reboot_since_baseline_proven=false` and `every_five_minute_tick_proven=false` correctly reported.

**Actual false-reboot rejection:** immediately invoking `--after-relogin --baseline-boot-utc 2026-11-10T05:24:48.5000000Z` returned `status=HOLD`, `reason=NO_NEW_BOOT_PROVEN`, **exit2**, as required. No Windows restart happened.

**Concrete sampling caveat:** one earlier QA invocation overlapped the naturally executing 16:15 Task and returned `TASK_NATIVE_RESULT_HOLD`/transient `TASK_ID_OR_STATE_HOLD` while Task was running. Independent native Task and receipt reread at **16:15:28 JST** showed it had returned `Ready`, last result0, no misses and fresh `PASS` receipt. Re-running **once** outside that short in-progress window returned actual baseline PASS and false-reboot HOLD. This was a timing-dependent sample, not proof of a service failure, and the reader correctly fails closed instead of labelling an in-progress Task as accepted. Future operator should sample outside the scheduled five-minute boundary; investigate only a persistent concrete HOLD.

## Next unchanged gates

Existing one-time **2026-11-12 10:30 JST** ~24h endurance acceptance remains scheduled independently; do not duplicate or move it. Only after separately authorized shared CMP08/CMP24 physical reboot/relogin: use the actual preboot timestamp, execute the same pinned read-only script once, and require later OS boot and fresh V2 Task/receipt plus the existing CMP08 cross-campaign check. iPhone, third-party network and formal RLO CMP20 canonical campaign registration remain separate pending gates. No signature grants OS reboot or RLO campaign creation.
