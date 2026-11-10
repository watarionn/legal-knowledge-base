# CMP-20: owner-signed parallel public-only live release and exact rollback (2026-11-11)

## Reviewed production boundary

The original Phase8 LegalKB public runtime remains Git `4acdda5aac833a30189858ff1e43c34ada23c839`, tracked-clean, `127.0.0.1:8878`, served by Tailscale Funnel `https://ywshtmr.tail8fd68c.ts.net:8443`. The unrelated private runtime is `127.0.0.1:8877`. Its original PowerShell/DPAPI launcher SHA256 is `fa806751be935fd93c4650a56171c9615c2ce3550acb222e233b038e0e32a77f`, and its old server Git blob is `a394f509b51fe598eb0f1852339ba7f21e2be9b4`. **Neither source, process nor private database is overwritten by this release.**

The owner-approved REVIEW-ONLY Ed25519 packet SHA256 `6bee779804cb0e9ef516eb3d5898107fcc9fa0d17a38b3d6d38459ee12f19e88` was already verified with two independent owner roles and protected ACL (LegalKB PR #55). It does **not** itself authorize production.

### Narrowly separate NEW execution authorization

`scripts/cmp20_public_parallel_exec_signer.py` enrolls a **new, purpose-distinct** issuer/reviewer key pair under `%LOCALAPPDATA%/RinkaMissionControl/owner_approvals/cmp20-public-demo-parallel-exec-v1`, and signs only the independently verified existing review, owner original source SHA, reviewed unsigned patch manifest SHA256 `9b8730abdfe399b9f8d9bf86e95fac0b9063236f214c306c439da4588b80374f`, patch blob `511f5070c8c3fac8e733b35cb897868dca77369c`, exact reviewed owner-action and overlay source blobs and four allowed actions:

- `stage`: create a **new** versioned, owner-private protected release folder and exact bytes, no change to live worktree;
- `start_parallel_8879`: run a source-checked patched public server at a distinct loopback port `:8879` while keeping `:8878` and `:8877` alive;
- `switch_public_8443`: only after both local public workers and the private app are healthy, switch Funnel HTTPS 8443's exact root target from `127.0.0.1:8878` to `127.0.0.1:8879`;
- `restore_public_8878`: exact original HTTPS8443 Funnel target restore even if the candidate :8879 worker has failed.

`scripts/cmp20_public_parallel_exec_verify.py` is an independent two-role Ed25519 verifier with strict JSON parsing, exact purpose, signed statement, stage/review SHA, fixed port/host and runtime source SHA checks. Review keys are never reused. **No blanket signature**: old public process termination, Windows Task registration/changes, private DB/8877 modification, OS reboot, Tailscale `reset`, other port changes and source modifications are all denied.

### Fixed source process and rollback

The original launcher is read SHA-pinned and transformed by seven exact text matches in memory. The transformed private release launcher retains original owner-only DPAPI credential loading and original worktree safety checks, but starts a source-pinned Python overlay on :8879. The overlay executes the **reviewed, SHA-pinned WinError10055 bounded retry** source in memory, with `__file__` set to the original immutable server path to reuse its verified Phase7 dependencies/web assets; it does not mutate old tracked files. It uses `PYTHONDONTWRITEBYTECODE=1` to avoid importer side effects. Generated launcher, overlay, patch and manifest are read back, protected and checked before execution.

The signed action checks that Tailscale `Web` and `AllowFunnel` state exactly match the preimage, uses fixed `tailscale funnel --bg --yes --https=8443 <literal target>` (never `reset`) and checks the **entire** Serve state after switching, not only 8443. If the mutation or HTTPS owner readback fails, it attempts to restore the **exact** original route and rejects if full rollback readback differs. The original :8878 process stays alive as the rollback destination, even after a successful switch.

### Runbook, only after owner executable signature issuance

1. Verify owner original worktree/launcher, public/private status, current Funnel proxy, protected original REVIEW-ONLY packet, unchanged reviewed stage, source Git blob hashes and exact new signed execution keys/packet.
2. Run `cmp20_public_parallel_exec_signer.py enroll-execution` and `issue-execution` under **separate explicit owner execution consent**, with an independent trust SHA check, and verify the packet using the independent `cmp20_public_parallel_exec_verify.py --verify`. Store only trust/manifest/packet SHA receipts; NEVER export secret key bytes.
3. Run the SHA-pinned owner action `--stage`, then `--start-parallel`. Check owner :8878/:8879 and private :8877 HTTP200, public mode/correct app version, process identity, signed bytes, and unchanged Funnel.
4. Run the exact signed owner action `--cutover` to serve :8879 over existing HTTPS8443, verify HTTP200, root, public-security headers, private API remains 404, private8877 unaffected, all other Tailscale Serve/Funnel routes identical.
5. On any failure, signed `--rollback` restores :8443→:8878 without stopping either service. Since this purpose's grant **explicitly forbids** Task changes or reboot, a separate owner-signed auto-resume/Task acceptance will be required before calling the service 24/7 durable or the CMP20 campaign completed.

No Postgres migrations, public role escalation, personal data access, old-process kill, forced OS logout/reboot, GitHub Actions, or unreviewed source patch is part of this release. Physical OS reboot is separately deferred for coordination with CMP08/CMP24. Actual execution and rollback receipts must be written to this document only **after** owner readback, not guessed from PR merge.

## QA prior to owner signature or production

Owner YWSHTMR isolated **seven exact Git blobs** matched the reviewed branch including source, signer, independent verifier, signed overlay and tests. Python3.14 compilation PASS, **27/27 signed-scope negative/positive tests PASS** including wrong role, forged authority, original-launcher structure drift, SHA binding, no reboot/old process stop, private mode refusal and rollback without candidate health. The original live launcher SHA and source, reviewed patch SHA, and in-memory actual generated :8879 launcher were verified without runtime or Task changes; new deterministic generated launcher SHA256 `cbb4bac8b80d5e5368a602ad8e8790158ea8fb5d330c028bf0d9fcad4f7ee763`. This is SOURCE/STAGING QA **only** before genuine owner execution packet and actual cutover.
