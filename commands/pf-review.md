---
description: Review the local staged/unstaged delta via the configured review provider (CodeRabbit default). Does not run the CI gate or stabilize PR threads.
alwaysApply: false
---

# `/pf-review`

Local pre-commit review over the uncommitted delta. Routes through `review.provider` (default: CodeRabbit).

## Scope

- Staged + unstaged changes only (not branch/PR history).
- Does **not** compute CI gate verdict or resolve PR review threads — use `/pf-watch-ci` / `/pf-stabilize`.

## Procedure

1. Resolve provider from `workflow.config.json` → `review.provider`; read `providers/review/<provider>.md`.
   If `review.provider` is `none` or `review.enabled` is `false`, report that review is disabled for this
   repo and stop — do **not** invoke the provider CLI. (Use this for repos not onboarded to the provider;
   the CLI would hang or fail.)
2. Gather delta: `git diff --cached --stat` and `git diff --stat`.
3. Stage new files (`??`) before `coderabbit review -t uncommitted` — untracked paths are invisible.
4. `memory-preflight` read for bot false-positives and file learnings.
5. Run provider local review (CodeRabbit):

   ```bash
   LOG_FILE="/tmp/pf-review-$(date +%Y%m%d%H%M%S)-$$.log"
   coderabbit review -t uncommitted > "$LOG_FILE" 2>&1
   ```

6. Fix actionable findings; re-run at most once if substantive fixes applied.
7. `memory-preflight` write for durable review learnings only (no raw bot dumps).

## Guardrails

- Load `agentsFile` before review.
- API keys from environment only.
- Do not use `--base` (branch review is a separate surface).
