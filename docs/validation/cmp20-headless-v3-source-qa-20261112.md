# CMP-20 windowless guardian V3: source implementation and owner cutover procedure

## Scope

This is a **new source-only, not-yet-issued/not-yet-installed** purpose-specific V3 successor to the existing signed V2 public guardian. It exists because the owner requires **no recurring CMD/console flashes** and owner Windows Task `RinkaLegalKBPublicGuardedOnceV2` now uses `pythonw.exe` while its immutable V2 guardian expects `python.exe` and returns `LastTaskResult=2`. Do not silently revert the owner UX choice.

Primary sources:
- `scripts/cmp20_headless_v3_verify.py`: independent two-role Ed25519 exact-manifest and unchanged V2/V1 signed release verification
- `scripts/cmp20_headless_v3_guard.py`: `pythonw.exe` only, exact fixed public-only recovery using the immutable V2 signed helpers and their existing lock; Windows `CREATE_NO_WINDOW` + `SW_HIDE` for all child PowerShell processes; fail-closed, protected V3 private PASS/HOLD receipts with bounded diagnostic metadata, no original `:8878` process stop, no private DB changes
- `scripts/cmp20_headless_v3_owner.py`: exact owner two-role key and source issuance, readback, immutable signed stage, **new disabled** `RinkaLegalKBPublicGuardedOnceV3` Task, verified V2 action preimage + Task XML backup, disable only the known currently failing V2 Task and enable V3, rollback that only reverses the two Task enabled states
- `tests/test_cmp20_headless_v3.py`: source-only signer and Task identity negative tests, no-prompt Windows process flags and mocked recovery

**Not permitted:** generic OS restart, any control of other Tasks or Daemons, broad commands from GitHub Issues, alteration of existing V1/V2 signed files, private database or original public `:8878` child, opportunistic force termination of an unhealthy `:8879` listener. A source file, PR merge or an existing V2 owner packet **does not authorize** V3 Task creation/cutover.

## Real owner source-only QA (2026-11-12 JST)

Exact branch Git blobs were copied into the existing owner-private QA root `%LOCALAPPDATA%\RinkaMissionControl\cmp20-headless-v3-qa-20261112\scripts` and separate `tests`, no changes in original project worktree or live Task. Files verified against actual Git blob via `git hash-object --no-filters`:

| File | Git blob |
| --- | --- |
| `cmp20_headless_v3_verify.py` | `8caff01ddb6f8d3f8619ed5d628f04b51de84eb1` |
| `cmp20_headless_v3_guard.py` | `44d7ac23e5d30c80e9287e3e27ab443f326efd5b` |
| `cmp20_headless_v3_owner.py` | `b30ee0ffe175c4c4179dd32be32ec428da6e6e51` |
| `test_cmp20_headless_v3.py` | `6c4d144d1ca2cc2a3496971d7b7287f30cb0835c` |

Owner `C:\Python314\python.exe -B -m unittest discover ... -v`: **26/26 PASS**, including distinct Ed25519 roles, signature rejection, privilege expansion rejection, exact Tasks/trigger/owner/executable, lock scope, unknown Task denial, no signature no runtime, no stop of occupied unhealthy candidate, and the actual Win32 `CREATE_NO_WINDOW/SW_HIDE` subprocess adapter. Existing **V2 independent signature** and actual owner immutable V2 source were read/verified `PASS`; owner V3 `--inspect` returned read-only `READ_ONLY_V3_SOURCES` with V3 Task/trust/release all absent. These tests do **not** prove a real scheduled `pythonw` V3 tick, absence of visible windows perceived by the owner, or a new V3 signature packet.

## Rollout gates (owner protected, no project permission widening)

1. Review exact source and tests on GitHub main, then independently re-fetch source Git blobs on the owner. Source signed in-place under owner-private QA, not from an unreviewed local worktree.
2. Explicit separate owner authorization for V3 Ed25519 key enrollment and distinct packet issuance. The reviewed CLI supports `--enroll --owner-consent 'ENROLL CMP20 HEADLESS V3 DUAL OWNER KEYS'` and separately `--issue --owner-consent 'ISSUE CMP20 HEADLESS V3 PURPOSE SIGNATURE' <independently-read-trust-SHA256>`. Issue action refuses unbound signer fields and source changes. Private keys must never leave protected owner storage. Do **not** infer this consent merely from a merged PR.
3. `--stage` requires independent Ed25519 readback and original V2 genuine signature, creates new protected release only, never replaces old release.
4. `--register-disabled` creates a **new disabled** V3 Task with exact `C:\Python314\pythonw.exe`, the signed immutable guardian argument, fixed CWD, Interactive/Limited owner, Logon + Daily/5min, IgnoreNew, AllowHardTerminate=false, on-demand disabled. Refuses existing V3 Task or original V2 Task identity drift.
5. `--cutover` requires actual original/public/private health and HTTPS8443 route still on `:8879`; native **V2 Task preimage is backed up in the private protected release before any Task change**; exact CAS verifies both source Tasks. Disables the existing V2 Task and enables the already registered V3 only. No process stop, source/Serve change, or reboot. Run a real 5-minute scheduled tick, match independent Task LastTaskResult=0 and new V3 receipt `PASS`.
6. To prove automatic recovery, use a **separately authorized** candidate-only fault drill with public fallback and bounded readback, never force-kill other processes; obtain 8878/8879/8877 health200, public HTTPS8443/root200, favorites404, CSP/nosniff and retained original PID. Owner visual acceptance confirms no flashing CMD.
7. Rollback disables only V3 and re-enables the original action-exact V2 Task; the V2 is **already HOLD** under its existing `pythonw` drift, so rollback is **non-destructive to HTTP**, not a guaranteed monitoring PASS. Keep signed V1/V2 historical assets intact, record and escalate that degraded rollback state rather than claiming otherwise.

**Final CMP20 closeout is still separate** from V3 installation: user iPhone/outside-network acceptance, reviewed RLO canonical `creation_authorized=false` adoption decision, legal product acceptance links, formal open Issue #54 closure/readback. Source QA is not production.
