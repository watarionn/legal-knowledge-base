# Phase 6.4 NDL Legislative Metadata live validation

Date: 2026-09-10

## Scope

Phase 6.4 validates a bounded NDL Search metadata path:

1. SRU exact item discovery with `maximumRecords=1`
2. serial wait of at least 3 seconds
3. OAI-PMH `GetRecord` with `metadataPrefix=dcndl_v3`
4. immutable raw XML persistence in Phase 3 `source_file`
5. projection persistence in `ndl_metadata_observation`

`ListRecords` bulk harvesting is not enabled by this adapter path.

## Live record

- provider: `ndl-search`
- SRU exact match count: 1
- OAI identifier: `oai:ndlsearch.ndl.go.jp:R000000004-I026731256`
- repository number: `R000000004`
- item number: `026731256`
- OAI datestamp: `2026-01-12T16:30:00Z`
- setSpec: `article`, `zassaku`
- metadata prefix: `dcndl_v3`
## Payload evidence

- OAI raw XML bytes: 6,250
- OAI payload SHA-256: `04d63e6a1e1d29b755e4990c8637496233b6b5996fc7aeeee8b9ae5e1df52526`
- metadata XML SHA-256: `c828792d92c570d8dbf7e5839c9c7e1e03b26edc63a8563025a539afbefda0b7`
- SRU response SHA-256: `285c67aed6fb894359cf6733398b5a7f58507a4374ce60407c212df45bbb04d6`
- title projection: `アートな時間 舞台 真珠の首飾り : 日本国憲法の草案作りの内幕 男女平等を目指す22歳のベアテ`
- issued-on projection: `2015-09-22`

The raw XML itself is not committed to Git. The SHA values and reproducible validation procedure are retained instead.

## Safety / source-truth boundaries

- requests are serial: true
- minimum interval: 3.0 seconds
- bulk `ListRecords`: disabled
- automatic legal relations: 0
- credentials recorded: false
- database URL recorded: false
- OAI metadata is an external bibliographic source, not Phase 3/4 law-text truth
- SRU output is discovery evidence only; OAI `identifier` is the logical document identity
- deleted OAI records are persisted as tombstone observations rather than deleting prior snapshots
