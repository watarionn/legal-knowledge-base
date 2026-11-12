# CMP-20: isolated owner-signed V3 candidate-only recovery acceptance

## Fixed scope, live production safety and authority

This is a **new two-key Ed25519 purpose** specifically for one-time fault injection on the *already signed and currently healthy* candidate public demo `127.0.0.1:8879`. It does not extend the V3 guardian's prior grant. The public HTTPS Funnel `:8443` must switch to the *preserved and independently healthy original* `:8878` **before** the candidate is stopped; the private `:8877`, original process, original DB and unrelated Tasks/Serve routes are never modified. Actual candidate PID identity is checked by the existing immutable signed V2 `stop_candidate_only()`. The fault script never manually starts the guardian or candidate: the existing signed V3 **natural** PT5M Task must recover the candidate. A separate signed `--finish` action requires `LastTaskResult=0` *after* the injected fault and `candidate_recovered=true` in the time-bound signed V3 receipt, then restores exactly HTTPS8443 original8878→candidate8879. If the test fails after fallback, original public remains serving users; no forced fallback to stale candidate. No OS restart, Task mutation, broader process authority, or new unauthenticated executor.

Reviewed source names:
- `scripts/cmp20_v3_candidate_drill_verify.py` (source-bound two-role independent Ed25519 manifest and sealed V3 release verification)
- `scripts/cmp20_v3_candidate_drill_owner.py` (owner-only fixed `--enroll`, `--issue`, `--stage`, `--drill`, `--finish`, and `--inspect` with explicit protected private evidence)
- `tests/test_cmp20_v3_candidate_drill.py` (positive and strict negative source-only gates)

The signer uses **new owner-private** keys in `%LOCALAPPDATA%\RinkaMissionControl\owner_approvals\cmp20-v3-candidate-drill-owner-v1` with the previously reviewed owner private ACL helper Git blob `4199852e192349270096807af52d358ee89afe2b`. It pins the original V3 two-role packet SHA256 `e8e4439b62a2d03d6703f62581887cd3e2bb8d48f578e64859beba76b95d5c2c` and unchanged V3 source blobs `8caff01ddb6f8d3f8619ed5d628f04b51de84eb1`, `44d7ac23e5d30c80e9287e3e27ab443f326efd5b`. No source edits to V1/V2/V3 signed releases. Private keys/packets are never committed to GitHub.

## Initial source-only owner QA, 2026-11-12

Isolated existing owner QA root `RinkaMissionControl\cmp20-headless-v3-qa-20261112\drill-20261112` actually received exact branch blobs:
- `cmp20_v3_candidate_drill_verify.py`: `4d09991e9d8e624eb67ca4f7d96962fb843228f9`
- `cmp20_v3_candidate_drill_owner.py`: `0935d5bee16e6c445b1dbcc4ef1739c45e075c35`
- `test_cmp20_v3_candidate_drill.py`: `6d80ada7de097963c5cd1c89ea54c211080ec52f`
- Existing standalone ACL signer helper: `4199852e192349270096807af52d358ee89afe2b`

`C:\Python314\python.exe -B -m unittest discover ...`: **25/25 PASS**, including independently different keys, signature mismatch, code/hash/port/Task alteration rejection, original PID preservation and no false recovery from an unrelated/stale Task. Exact source blobs matched GitHub. `--inspect` returned `READ_ONLY_DRILL_SOURCE` with `trust_created=false`, `release_staged=false`, `drill_started=false`, `drill_completed=false`. This is a **source implementation and tests**, not proof that any actual live candidate has been stopped or restarted.

## Required bounded runtime gate

After reviewed code reaches main, owner verifies exact main Git blobs and expressly authorizes new purpose-key enroll + packet issue with independent `trust.json` SHA256, protected ACL readback and private immutable stage. Only the approved owner fixed action `--drill` may run, after actual current natural Task PASS/missed0, healthy original/private/candidate and public :8443→candidate route. The script requires at least 60 seconds before the next automatic Task tick to avoid races. Immediately inspect protected drill-start receipt, independently verify public :8443→original :8878 and private :8877 normal while candidate is absent. Do not manually trigger guardian.

Allow existing V3 periodic Task to run; **verify native LastRun later than drill start with result0 and signed new `candidate_recovered=true` receipt** and changed candidate PID. Run separately signed `--finish` before its special recovered receipt can be overwritten by another 5-minute natural tick, restoring public :8443→candidate without interruption to preserved original/private. Read back both protected receipt files, original/new/private health, private API404 and CSP/nosniff. On any gate failure leave service safely served by original and report precise HOLD; do not pretend the drill succeeded or kill an unrelated process.

CMP-20 complete campaign still separately requires owner iPhone + cellular and no visible CMD UX reports, 24h V3 soak if required, owner-authorized RLO campaign registration and legal Issue #54 closeout/readback. Those are distinct from the drill.

## Signed V3 isolated import-path correction (owner preflight)

Before enrolling any extra keys, genuine owner isolated QA performed the release dependency probe. It initially returned `HOLD/ModuleNotFoundError` while reading the original signed V3 guard by file path, because that guard imports its matching signed verifier via standard module name but the isolated QA does not automatically include the sealed V3 release directory on `sys.path`. No keys, Task, PID or Serve routing were mutated. The separate drill source now **first verifies the exact independent signed V3 verifier Git blob** and then adds only the existing sealed V3 release path to `sys.path` (no file copy, no PYTHONPATH global changes or sealed V3 edits). Two tests reject mismatched V3 bytes and check the exact import path. Re-run the same owner preflight gate once; if PASS continue to source-bound signing, otherwise HOLD with exact failure.
