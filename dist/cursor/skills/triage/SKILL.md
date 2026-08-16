---
name: triage
description: Classify work into Quick, Standard, or Full tiers from deterministic signals. Use when routing new work or re-scoring scope mid-flight. Does not run the doc pipeline or implementation phases.
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: phase_default
        selectionFamily: workflow
        command: sw-triage
    metadata:
      skill: triage
      selectionFamily: workflow
---
# Triage rubric (`/sw-triage`)

Deterministic tier classifier. Auditable — same inputs → same tier. Not model judgment.


**Model tier:** cheap — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --skill triage`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Inputs

Collect before scoring:

1. **File count** — number of files likely touched (user estimate or `git diff --stat` scope).
2. **Risk keywords** — scan description + file paths for triggers (case-insensitive).
3. **Ambiguity markers** — vague scope language in the request.
4. **Override** — optional `--tier <quick|standard|full>` forces tier (record override).
5. **Misroute re-entry** — `--re-score` when a Quick item's scope grew mid-flight.

## Risk triggers (hard floor → ≥ Standard)

Each keyword is **tagged**. **Any tag match** forces at least Standard regardless of file count.
**`security`-tagged** entries flow into doc-review selection via `signal_context.derived_tags` and manifest
`text_token` triggers on `sw-security-reviewer` (see `core/sw-reference/capability-manifest.md` — not
duplicated here).

| Keyword | Category |
| --- | --- |
| `auth` | security |
| `authn` | security |
| `authz` | security |
| `authentication` | security |
| `authorization` | security |
| `login` | security |
| `session` | security |
| `oauth` | security |
| `jwt` | security |
| `payment` | security |
| `payments` | security |
| `billing` | security |
| `PII` | security |
| `credentials` | security |
| `token` | security |
| `encryption` | security |
| `public api` | security |
| `public endpoint` | security |
| `external api` | security |
| `webhook` | security |
| `stripe` | billing-routing |
| `paddle` | billing-routing |
| `subscription` | billing-routing |
| `migration` | data-migration |
| `data migration` | data-migration |
| `schema migration` | data-migration |
| `backfill` | data-migration |

## Ambiguity markers (bias upward)

Any match adds +1 to the score:

- `maybe`, `possibly`, `not sure`, `unclear`, `TBD`, `figure out`
- `explore`, `investigate`, `spike`, `prototype`
- missing acceptance criteria on a multi-file change

## File-count score

| Files | Base tier |
|-------|-----------|
| 0–1 | Quick |
| 2–5 | Standard |
| 6+ | Full |

## Resolution algorithm

```
1. If override flag set → use override tier; record "override: <tier>".
2. If any risk trigger matches (any category) → floor = Standard.
3. Compute base tier from file count.
4. If ambiguity markers present → bump one tier (Quick→Standard, Standard→Full).
5. If mixed/insufficient signals (no file count, empty description) → Standard (conservative).
6. final = max(base tier, floor) using order Quick < Standard < Full.
7. On --re-score with prior tier Quick and new score > Quick → promote; report misroute recovery.
```

## Output contract

Report:

```text
Tier: <Quick|Standard|Full>
Signals:
  - file_count: <n> → <base tier>
  - risk_triggers: [<matches>] → floor Standard (if any)
  - ambiguity: [<matches>] → bumped (if any)
  - override: <tier> (if set)
  - misroute_reentry: promoted from Quick (if applicable)
Next: <route>
```

Routes:

- **Quick** → implementation workstream (`/sw-execute` when available); no doc artifacts.
- **Standard** → `/sw-prd` (skip brainstorm) or `/sw-doc`.
- **Full** → `/sw-brainstorm` or `/sw-doc`.

## Misroute re-entry

When implementation reveals scope growth on a Quick-classified item:

1. Re-run `/sw-triage --re-score` with updated file list and description.
2. If new tier > Quick, route into Standard/Full pipeline.
3. Record prior Quick classification in the output for audit.

## Test matrix (structural)

| Case | Input | Expected |
|------|-------|----------|
| Trivial | 1 file, no risk keyword | Quick |
| Bounded feature | 4 files, no risk | Standard |
| Risk floor | 1 file + "auth" | Standard (not Quick) |
| Billing floor only | 1 file + "stripe" | Standard (not Quick); does not fire security persona |
| Migration floor only | 1 file + "migration" | Standard (not Quick); does not fire security persona |
| Ambiguous | 2 files + "maybe refactor" | Standard or Full |
| Conservative default | empty file count | Standard |
| Override | `--tier full` on 1-file change | Full + override recorded |
| Misroute | `--re-score`, was Quick, now 6 files | Standard or Full |

## Quick tier and graph-native `/sw-ship` (PRD 271 R7/R15)

Quick-classified work has **no frozen task list** — `/sw-deliver` does not apply. Entry remains
**`/sw-ship`**: the same operator command compiles Quick work to a fixed WorkflowGraph via
`scripts/graph/quick_ship_compile.py` (`canonicalPhaseChains.sw-ship` in
`kernel-classification.json`). Topology is configuration-declared only — no adaptive capability selection.

Graph-native Quick does **not** add `/sw-graph-*` slash commands; live node progress and explain stay on
`/sw-status`. On misroute (`--re-score` above Quick), route to Standard or Full — do not stretch Quick onto
multi-phase deliver.

