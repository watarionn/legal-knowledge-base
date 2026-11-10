# CMP-20 Owner Windows public-demo release readiness: audited as actually OPEN (2026-11-10)

## Primary source and current product

LegalKB Phase1–8 **project** is already complete under the 2026-09-17 Phase8 Completion Gate, including 200/200 offline tests, evidence-only public demo, source/revision provenance and public safe subset. This historical product completion is preserved and is **not** reset by later operational incidents. Exact primary source: [Project closeout](../codex/LEGAL_KB_PROJECT_CLOSEOUT_HANDOFF.md), [Phase8 gate](phase8-completion-gate-20260917.json).

At 2026-11-10 **23:29–23:31 JST**, owner PC YWSHTMR independently verified:
- Original live public checkout `%USERPROFILE%/Documents/LegalKB/public-demo-runtime/app-candidate` remains Git HEAD `4acdda5aac833a30189858ff1e43c34ada23c839` and tracked clean.
- Original public launcher SHA256 `fa806751be935fd93c4650a56171c9615c2ce3550acb222e233b038e0e32a77f`; original logon Task `LegalKB Public Demo Runtime` is Ready, last Task exit0, existing 8878 listener process is alive.
- Public owner HTTPS root and `/api/v1/health` both HTTP200; health `status=ok,mode=public-demo`; `/api/v1/favorites` remains HTTP404; CSP and `X-Content-Type-Options:nosniff` present.
- Local public 8878 and **separate private 8877** `/api/v1/health` HTTP200.
- Previously reviewed owner `scripts/cmp20_public_runtime_inspect.py --inspect` exact source Git blob `33f0e3549f881bb5f9f5267b7ae5d6aca5d95ea8`, real owner result `status=HEALTHY` with pinned Task/source/launcher/Funnel/proc/health, `read_only=true` and `owner_execution_authority=false`.

## Genuine release boundary

Original owner immutable unsigned source candidate still contains exactly `003_web_server.py`, `082_public_demo_socket_retry_test.py`, `manifest.json` and manifest SHA256 `9b8730abdfe399b9f8d9bf86e95fac0b9063236f214c306c439da4588b80374f`; [candidate record](cmp20-public-demo-immutable-unsigned-stage-20261110.md). Reviewed PR #49 bounded public-only WinError10055 patch and PR #50 unsigned stage remain **SOURCE ONLY**. Do not claim the live original public process runs the new fix.

Owner-private review trust path `%LOCALAPPDATA%/RinkaMissionControl/owner_approvals/cmp20-public-demo-release-review` was confirmed **absent** on the actual machine, including two independent Ed25519 keys/trust/manifest/packet. Independently executed existing review verifier pinned Git blob `ae7f2cbd01dab3d6dd9823ce340be34ee95bbe3b`; result **HOLD / OWNER_SIGNED_DIRECTORY_MISSING_OR_REPARSE** exit2. This is the correct fail-closed outcome; no signature, consent, or execution grant was invented.

New `scripts/cmp20_public_release_readiness_readonly.py --inspect` combines the exact existing public-runtime inspector, independent pinned owner **unsigned-stage verifier**, the three fixed owner HTTPS safe-subset GETs, and the existing independent owner review signature inspector. It fails closed on unknown source bytes, source drift, wrong public route, missing CSP/nosniff, exposed private endpoint, invalid stage SHA, or forged review execution authority. The output is **`HOLD_FOR_PRODUCTION_CUTOVER`**, with either `OWNER_REVIEW_KEY_ENROLLMENT_AND_PACKET_PENDING` (the observed current state) or `SIGNED_REVIEW_ONLY_SEPARATE_EXECUTION_APPROVAL_PENDING` if a future genuine owner REVIEW-ONLY packet exists. Neither claims deployment, Task execution, CMP20 canonical completion, or OS restart. It never invokes the signer or changes existing signed material, process, DB/DPAPI, Tailscale, Queue or Task.

## Outstanding implementation and owner decisions (do not silently close)

1. Explicit owner consent is required for the dedicated **review-only** Ed25519 key enrollment and **separate** review packet issuance using the checked-in exact owner signer and fixed consent literals; issuance must read back owner ACL/owner-public trust SHA and independently verify the authentic packet. Generic historical source code or current HTTPS200 is not substitute for that consent.
2. **Review is not execution.** Independently reviewed owner-scoped executable release authorization, rollback, cooperative old public child transition and fixed Task lifecycle must be designed, signed, source-pinned and verified; new bounded patch must be stage/activation accepted on actual owner Windows with unchanged private8877, PostgreSQL volume, public security headers and owner HTTPS8443.
3. The old public logon-only Task will not revive its detached child if the latter crashes. Genuine post-crash recovery and WinError10055 root-cause mitigation, no-dual-owner process behavior, automatic restart with bounded rate limits, and longer uptime are operational reliability gates. The shared physical PC reboot remains owner-deferred to maintenance with CMP08/CMP24; **do not reboot unilaterally**.
4. Historical Phase8 evidence/provenance correctness is closed. Separate semantic search relevance and answer quality were explicitly optional/not proven by that historical completion; do not invent metrics or add product scope without a new project decision.
5. CMP-20 in RLO's planning index remains `PROJECT_SOURCE_VERIFIED_CAMPAIGN_OPEN`, `creation_authorized=false`, `canonical_campaign_registered=false`. Owner authorization for formal campaign enrollment, and separate actual production/survival acceptance, must not be inferred from this source-only integration.

This is the current, truthful completion boundary. A successful command exit for tests/source merge is **not** owner signing, production upgrade, or canonical CMP20 closure. No new background task created.

## Verified owner Windows source-only release readiness QA (2026-11-10 23:31 JST)

The final review candidate `cmp20_public_release_readiness_readonly.py`, Git blob `1003df0b21ecc9c2ad59eb076ee8d22e7be3a848`, its tests Git blob `4e3c24cd457165cb4b74e1fbe3d7c1fa92ecd31a`, the original runtime inspector blob `33f0e3549f881bb5f9f5267b7ae5d6aca5d95ea8` and independent owner verifier blob `ae7f2cbd01dab3d6dd9823ce340be34ee95bbe3b` were copied into a new isolated owner Windows QA directory. Independent `git hash-object --no-filters` **4/4 exact source pins PASS**, Python3.14 `py_compile` PASS, **20/20 new tests PASS** including false review grant, wrong source, stage SHA, private route exposure and CSP/nosniff negative paths.

Real owner `--inspect` result, **exit code 2 deliberately meaning release not authorized**:

`status=HOLD_FOR_PRODUCTION_CUTOVER; owner_public_runtime=HEALTHY; immutable_patch_stage=PASS; review_key_or_packet_state=OWNER_REVIEW_KEY_ENROLLMENT_AND_PACKET_PENDING; public_https_root=200; public_https_health=200; private_public_exposure=404; public_security_headers_verified=true; review_signed=false; owner_execution_authority=false; public_new_patch_deployed=false; cmp20_canonical_campaign_completed=false`.

This bounded output was obtained by actual runtime inspection, SHA-pinned stage review and owner self-HTTPS, **not** by simulating a signature or running the new patch in production. The 20 test cases are source-boundary tests, not a substitute for the original Phase8 full regression or an owner executable release action. No new Task, scheduled job, service, file in production, credentials or database was modified.
