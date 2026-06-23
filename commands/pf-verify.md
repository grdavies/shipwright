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
4. Run `workflow.config.json` → `verify.*` commands; tee each to `/tmp/pf-verify.*.log`.
5. After all `verify.*` commands complete, write the aggregate to a stable status file:

   ```bash
   STATUS_FILE=/tmp/pf-verify.status.json
   # Aggregate: exitCode 0 + status "pass" only when every verify.* command succeeded.
   jq -n --argjson ec "$AGG_EXIT" --arg st "$AGG_STATUS" \
     '{exitCode: $ec, status: $st, commands: $COMMANDS_ARRAY}' > "$STATUS_FILE"
   ```

   Shape: `{ "exitCode": 0|N, "status": "pass"|"fail", "commands": [{ "name", "exitCode", "status" }] }`.
   The verification-gate (`scripts/verify-evidence.sh`) consumes this file — not the raw logs.
6. Prefer scoped checks; broaden when shared config changed.
7. Report pass/fail with log paths and `$STATUS_FILE`.
8. On durable failure pattern → `memory-preflight` write (redact first). Stop before `/pf-commit` on fail.

## Guardrails

- Logs go to `/tmp` only — never repo root.
- Does not fix code or commit.
