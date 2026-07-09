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
4. Run `workflow.config.json` → `verify.test` (default **phase** scope via `SW_TEST_SCOPE=phase` and
   `scripts/test/_runner.py verify --scope phase`). Use `verify.fullTest` when a full collection is required
   (pre-merge widen, global infra paths per TR2). Tee each command to `/tmp/sw-verify.*.log`.
5. **E2E/smoke adapter** (when `verifyE2e.enabled`):

   ```bash
   E2E_JSON=$(python3 scripts/verify-e2e.py)
   E2E_EC=$?
   # Merge into commands array as { "name": "e2e", "exitCode", "status", "provider", "logPath" }
   ```

   Selector reads `verifyE2e.provider` → `providers/verify/<id>.py` (`providers/verify/CAPABILITIES.md`).
   Skipped when `enabled: false` or `provider: "none"` — non-blocking.
6. After all commands complete, resolve the run dir and write the aggregate status file:

   ```bash
   RUN_DIR=$(python3 scripts/sw-tmp.py resolve)
   if [[ -z "$RUN_DIR" ]]; then
     RUN_DIR=/tmp
   fi
   STATUS_FILE="$RUN_DIR/sw-verify.status.json"
   # Aggregate: exitCode 0 + status "pass" only when every verify.* command succeeded.
   Python json -n --argjson ec "$AGG_EXIT" --arg st "$AGG_STATUS" \
     '{exitCode: $ec, status: $st, commands: $COMMANDS_ARRAY}' > "$STATUS_FILE"
   chmod 600 "$STATUS_FILE"
   ```

   Shape: `{ "exitCode": 0|N, "status": "pass"|"fail", "commands": [{ "name", "exitCode", "status", ... }] }`.
   Include the `e2e` entry when the adapter ran. The verification-gate (`scripts/verify-evidence.py`) consumes this file — not the raw logs.
   Optional baseline capture (off by default): `python3 scripts/verify-baseline.py capture --from "$STATUS_FILE" --to <caller-owned-baseline>`.
7. Prefer scoped checks; broaden when shared config changed.
8. Report pass/fail with log paths and `$STATUS_FILE`.
9. On durable failure pattern → `memory-preflight` write (redact first). Stop before `/sw-commit` on fail.

### Baseline isolation (PRD 060 R15)

Capture baselines at caller-owned paths scoped to the phase/run
(e.g. `.cursor/sw-deliver-runs/<phase>/baseline.verify.json`) — never a shared
repo-root `.shipwright/baseline.*` across concurrent phases. Harness fixtures
must use isolated temp paths (`harness_isolation_lint.py` enforces).

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-verify`.

## Guardrails

- Logs go to `/tmp` only — never repo root.
- Does not fix code or commit.
