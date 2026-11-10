# CMP-20 owner-signed review-only patch approval: genuine Windows result (2026-11-11 JST)

## Result and exact source scope

**OWNER REVIEW-ONLY SIGNATURE: PASS, independently verified.** The user explicitly authorized both dedicated review key enrollment and review packet issuance on November 11. The true Windows owner `YWSHTMR` executed the already-reviewed, merged source in its isolated QA directory:
- `scripts/cmp20_public_release_owner_signer.py`, pinned Git blob `4199852e192349270096807af52d358ee89afe2b`;
- independent `scripts/cmp20_public_release_review.py`, pinned Git blob `ae7f2cbd01dab3d6dd9823ce340be34ee95bbe3b`;
- pre-existing unchanged unsigned source stage with three exact fixed files and SHA256 manifest `9b8730abdfe399b9f8d9bf86e95fac0b9063236f214c306c439da4588b80374f`.

`enroll-review` returned `ENROLLED_REVIEW_ONLY` exit0; user-owned trust SHA256 was independently reread as `04d6c397ab894d50616ea68a4166574a36e3ad42fd26de04a005d527c012b2bb`. The separately consented `issue-review` used that SHA as an independent trust pin and returned `ISSUED_AND_INDEPENDENTLY_VERIFIED_REVIEW_ONLY` exit0.

| Artifact (owner-private, never GitHub raw contents) | SHA-256 |
| --- | --- |
| `owner_approvals/cmp20-public-demo-release-review/trust.json` | `04d6c397ab894d50616ea68a4166574a36e3ad42fd26de04a005d527c012b2bb` |
| `owner_approvals/cmp20-public-demo-release-review/manifest.json` | `f6af50c116e4eebca6415c2ea726e93d67b80b74f440a2550b174f8e7baff8ec` |
| `owner_approvals/cmp20-public-demo-release-review/packet.json` | `6bee779804cb0e9ef516eb3d5898107fcc9fa0d17a38b3d6d38459ee12f19e88` |

The independent reviewed verifier's actual owner `--verify` response was **`status=PASS` exit0**, `verified_scope=REVIEW_ONLY_NOT_EXECUTION`, two independent valid Ed25519 roles, exact staged source verification PASS, and `owner_execution_authority=false`. Task register/enable, old-process stop, rollback execution and live public runtime modification flags were all false.

## Owner ACL and live production readback

A separate PowerShell `Get-Acl` owner readback verified **all 7 paths** (root directory, keys directory, both role key files, trust, manifest, packet): DACL protection on; exactly three noninherited FullControl ACEs for owner SID, SYSTEM and Administrators; no extra inherited permissions. No private key material was exported or committed.

The previously merged `scripts/cmp20_public_release_readiness_readonly.py --inspect` re-read the actual owner: `status=HOLD_FOR_PRODUCTION_CUTOVER`, `owner_public_runtime=HEALTHY`, `immutable_patch_stage=PASS`, `review_signed=true`, `review_key_or_packet_state=SIGNED_REVIEW_ONLY_SEPARATE_EXECUTION_APPROVAL_PENDING`, public HTTPS root/health200, private-public endpoint404, CSP/nosniff PASS. Crucially `owner_execution_authority=false`, `public_new_patch_deployed=false`, `cmp20_canonical_campaign_completed=false`. Exit2 is the *expected* fail-closed execution gate, **not** a failure of the review-only signature.

The original signed publicly served Phase8 app and private :8877 remain in place. The review signer did not modify Task, process, database, Serve or OS reboot policy. The reviewed source patch is still **NOT deployed**.

## Preserve and next release step

This genuine owner proof closes only CMP20's review-key/packet issuance milestone. The next independent gate requires **new owner-purpose executable cutover + rollback authorization**, exact source SHA, separate fixed cooperative process handoff, stable public HTTPS 8443 / private 8877 and PostgreSQL protections, durable auto-recovery, long-term uptime and the separately coordinated shared reboot. A review packet does not satisfy that execution authorization. Never reuse it as Task or OS permission, infer a production deployment, or mark the planning-only CMP20 candidate formally canonical.

Primary issue receipt, actually posted and API-read back: [LegalKB #54, 2026-11-11 review signature](https://github.com/watarionn/legal-knowledge-base/issues/54#issuecomment-6780672481). Existing [owner cutover readiness handoff](cmp20-owner-release-readiness-current-boundary-20261110.md) and older completed Phase8 primary product evidence remain intact.
