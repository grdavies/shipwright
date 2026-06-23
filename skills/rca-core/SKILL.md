---
name: rca-core
description: Shared hypothesis-driven root cause analysis core for stabilize and debug entry points.
---

# RCA core (shared)

Single analysis skill with two entry points (R35):

| Entry | Status | Inputs |
|-------|--------|--------|
| `stabilize` | **implemented** | Gate failures + normalized review findings (from review seam) |
| `debug` | **deferred** | Deploy logs / Sentry / user-reported behavior — debugging workstream plan |

## Stabilize entry procedure

1. Collect failing check names + logs from gate JSON (`scripts/check-gate.sh`).
2. Collect normalized findings from `review.provider` adapter (inline threads + non-inline bodies).
3. Form ranked hypotheses (most likely first) with evidence for/against each.
4. Propose minimal fix per top hypothesis; verify against frozen spec / PRD amendments union.
5. Stop when gate returns `green` or stabilize loop hard-stop triggers.

## Debug entry (stub)

Deferred to debugging-workstream plan. Do not invoke until `/pf-debug` is designed.

## Output shape

```markdown
## Hypotheses
1. [hypothesis] — evidence for / against
## Recommended fix
[minimal change]
## Verification
[how to confirm]
```
