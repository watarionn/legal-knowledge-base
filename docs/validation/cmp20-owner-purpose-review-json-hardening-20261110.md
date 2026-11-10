# CMP-20 owner review JSON strictness repair (2026-11-10)

## Reason and isolated source change

The existing review verifier used Python default `json.loads` for owner `trust.json`, `manifest.json`, `packet.json` and the SHA-pinned unsigned stage. Python accepts repeated JSON object keys (last value wins), `NaN` / `Infinity` and numerical exponent overflow even though these are ambiguous or nonstandard JSON. Duplicate keys must not cross the owner cryptographic evidence boundary.

This source-only correction adds `strict_json` to the independent verifier. It rejects repeated keys at any depth, nonstandard NaN/Infinity constants, nonfinite exponent results, invalid UTF-8 and nonobject top levels. The signer now parses the exact already SHA-checked `trust.json` bytes through the same pinned strict verifier and refuses symlink/junction or oversized trust files. Existing positive canonical JSON, purpose, two-role Ed25519 signatures, stage SHA, source SHA and `REVIEW_ONLY_NOT_EXECUTION` flags remain unchanged.

The signer `REVIEW_VERIFIER_BLOB` pin is updated to the new verifier Git blob. Negative tests exercise nested repeated keys and nonfinite values; a valid nested JSON control remains accepted. Nothing signs or issues an owner packet in this change.

## Boundary

This is a GitHub source correction only, not owner Windows acceptance, not a key enrollment and not a production release. Existing unsigned stage and original owner public runtime remain untouched. Before any future owner enrollment the exact signer/reviewer source blobs, their linked pin and Windows ACL behavior must be tested on the owner PC. Independent real owner consent remains mandatory. Separate execution/rollback grant, cooperative public process handoff and the joint CMP08 maintenance reboot remain OPEN.

CMP20 remains `PROJECT_SOURCE_VERIFIED_CAMPAIGN_OPEN` and noncanonical. Do not treat a source merge, review PASS or this fix as Task execution authority.
