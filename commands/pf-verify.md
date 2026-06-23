---
description: Run scoped local verification for the current phase; tee logs to /tmp. Does not fix code or commit.
alwaysApply: false
---

# `/pf-verify`

Run the smallest reliable verification for the current phase.

## Procedure

1. Union changed paths: staged, unstaged, untracked (`git diff --name-only`, `git ls-files --others --exclude-standard`).
2. `memory-preflight` read for verification footguns on changed paths.
3. Load `agentsFile` + relevant doctrine.
4. Run `workflow.config.json` → `verify.*` commands; tee to `/tmp/pf-verify.*.log`.
5. Prefer scoped checks; broaden when shared config changed.
6. Report pass/fail with log paths.
7. On durable failure pattern → `memory-preflight` write (redact first). Stop before `/pf-commit` on fail.

## Guardrails

- Logs go to `/tmp` only — never repo root.
- Does not fix code or commit.
