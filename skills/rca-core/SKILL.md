---
name: rca-core
description: Shared hypothesis-driven root cause analysis core for stabilize and debug entry points.
---

# RCA core (shared)

Single analysis discipline with two entry points (R35). Both use the same hypothesis ranking, causal-chain
gate, explicit invalidation, and hard stops — different inputs and downstream routing only.

| Entry | Inputs | Downstream |
|-------|--------|------------|
| `stabilize` | Gate failures + normalized review findings | `/pf-stabilize` → push → `/pf-watch-ci` |
| `debug` | Production signals (Sentry / deploy log / user report) | `/pf-debug` routing → `003` or `002` |

## Shared discipline

1. **Rank hypotheses** — most likely first; evidence for and against each.
2. **Causal-chain gate** — do not propose a fix until trigger → symptom chain is complete, or the user
   explicitly authorizes a best-available hypothesis.
3. **Invalidate explicitly** — a rejected hypothesis is marked invalid; do not retry variants of it.
4. **Hard stops (R29)** — stop when any applies:
   - `maxIterations` (default **5**) reached
   - **No progress** — same top hypothesis + same evidence set on two consecutive iterations
   - **Human decision** — scope/architecture ambiguity blocks a minimal fix
5. **Output shape** — see below; debug adds `routingHint` after U4 classifies fix size.

## Stabilize entry procedure

**Single pass only** — runs once per `/pf-stabilize` invocation. Does not iterate; `stabilize-loop`
owns the R29 budget (`maxIterations`, no-progress, human decision). Do not re-run this entry in a loop
inside one stabilize pass.

**Consume harvested artifacts** (collection happens in `/pf-stabilize` preconditions — do not re-fetch):

| Artifact | Path |
| --- | --- |
| Review threads | `/tmp/pf-stabilize-threads.json` |
| Non-inline findings | `/tmp/pf-stabilize-noninline.md` |
| Gate verdict | `/tmp/pf-stabilize-gate.json` (`scripts/check-gate.sh` stdout) |

1. Parse failing check names + logs from `/tmp/pf-stabilize-gate.json`.
2. Parse normalized findings from threads JSON + non-inline markdown.
3. Run the **shared discipline** (hypotheses → causal-chain gate) on **`fix-now` candidates only**.
   Items destined for `resolve-with-evidence`, `already-fixed-with-evidence`, or defer buckets **bypass**
   the causal-chain gate — classify them straight into the ledger without forcing a trigger→symptom chain.
4. Propose minimal fix per top surviving `fix-now` hypothesis; verify against frozen spec / PRD amendments
   union.
5. Hand off to `/pf-stabilize` ledger + fix procedure. Gate green is determined by `check-gate.sh` on the
   next pass — this entry does not declare success alone.

## Debug entry procedure

Inputs: normalized signal per `references/debug-inputs.md` + optional repo context.

1. **Redact** all signal text through `bash scripts/memory-redact.sh` before analysis or memory.
2. `memory-preflight` read: prior `debug` memories for `relatedFiles` / failing area.
3. Enrich Sentry signals per `skills/debug/references/sentry.md` when `type == sentry`.
4. Form ranked hypotheses from signal evidence (stack, breadcrumbs, log excerpt, user report).
5. Run the **shared discipline** — attempt repro-from-context but proceed without local repro if blocked.
6. Emit root cause + proposed fix + verification plan.
7. **Do not implement or merge** — hand off to `/pf-debug` routing (scoped phase vs brainstorm/amendment).

### Debug vs stabilize

| | Stabilize | Debug |
|---|-----------|-------|
| Trigger | In-loop CI/review on a PR | Post-ship production signal |
| Repro | Required via failing checks/tests | Attempted from context; not required |
| Fix execution | In-loop commit/push | Routed to `003`/`002`; never auto-merged |

## Output shape

```markdown
## Hypotheses
1. [hypothesis] — evidence for / against (invalidated hypotheses marked)

## Causal chain
trigger → … → symptom

## Root cause
[one sentence]

## Recommended fix
[minimal change — scope estimate for routing]

## Verification
[how to confirm in prod/staging]

## Routing hint (debug only)
small | substantial — rationale
```
