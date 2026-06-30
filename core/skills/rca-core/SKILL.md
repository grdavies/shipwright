---
name: rca-core
description: Shared hypothesis-driven root cause analysis core for stabilize, debug, and dev-time entry points.
---

# RCA core (shared)

Single analysis discipline with three entry points (R35). All use the same hypothesis ranking, causal-chain
gate, explicit invalidation, reproduction-first where applicable, and hard stops — different inputs and
downstream routing only.

| Entry | Inputs | Downstream |
|-------|--------|------------|
| `stabilize` | Gate failures + normalized review findings | `/sw-stabilize` → push → `/sw-watch-ci` |
| `debug` | Production signals (Sentry / deploy log / user report) | `/sw-debug` routing → `003` or `002` |
| `dev-time` | Local test/build/verify failures | `/sw-debug` → worktree + `/sw-start` or escalate |


**Model tier:** build — resolve via `python3 scripts/resolve-model-tier.py --skill rca-core`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Shared discipline

1. **Rank hypotheses** — most likely first; evidence for and against each.
2. **Reproduction-first gate** — before a scoped fix, establish a reliable repro **or** log inability to
   reproduce with evidence (what was tried, what blocked). Dev-time entry treats this as **strict**;
   debug entry attempts repro-from-context but may proceed when blocked; stabilize uses failing checks as
   repro.
3. **Causal-chain gate** — do not propose a fix until trigger → symptom chain is complete, or the user
   explicitly authorizes a best-available hypothesis.
4. **Failing-regression-test gate (dev-time + scoped fixes)** — when the failure is test-shaped, require a
   test that **fails before** the fix and **passes after**; do not rewrite the test to match broken behavior.
5. **Invalidate explicitly** — a rejected hypothesis is marked invalid; do not retry variants of it.
6. **Hard stops (R29)** — stop when any applies:
   - `maxIterations` (default **5**) reached
   - **No progress** — same top hypothesis + same evidence set on two consecutive iterations
   - **Rule-of-three** — three identical failed fix attempts (same hypothesis + same evidence signature) →
     escalate to architecture review; maps to the R29 circuit breaker
   - **Human decision** — scope/architecture ambiguity blocks a minimal fix
7. **Output shape** — see below; debug adds `routingHint` after fix-size classification.

## Stabilize entry procedure

**Single pass only** — runs once per `/sw-stabilize` invocation. Does not iterate; `stabilize-loop`
owns the R29 budget (`maxIterations`, no-progress, human decision). Do not re-run this entry in a loop
inside one stabilize pass.

**Consume harvested artifacts** (collection happens in `/sw-stabilize` preconditions — do not re-fetch):

| Artifact | Path |
| --- | --- |
| Review threads | `/tmp/sw-stabilize-threads.json` |
| Non-inline findings | `/tmp/sw-stabilize-noninline.md` |
| Gate verdict | `/tmp/sw-stabilize-gate.json` (`scripts/check-gate.py` stdout) |

1. Parse failing check names + logs from `/tmp/sw-stabilize-gate.json`.
2. Parse normalized findings from threads JSON + non-inline markdown.
3. Run the **shared discipline** (hypotheses → causal-chain gate) on **`fix-now` candidates only**.
   Items destined for `resolve-with-evidence`, `already-fixed-with-evidence`, or defer buckets **bypass**
   the causal-chain gate — classify them straight into the ledger without forcing a trigger→symptom chain.
4. Propose minimal fix per top surviving `fix-now` hypothesis; verify against frozen spec / PRD amendments
   union.
5. Hand off to `/sw-stabilize` ledger + fix procedure. Gate green is determined by `check-gate.py` on the
   next pass — this entry does not declare success alone.

## Debug entry procedure

Inputs: normalized signal per `references/debug-inputs.md` + optional repo context.

1. **Redact** all signal text through `python3 scripts/memory-redact.py` before analysis or memory.
2. `memory-preflight` read: prior `debug` memories for `relatedFiles` / failing area.
3. Enrich Sentry signals per `skills/debug/references/sentry.md` when `type == sentry`.
4. Form ranked hypotheses from signal evidence (stack, breadcrumbs, log excerpt, user report).
5. Run the **shared discipline** — attempt repro-from-context but proceed without local repro if blocked.
6. Emit root cause + proposed fix + verification plan.
7. **Do not implement or merge** — hand off to `/sw-debug` routing (scoped phase vs brainstorm/amendment).

## Dev-time entry procedure

Inputs: failing test output, build error, or `/tmp/sw-verify.status.json` + relevant log excerpt from local
dev (not production signals).

1. **Redact** failure text through `python3 scripts/memory-redact.py`.
2. `memory-preflight` read for prior `debug` / `learning` memories on the failing area.
3. **Reproduction-first (strict)** — reproduce via the narrowest command (single test, build target, or
   verify key). If blocked, log what was tried and stop at human-decision hard stop — do not guess-fix.
4. Form ranked hypotheses from stack trace / assertion / build output.
5. Run **shared discipline** including **failing-regression-test gate** before fix proposal.
6. Optional **git bisect** for regressions when history is suspected:

   ```bash
   # Wrapper: exit 0=good, 1=bad, 125=skip (git bisect convention)
   git bisect run bash -c '<repro command>; ec=$?; [[ $ec -eq 0 ]] && exit 0 || exit 1'
   ```

7. Emit root cause + proposed fix + verification plan (test command that must flip red→green).
8. Hand off to `/sw-debug` dev-time routing → `/sw-worktree` + `/sw-start` when fix is small; escalate on
   rule-of-three or substantial scope.

### Entry comparison

| | Stabilize | Debug | Dev-time |
|---|-----------|-------|----------|
| Trigger | In-loop CI/review on a PR | Post-ship production signal | Local test/build/verify failure |
| Repro | Via failing checks/tests | Attempted; optional if blocked | **Required** or logged inability |
| Regression test | Via verify re-run | N/A at RCA stage | **Required** before fix |
| Fix execution | In-loop commit/push | Routed to `003`/`002` | Routed to worktree + phase loop |

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
