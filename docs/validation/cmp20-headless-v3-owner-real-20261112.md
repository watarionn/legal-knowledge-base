# CMP-20: real owner-signed V3 silent Task cutover, genuine natural 5-minute tick (2026-11-12 JST)

## Goal and current verdict

**Scoped operational result: `HEADLESS_V3_SIGNED_RELEASE_TASK_AND_FIRST_NATURAL_TICK_PASS`. Full CMP-20 canonical campaign closure: `OPEN`.** Real owner YWSHTMR physical post-shared-reboot boot `2026-11-12T03:03:46.5000000Z`, earlier old V2 signed natural Task 12:25 PASS but subsequent external change at 12:31 to `pythonw.exe` invalidated the original immutable V2 action guard. Respect owner's explicit no-CMD-popup UX preference; no rollback to `python.exe`.

## Source and review

- PR #63 source-only V3 implementation squash merged to LegalKB main `f95753b74e8aff0a5f0f0651d02f5361749ff59a`: immutable-source-bound independent Ed25519 V3 verifier, private issuer and new Task cutover, windowless `pythonw` fixed-scope original V2-protected recovery with all child PowerShell `CREATE_NO_WINDOW/SW_HIDE`, separate V3 PASS/HOLD receipts and exact rollback.
- PR #64 fixes a **real protected signer dependency failure** from source-only V3: original immutable V2 release deliberately does not contain the historical review signing/ACL helper. The first V3 enrollment returned HOLD without creating trust or keys/Task. Fixed new V3 owner source to load reviewed standalone `cmp20_public_release_owner_signer.py` **Git blob `4199852e192349270096807af52d358ee89afe2b`** from isolated owner QA, never altering V2 release. Fix squash merged `e07ad3ae1a54358eec073551777fed26f61b91cd`, owner source Git blob `ceaa4b42bd3413fe038ba5eef59fce6e2bf6571d` and 27 tests blob `0973c64969c646fb046b480981bcac3a1e41c2fa`, both read from main.
- Actual owner `C:\Python314\python.exe -B -m unittest discover` **27/27 PASS**, including independent issuer/reviewer roles, unsigned/tampered schema denial, fixed task identity, no force-stop of non-owned candidate and Windows `CREATE_NO_WINDOW/SW_HIDE` adapter. The V3 operator `--inspect` validated old V2 signed grant PASS and V2 Task exact `pythonw` drift, without source/Task mutation.

## Real owner V3 signatures and protected staging

- New private V3 owner-specific Ed25519 `issuer` + `reviewer` distinct keys actually enrolled under existing `%LOCALAPPDATA%\RinkaMissionControl\owner_approvals\cmp20-headless-guard-owner-v3`. Independent `trust.json` SHA256 **`f41164da6b8f93587f83134d13071f59a400ee739a6a828575aeec712171d538`**.
- Separate genuine private signed V3 manifest SHA256 **`b0552426b2041de294ccf0e4c468833dc45706db83d89a1c2bce82a5d103111e`** and two-role signed packet SHA256 **`e8e4439b62a2d03d6703f62581887cd3e2bb8d48f578e64859beba76b95d5c2c`**, generated using independently pinned trust SHA and reviewed all-three-source Git blobs. Never exported private signing keys or put private files in repo.
- Owner/SYSTEM/Admin-only DACL real readback with `AreAccessRulesProtected=true`, exactly 3 rules, owner SID `S-1-5-21-2008575412-695584821-1269537588-1001` on trust root/keys folder/two private keys/trust/manifest/packet. `--stage` only created new private release `cmp20-headless-guard-owner-v3` with reviewed files; new independent `cmp20_headless_v3_verify.py --verify` returned **PASS**, including original immutable V2 Ed25519 PASS.
- Installed V3 source Git blobs from main: verifier `8caff01ddb6f8d3f8619ed5d628f04b51de84eb1`, windowless guardian `44d7ac23e5d30c80e9287e3e27ab443f326efd5b`, owner action `ceaa4b42bd3413fe038ba5eef59fce6e2bf6571d`.

## Actual owner Task transition and readback

1. Signed `--register-disabled`: created exact **new** Task `RinkaLegalKBPublicGuardedOnceV3` disabled, `C:\Python314\pythonw.exe` and fixed owner-private signed `--once` action, owner Interactive/Limited, one Daily PT5M/P1D and one owner Logon trigger, IgnoreNew, no hard termination/on-demand. Existing V2 Task unchanged in registration stage.
2. Signed and preimage-CAS-guarded `--cutover` required owner healthy original public :8878, private :8877, candidate :8879, and public HTTPS8443 Funnel routed to :8879. Protected backup of the exact original V2 Task XML SHA256 **`e8ff8b019c3c2f9e29a4fd974cc23a0c15c7c5d20d2fddafaa363fe29a05347f`** created/read back before touching Task definitions. Then exact old `RinkaLegalKBPublicGuardedOnceV2` **Disabled**; new `RinkaLegalKBPublicGuardedOnceV3` **Ready**. Native Task/source/trigger readback PASS. No service process stop, original public/private data change, unrelated Task change, OS restart or Tailscale/Funnel mutation.
3. **First genuine natural scheduled V3 tick `2026-11-12T14:15:01+09:00`** returned `LastTaskResult=0`, Task Ready, next 14:20. New signed `last-pass.json` SHA256 **`8f38fd0ffacc8d82fe255aad16c1559d2cb37b08c1f3981c8af839fb71fdfff0`**, `status=PASS` checked 14:15:08, `pythonw_headless=true`, candidate PID9900, original PID12736, `candidate_recovered=false`, old/public/private health healthy and route exactly 8879, signed two-role grant, no other Task mutation.
4. **Separate immutable-source owner read-only V3 acceptance** `scripts/cmp20_headless_v3_owner_acceptance_readonly.py`: source Git blob `4e9070b6510dbb381b1d37aba829e69c54d897c4`; pure test source blob `19921aced384706de09a4fcfc7ded9361a9ff5ec` **12/12 PASS** on actual owner Windows 3.14. Actual `--after-cutover` returned **PASS/exit0**, new physical boot proven, native Task last result0, matched timestamp-bound current signed V3 receipt SHA, original and candidate process PIDs, public HTTPS/private isolation, no additional Task mutation. Owner-network only. No source/Task/DB mutation from the read-only acceptance.

## Clearly separate remaining gates

- Another genuine natural V3 5-minute tick over time, fresh receipt and 8877/8878/8879/8443 should be sampled to verify persistence (first actual tick already PASS). No 24-hour V3 soak can be claimed yet.
- **Candidate-only failure drill under a newly scoped owner authorization** is not yet performed for V3; V3 intentionally refuses force-killing an unhealthy :8879 listener. Old V2 previously passed real fault recovery before its signed Task drift. Do not use unsigned or unreviewed Task/stop controls.
- **No popup UX observation by owner** is confirmed. Code and Windows Task enforce `pythonw.exe` + `CREATE_NO_WINDOW/SW_HIDE`, but visual acceptance is the owner's separate check.
- **iPhone or independent outside-network acceptance** of public LegalKB remains unverified. Owner-host HTTP200 is not third-party proof. Do not infer external browsing access from its HTTPS URL.
- **RLO CMP-20 canonical registration** is not granted automatically by this source evidence. Existing candidate `creation_authorized=false`, `progress.status=PROJECT_SOURCE_VERIFIED_CAMPAIGN_OPEN`. Requires reviewed registry/owner decision and true source evidence. LegalKB Issue #54 stays OPEN until this + user signoff and formal read-after-write.

**No false campaign COMPLETE declaration from signed V3 startup alone.**
