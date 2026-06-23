---
name: pf-triage
description: Classify work into Quick, Standard, or Full tiers from deterministic signals. Does not run the doc pipeline or implementation phases.
---

# Triage rubric (`/pf-triage`)

Deterministic tier classifier. Auditable — same inputs → same tier. Not model judgment.

## Inputs

Collect before scoring:

1. **File count** — number of files likely touched (user estimate or `git diff --stat` scope).
2. **Risk keywords** — scan description + file paths for triggers (case-insensitive).
3. **Ambiguity markers** — vague scope language in the request.
4. **Override** — optional `--tier <quick|standard|full>` forces tier (record override).
5. **Misroute re-entry** — `--re-score` when a Quick item's scope grew mid-flight.

## Risk triggers (hard floor → ≥ Standard)

Any match forces **at least Standard** regardless of file count:

- `auth`, `authentication`, `authorization`, `login`, `session`, `oauth`, `jwt`
- `payment`, `payments`, `billing`, `stripe`, `paddle`, `subscription`
- `migration`, `data migration`, `schema migration`, `backfill`
- `public api`, `public endpoint`, `external api`, `webhook`

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
2. If any risk trigger matches → floor = Standard.
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

- **Quick** → implementation workstream (`/pf-execute` when available); no doc artifacts.
- **Standard** → `/pf-prd` (skip brainstorm) or `/pf-doc`.
- **Full** → `/pf-brainstorm` or `/pf-doc`.

## Misroute re-entry

When implementation reveals scope growth on a Quick-classified item:

1. Re-run `/pf-triage --re-score` with updated file list and description.
2. If new tier > Quick, route into Standard/Full pipeline.
3. Record prior Quick classification in the output for audit.

## Test matrix (structural)

| Case | Input | Expected |
|------|-------|----------|
| Trivial | 1 file, no risk keyword | Quick |
| Bounded feature | 4 files, no risk | Standard |
| Risk floor | 1 file + "auth" | Standard (not Quick) |
| Ambiguous | 2 files + "maybe refactor" | Standard or Full |
| Conservative default | empty file count | Standard |
| Override | `--tier full` on 1-file change | Full + override recorded |
| Misroute | `--re-score`, was Quick, now 6 files | Standard or Full |
