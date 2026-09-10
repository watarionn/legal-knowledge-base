# GitHub Actions cost guard

## Policy

This repository treats avoidance of metered GitHub Actions usage as a hard operational constraint.
Validation is performed locally or through Remote Desktop Commander unless the policy is explicitly changed.

## Four-layer guard

1. Repository-level GitHub Actions permissions are kept disabled.
2. `.github/workflows/` contains no executable `.yml` / `.yaml` workflow files.
3. Previous workflow definitions are archived under `.github/workflows-disabled/` and are not executable by GitHub Actions.
4. Pull requests are merged through `tools/merge_with_cost_guard.ps1`, which fails closed unless the repository guard is intact.

The archived workflow files are retained only as implementation history and reference material.
They must not be moved back into `.github/workflows/` without an explicit policy change.

## Guard check

Run before Ready for review and again immediately before merge:

```powershell
python tools/check_github_actions_cost_guard.py `
  --repository watarionn/legal-knowledge-base
```

The check fails if any of the following is true:

- repository Actions permissions are enabled;
- an executable workflow YAML exists under `.github/workflows/`;
- a GitHub Actions run is queued, waiting, requested, pending, or in progress.

## Merge procedure

Only after explicit merge approval:

```powershell
& tools/merge_with_cost_guard.ps1 `
  -PullRequest <number> `
  -ExpectedHeadSha <validated-head-sha>
```

The wrapper checks the cost guard, PR state, draft state, mergeability, and expected HEAD before merging.
It runs the cost guard again after the merge.

## Local validation

Use repository tests, PostgreSQL smoke tests, and full runtime validation directly on an authorized local machine.
Do not depend on `[skip actions]` as the primary safety mechanism. Merge commits created by GitHub may not preserve skip directives.

Re-enabling repository Actions or restoring active workflow YAML is a policy change and requires explicit approval before execution.
