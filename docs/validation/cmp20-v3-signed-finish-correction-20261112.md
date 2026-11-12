# CMP-20: independently signed 8878→recovered8879 exact V3 fault completion correction

## Concrete fault in the first independently signed drill (2026-11-12)

The **separate owner dual-role Ed25519 drill** genuinely completed a safe fault injection: 15:10:24–15:10:34 JST public HTTPS8443 was redirected to preserved original8878 before stopping only exact candidate8879 PID9900, primary protected signed start receipt SHA256 `99ec7c2f0ab8d0d83cdf15c6d4bf0df6683ae3489de8c00d5d7c3cca32eb3d8b`. Subsequent 15:15:01 genuine scheduled V3 Task `LastTaskResult=0`, new candidate PID **15972** and actual V3 signed receipt `candidate_recovered=true`, `old_public_pid=12736`, `candidate_pid=15972`, private/original/candidate/public200; SHA256 `11d6b4de644c0e6169d0b82e625ac6624b289d34bf96e2efb61855394db2191b`. The exact 15:15 V3 receipt bytes were copied into original drill's owner-private protected release as `verified-natural-recovery-20261112.json` with exact SHA reread; reviewed owner ACL helper protected DACL without changing bytes. Original :8878, private :8877 and candidate :8879 remained healthy while public `:8443→:8878` stayed safely live.

**Actual cause of the first `--finish` HOLD:** its check mistakenly required `v3_receipt["original_public_pid"]`, but the sealed authentic V3 receipt schema uses **`old_public_pid`**. An isolated read-only gate-by-gate diagnosis pinpointed `V3_SIGNED_NATURAL_RECOVERY_NOT_PROVEN` while other genuine V3 signature/native Task/source gates passed. This is a source schema mistake in the drill *completion reader*, not evidence of failed natural recovery. The first signed drill release, code and packet are immutable and **must not be silently edited or re-signed in place**.

## Narrow corrective signed successor

New exact source `scripts/cmp20_v3_finish_verify_v2.py` and `scripts/cmp20_v3_finish_owner_v2.py` create a **separate purpose-bound two-key owner Ed25519** corrective action. The new manifest binds: original first-drill packet SHA256 `3f85a01b1030d4dc6645fe52d7792a9c13a60b02cdbbcae722ae6a7a2354a8d0`, its exact two Git source blobs, the original start receipt SHA and the preserved genuine V3 naturally recovered receipt SHA, owner host, fixed original public PID12736, stopped candidate PID9900 and recovered PID15972, and the **single allowed public 8443 route `127.0.0.1:8878→127.0.0.1:8879`**. Deny arbitrary process stop, OS reboot, Task/DB change, or other routes.

`--finish` independently validates the earlier two-role signed grant and exact bytes of both receipts, uses the **correct actual `old_public_pid` field**, checks current V3 native Task natural LastResult0/missed0, protects original8878/private8877 and verifies current candidate8879 PID15972. It then switches only public Funnel to the recovered candidate and writes a protected completed receipt. On any mismatch, it HOLDs without replacing the original safe public route. The existing signed V3 headless worker, task, original V2 and first signed drill remain byte-identical.

## Exact owner source-only verification and current state

Isolated actual owner QA root `%LOCALAPPDATA%\RinkaMissionControl\cmp20-headless-v3-qa-20261112\finish-v2-20261112` received exact Git blobs:
- new verifier: `a02dda6159030c8fa99221ec613b2d76a754a19c`
- new fixed owner executable: `950fd992ee8c3382dfe50f7e342f9734e30a620e`
- source-only 16 negative and positive tests: `5fc04ba795748573aa4df6ad1856d2b52bcf80dd`
- reviewed ACL/signer helper: `4199852e192349270096807af52d358ee89afe2b`

Real Windows CPython3.14 **16/16 tests PASS** including exact authentic `old_public_pid`, rejection of the incorrect legacy field name, unsigned/changed signatures, route/PID/task misuse, stale recovery and unrelated process-stop permissions. Read-only `--inspect` returned no new trust/release/finish receipt. At this document stage **the corrective new grant has not yet been issued and the public is still on original :8878**. Source-only test PASS is not a completed live cutover; preserve separate actual issuer and native HTTPS/PID/readback proof after approved installation.

## Recurrence prevention

Require every receipt-field assumption in new owner action to be checked against the **actual installed sealed producer schema**, not a guessed English synonym; bind it in a positive test using recorded real field names and a separate wrong-key rejection test before signing. Any new correction requires new purpose-specific signed source/manifest and protected readback, never hot-patching sealed scripts or weakening their fail-closed gate.
