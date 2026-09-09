# Phase 6.2 Parliamentary Provider Live Validation

Observed: 2026-09-09 JST

Phase 6.2 was validated against the two official National Diet Library proceedings APIs. Requests were serialized with a 3.2 second minimum interval. No provider payload or speech body is committed to Git.

## Providers

- National Diet minutes: `https://kokkai.ndl.go.jp/api/meeting`
- Imperial Diet minutes: `https://teikokugikai-i.ndl.go.jp/api/emp/meeting`
- Response format: JSON
- Query identity: exact `issueID`
- Meeting fetch size: `maximumRecords=1`

## National Diet live observation

- issueID: `100105254X00119470520`
- session: 1
- held on: 1947-05-20
- speech records: 9
- first speechID: `100105254X00119470520_000`
- last speechID: `100105254X00119470520_008`
- response SHA-256: `89fa44e483df16bd07169ca2794af1777efca66942c86a1ecf3a8238bfc77e6d`

## Imperial Diet live observation

- issueID: `009213242X03119470330`
- session: 92
- held on: 1947-03-30
- speech records: 94
- first speechID: `009213242X03119470330_000`
- last speechID: `009213242X03119470330_093`
- response SHA-256: `9ccce61e5b339a954b825c061852d994add5a0e1b478028fc33f4443ed539339`

## Persistence validation

Fresh PostgreSQL 18 received:

- external documents: 2
- immutable snapshots: 2
- speech parts: 103
- speech observations: 103
- missing `parliamentary_part_provenance()` source SHA: 0
- database URL recorded in public metadata: false
- credentials recorded in public metadata: false

Result marker: `PHASE62_LIVE_PROVIDER_INGEST_OK`
