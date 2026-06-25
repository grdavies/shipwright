---
description: Run scoped local verification for the current phase; tee logs to /tmp. Does not fix code or commit.
alwaysApply: false
---

# `/sw-verify`

Run the smallest reliable verification for the current phase.

## Procedure

1. Union changed paths: staged, unstaged, untracked (`git diff --name-only`, `git ls-files --others --exclude-standard`).
2. `memory-preflight` read for verification footguns on changed paths.
3. Load `agentsFile` + relevant doctrine.
4. Run `workflow.config.json` → `verify.*` commands; tee each to `/tmp/sw-verify.*.log`.
5. **E2E/smoke adapter** (when `verifyE2e.enabled`):

   ```bash
   E2E_JSON=$(bash scripts/verify-e2e.sh)
   E2E_EC=$?
   # Merge into commands array as { "name": "e2e", "exitCode", "status", "provider", "logPath" }
   ```

   Selector reads `verifyE2e.provider` → `providers/verify/<id>.sh` (`providers/verify/CAPABILITIES.md`).
   Skipped when `enabled: false` or `provider: "none"` — non-blocking.
6. After all commands complete, resolve the run dir and write the aggregate status file:

   ```bash
   RUN_DIR=$(bash scripts/sw-tmp.sh resolve)
   if [[ -z "$RUN_DIR" ]]; then
     RUN_DIR=/tmp
   fi
   STATUS_FILE="$RUN_DIR/sw-verify.status.json"
   # Aggregate: exitCode 0 + status "pass" only when every verify.* command succeeded.
   jq -n --argjson ec "$AGG_EXIT" --arg st "$AGG_STATUS" \
     '{exitCode: $ec, status: $st, commands: $COMMANDS_ARRAY}' > "$STATUS_FILE"
   chmod 600 "$STATUS_FILE"
   ```

   Shape: `{ "exitCode": 0|N, "status": "pass"|"fail", "commands": [{ "name", "exitCode", "status", ... }] }`.
   Include the `e2e` entry when the adapter ran. The verification-gate (`scripts/verify-evidence.sh`) consumes this file — not the raw logs.
   Optional baseline capture (off by default): `bash scripts/verify-baseline.sh capture --from "$STATUS_FILE" --to <caller-owned-baseline>`.
7. Prefer scoped checks; broaden when shared config changed.
8. Report pass/fail with log paths and `$STATUS_FILE`.
9. On durable failure pattern → `memory-preflight` write (redact first). Stop before `/sw-commit` on fail.

**Communication intensity:** ultra

## Guardrails

- Logs go to `/tmp` only — never repo root.
- Does not fix code or commit.
