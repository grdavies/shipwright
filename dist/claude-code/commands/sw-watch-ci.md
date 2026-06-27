---
description: Watch the active PR's checks under the all-checks gate and report the next action
alwaysApply: false
trigger: "/sw-watch-ci" or "watch CI for the current PR"
---

# `/sw-watch-ci`

Watch the active PR after `/phase-pr` or any follow-up push, and report a single gate verdict. Uses the
**all-checks** policy by default (every check, not just required) via the `checks-gate` skill.

## Preconditions

- The current branch has an open PR, and the latest state is pushed to `origin`.
- Host token env var is set (`host.tokenEnv`, default `GITHUB_TOKEN`).

If no PR exists, stop and send the workflow back to `/phase-pr`.

When `host.sh pr-view` reports `mergeable: CONFLICTING`, stop and hand off to `/sw-stabilize` (merge-base
sync). Do not busy-poll checks that cannot run until conflicts are resolved.

## Procedure

1. Read `.cursor/workflow.config.json` → `checks` (policy, `treatNeutralAsPass`, `neutralAllowlist`) and
   `memory`.
2. Resolve the active PR:

```bash
PR_JSON=$(bash scripts/host.sh pr-view --number "$PR")
PR_NUMBER=$(jq -r .number <<<"$PR_JSON")
HEAD_SHA=$(jq -r .headRefOid <<<"$PR_JSON")
printf '%s\n' "$PR_JSON"
```

3. **Compute the verdict with the deterministic gate script (do not hand-roll it).** Hand-rolled host
   checks are exactly how a false `green` slipped through (a comment-count proxy
   counted only already-posted inline comments and missed a re-review that had not posted yet). Run:

```bash
GATE="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/local/shipwright}/scripts/check-gate.sh"
bash "$GATE" > /tmp/sw-watch-ci-gate.json
cat /tmp/sw-watch-ci-gate.json
```

   The script paginates `reviewThreads`, classifies every check, and applies the per-head CodeRabbit
   barrier (status context + review→commit association + summary-comment markers). It emits `verdict`,
   `coderabbitLanded`, `coderabbitState` (`landed`/`skipped`/`in-flight`/`absent`),
   `coderabbitReviewedCurrentHead`, `unresolvedActionable`, and the failing/pending lists. If the script is
   unavailable, fall back to the `checks-gate` skill's documented steps by hand — but the thread fetch and
   the per-head CodeRabbit barrier are **mandatory** either way.
4. **Trust the script's `verdict`; do not override a `green` with a hand-rolled check.** The script already
   encodes the barrier: a `green` verdict means `coderabbitLanded == true` — CodeRabbit reviewed the current
   head, **skipped** it as non-reviewable (`coderabbitState == "skipped"`, e.g. "No new commits to review"),
   or is `absent`. Do **not** add your own `coderabbitReviewedCurrentHead == true` gate on top — that would
   wrongly hold a legitimately-skipped head at `yellow` (the review oid lags the head by design when
   CodeRabbit skips). CodeRabbit re-reviews after every push, so the head the script checks is always the
   latest pushed head.
5. On a `red`/`blocked` verdict, run a `memory-preflight` read scoped to the failing job(s) so prior
   CI/review lessons can shape the handoff. Skip memory on `green`/`yellow` (lazy read).
6. Act on the verdict:
   - **`yellow`** (checks pending or CodeRabbit in-flight) — arm a wake and block on CI settling rather
     than busy-polling or handing back a pending PR. Wake on settle, then re-poll review threads + the
     CodeRabbit barrier and recompute. (Standalone `/sw-watch-ci` runs one wait-and-rewatch; under `/ship` the
     orchestrator owns the bounded loop and re-enters here.)

```bash
Use `bash scripts/host.sh checks --number "$PR"` in a poll loop (bounded intervals per host rate-limit policy).
echo 'WATCH_CI_TICK {"phase":"recheck"}'
```

   Run as a background shell with `notify_on_output` on `^WATCH_CI_TICK` so the agent wakes when checks
   finish; bound the total wait by `checks.watch.maxWaitMinutes` and re-poll at most every
   `checks.watch.pollSeconds`. If a CI-watcher subagent is available, delegate this wait-and-report.
   - **`red`/`blocked`** — pull failure logs for the `/sw-stabilize` handoff:

```bash
Optional: fetch failed workflow logs via host REST when CI job links are present in checks output.
: > /tmp/sw-watch-ci-failed.log
for RUN_ID in $RUN_IDS; do
  [ -n "$RUN_ID" ] || continue
  printf '=== failed logs for run %s ===\n' "$RUN_ID" >> /tmp/sw-watch-ci-failed.log
  # append failed job logs when available from the host checks payload
done
```

## Verdict → next step

Per the `checks-gate` skill:

- `green` — all checks pass, none pending, CodeRabbit settled for the current head (`coderabbitLanded == true` — reviewed, **skipped**, or absent), zero unresolved actionable threads → `/sw-phase-ready`
- `red` — any check failed → `/sw-stabilize`
- `yellow` — any check pending **or** CodeRabbit review still in-flight → keep waiting (re-watch; under `/ship` the loop continues automatically within `checks.watch.maxWaitMinutes` — `yellow` is **not** a terminal state)
- `blocked` — unconfigured/neutral-blocking checks, or unresolved actionable threads → `/sw-stabilize`

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --command sw-watch-ci`.

## Guardrails

- Watch the PR tied to the current branch only.
- Evaluate **all** checks under the configured policy — a failing non-required job blocks readiness.
- Use `scripts/check-gate.sh` for the verdict; never substitute a hand-rolled proxy (e.g.
  a comment-count proxy — that shortcut can't see a not-yet-posted re-review and is what
  produced a false `green`. Trust the script's `verdict`: `green` ⟺ `coderabbitLanded == true` (reviewed,
  skipped, or absent). Do not re-gate on `coderabbitReviewedCurrentHead`.
- Treat unresolved actionable review items as a readiness gate alongside checks.
- Do not fix code, resolve threads, rerun workflows, merge, or dismiss failures from this command.
- Store memories only for durable CI/review failure patterns (usually during `/sw-stabilize`), never for
  routine green/pending states.
