---
name: stabilize-loop
description: USE WHEN reviewing code, handling review feedback, or running /sw-review and /sw-stabilize. Opt-in goal-driven loop that keeps running /sw-stabilize and /sw-watch-ci until the all-checks gate is green and no actionable review threads remain. Use when the user asks to stabilize until green, or from /ship. Single-pass /sw-stabilize remains the default; this only adds the loop wrapper with hard stops.---

# stabilize-loop

Drives the current PR to a green gate by repeating the stabilize→verify→push→watch cycle, waking on CI
completion and new review comments. **Opt-in only** — the default for `/sw-stabilize` is a single pass.
This wrapper never changes stabilize's discipline (reply-before-resolve, verify-before-resolve, no
mass-resolve); it just repeats it under hard stops.


**Model tier:** build — resolve via `python3 scripts/resolve-model-tier.py --skill stabilize-loop`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Success predicate

Stop with success when the `checks-gate` verdict (from `scripts/check-gate.py`) is **green**:

- every **required** check passes under the configured all-checks policy (PR test-plan **advisory**
  job failures appear in `advisoryFailingChecks` but do not block — see `prTestPlan` in gate JSON), and
- zero checks pending, and
- **CodeRabbit is settled for the current head** — `coderabbitLanded == true` (`coderabbitState` is
  `landed`, `skipped`, or `absent`). Because every pass pushes a new fix commit, this means a **fresh**
  CodeRabbit review must land for that commit, *or* CodeRabbit explicitly skips it (`skipped` — "no new
  commits to review"); a stale review of the pre-fix head with no skip marker never counts. This is the
  predicate's most important clause: "the threads I just fixed are resolved" is **not** success — the
  re-review of the fix can post new findings (it has, ~1–3 min after the push), and
- zero unresolved **actionable** review items — both inline review threads **and** non-inline findings
  (CodeRabbit "Outside diff range comments" / "Additional comments" harvested from review + walkthrough
  bodies, which have no reply/resolve handle).

When `coderabbit.noDefer` is true, "actionable" includes every valid bot finding — inline or non-inline —
the loop is not done while reproducible findings remain unresolved.

## Hard stops (any one ends the loop)

- `maxIterations` reached (default 5; configurable).
- **No-progress**: the same head SHA with the same failing-check set (or the same unresolved-thread +
  non-inline-finding set) seen on two consecutive evaluations → escalate, do not keep pushing.
- A blocker that needs a human decision (ambiguous fix, scope/architecture call, base-branch conflict
  whose intents disagree) → stop and ask.
- A check failure outside this PR's scope that a scoped fix cannot address → report, do not mutate CI.

## Loop

1. Resolve PR + config (`checks`, `coderabbit`, `verify`, `memory`). Record the starting head SHA.
2. Run one `/sw-stabilize` pass (its full procedure + guardrails, including the **rca-core stabilize
   entry** RCA pass before the blocker ledger): build the blocker ledger, fix the `fix-now` batch,
   verify with the configured `verify` commands, reply+resolve only verified threads, make one focused
   commit, push once.
3. If nothing changed and the gate was already green → success.
4. Arm the wake (see below) and wait for CI to settle and for new comments.
5. Recompute the verdict via `scripts/check-gate.py` (it folds in the per-head CodeRabbit barrier,
   classified checks, and the unresolved-thread count); also re-harvest open non-inline findings from the
   review/walkthrough bodies (a fixed "Outside diff range" item should no longer recur).
   - **green** (`coderabbitLanded == true` — the re-review of this pass's fix landed clean, or CodeRabbit
     skipped the head) → success: report and hand back (to `/ship` → `phase-ready`, or to the user).
   - **`coderabbitState == "in-flight"`** (re-review of the fix not posted yet, no skip marker) → treat as
     **yellow**, wait on the wake (step 4) and recompute; do **not** declare success.
   - **red/blocked** with progress (head SHA advanced or the failing/thread/finding set shrank) → loop to
     step 2.
   - **no progress** (same SHA + same failures/threads/findings twice) → hard stop, escalate.
6. Honor `maxIterations`. On any hard stop, summarize the remaining blockers and the reason.

## Wake mechanism (from the `loop` pattern)

After pushing a pass, block on CI settling rather than busy-polling:

```bash
PR=$(python3 scripts/host.py resolve-pr-for-branch)
python3 scripts/host.py checks --number "$PR"
echo 'STABILIZE_LOOP_TICK {"phase":"recheck"}'
```

Run that as a background shell with `notify_on_output` on `^STABILIZE_LOOP_TICK` so the agent wakes when
checks finish. Also poll for new review threads on wake. Use a unique sentinel; do not arm duplicate
loops; track the PID so the loop can be stopped on request.


## Deliver-initiated remediation

When invoked from `/sw-deliver` `remediate` dispatch (post-merge `verify:failed`), this loop runs on the
phase branch under the regression remediation budget (`deliver.remediation.maxAttempts`). Environmental
post-merge verify failures use a separate `verifyRemediationAttempts` counter and do not consume the
regression budget. Completion updates durable deliver state (`stabilizePassId`, `lastRemediationAt`) so the
conductor no-progress signature advances before the next driver tick.

## Guardrails

- Opt-in. Never convert a plain `/sw-stabilize` into a loop without the user asking (or `/ship` driving).
- Preserve every `/sw-stabilize` guardrail — this wrapper adds iteration, not new resolve powers. Each
  pass includes one rca-core stabilize entry (single analysis step; R29 budget stays here, not nested).
- One focused commit per pass; never batch "do everything" into one inflated commit.
- Never merge, force-push, rerun unrelated workflows, or edit CI definitions to go green.
- Always enforce the no-progress stop — a loop that cannot improve must escalate, not churn.
- Stop and ask on any human-owned decision; record the stop reason.
