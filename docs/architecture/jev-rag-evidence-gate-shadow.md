# Jev RAG Evidence Gate Shadow

Date: 2026-09-23
Status: isolated shadow foundation

## Purpose

Add a bounded semantic evidence-sufficiency check after Phase 5 Evidence Bundle
construction and before answer generation.

The gate does **not** interpret the law, choose a legal outcome, or replace the
strict temporal resolver, hybrid retrieval, provenance validation, citation
truth, or answer-contract validation.

## Placement

```text
strict temporal resolver
  -> hybrid retrieval
  -> Evidence Bundle
  -> Jev evidence-sufficiency shadow gate
  -> existing answer provider / evidence-only response
```

The first rollout is shadow-only. The Jev result does not change the production
query response.

## Decisions

The semantic gate returns one of:

- `sufficient`
- `needs_more_evidence`
- `review`

Low-confidence semantic decisions are normalized to `review`.

Deterministic failures are handled before Jev:

- temporal resolution not resolved
- retrieval status not `ok`
- empty evidence
- cross-revision/source identity drift
- no substantive Sentence evidence

## Authority boundary

Contract: `legal-kb-jev-rag-gate-v1`

The export explicitly sets all of these to false:

- change retrieval
- change temporal resolution
- change citation truth
- suppress answer
- trigger additional retrieval

The generated answer is not included in the export. Jev judges the Evidence
Bundle independently of any answer text.

## Data boundary

Exported data is bounded to:

- question
- as-of date
- selected law metadata
- retrieval query/filter metadata
- up to 8 Evidence Bundles
- bounded source-node text and structural metadata

No database credentials, local paths, answer-provider output, or application
state are exported.

## Initial evaluation

Synthetic benchmark, 8 deliberately clear cases:

- direct definition
- missing exception
- missing referenced subordinate-rule content
- direct prohibition
- unrelated purpose text for a penalty question
- direct deadline
- ambiguous user question
- direct rule at a resolved effective date

Result: **8 / 8 expected shadow decisions** using `jev-1.13.0`.

## Live smoke

Current Phase 8 Public Demo was queried through `/api/v1/query` using an
explicit known law id and an Article 90 question.

Observed upstream state:

- law resolution: resolved
- temporal resolution: resolved
- retrieval: ok
- Evidence Bundles: 2
- answer provider: not configured / evidence-only

The saved response was converted through the Legal KB shadow exporter and then
read by the Jev Lab gate.

Observed gate result:

- deterministic checks: pass
- substantive Sentence evidence: 1
- Jev decision: `sufficient`
- confidence: 0.94
- model: `jev-1.13.0`
- authority flags: all false

## Promotion rule

Do not connect this result to production answer suppression or automatic
retrieval expansion yet.

Next validation should use a broader real-query corpus containing both:
- clearly sufficient evidence,
- deliberately incomplete or cross-reference-dependent evidence.

Only after a pre-registered benchmark should advisory integration be
reconsidered.
