---
description: Local-then-provider code review — phase 1 multi-agent (ce-code-review) then phase 2 external provider. Does not run the CI gate or stabilize PR threads.
alwaysApply: false
---

# `/sw-review`

Two-phase local review over the uncommitted delta: **phase 1** = local multi-agent adapter
(`review.local`); **phase 2** = external provider (`review.provider`, CodeRabbit default).

## Scope

- Staged + unstaged changes only (not branch/PR history).
- Phase 1 before phase 2 — earliest substantive code-quality review is local.
- Does **not** compute CI gate verdict or resolve PR review threads — use `/sw-watch-ci` / `/sw-stabilize`.
- `gap-check` remains the sole requirements-completeness authority; local review is requirements-aware
  but emits no completeness verdict.

## Phase 1 — local review (`review.local`)

1. Resolve `review.local` from `workflow.config.json`.
   - `review.local.enabled: false` or `review.local.provider: "none"` → skip to phase 2 with message.
2. Read `providers/code-review/<provider>.md` (default `ce-code-review`).
3. **Soft dependency check:** if `ce-code-review` skill is unavailable → report
   `Local review skipped — ce-code-review skill not available.` and skip to phase 2 (fail-closed;
   **never** treat as clean pass). No `native` fallback (deferred YAGNI).
4. `memory-preflight` read for known false-positives and file learnings.
5. **Invariants (optional):** when `invariantsFile` is set, resolve relative to the review ref (PR head /
   worktree base). Surface to local review agents as non-negotiable constraints. Missing/unreadable blocks this
   review unless `invariantsOptional: true` or `--no-invariants` (logged).
6. Compute `base` = per-worktree `parentBranch` from phase state.
6. Invoke adapter per `providers/code-review/ce-code-review.md`:

   ```
   ce-code-review mode:agent base:<parentBranch> grouping:<review.local.grouping|auto>
   ```

   Capture raw JSON to `/tmp/sw-local-review-raw.json`.
7. Normalize:

   ```bash
   scripts/code-review-normalize.sh --input /tmp/sw-local-review-raw.json --repo-root "$PWD" \
     > /tmp/sw-local-review-normalized.json
   ```

   - `status: skipped|failed|degraded` (no findings) → surface `reason`, skip remainder of phase 1,
     proceed to phase 2 — **never** deserialize as "0 findings → pass."
   - Requirement-stage findings are post-filtered in normalize (gap-check unaffected).
8. **Apply** (sw-owned, untrusted-output boundary):

   For each finding in normalized output, run eligibility check:

   ```bash
   scripts/code-review-apply-check.sh --finding '<json>' --repo-root "$PWD"
   ```

   Auto-apply only when eligible: P2/P3, concrete `suggested_fix`, `requires_verification: false`,
   in-repo file, size-bounded, non-security-sensitive target. **P0/P1 never auto-fixed.** Apply through
   pf edit machinery only — never let `ce-code-review` commit into the worktree.
9. **Bounded re-verify:** if any fix applied, run `/sw-verify` once. Circuit-breaker: three identical
   failures without diff change → escalate per `rules/sw-subagent-dispatch.mdc`.
10. **Severity gate:**

    ```bash
    scripts/code-review-gate.sh \
      --input /tmp/sw-local-review-normalized.json \
      --gate-config /tmp/sw-local-review-gate.json
    ```

    Write gate config from `review.local.gate`. Surface-only default (`haltOn: []`) logs P0–P3 and
    continues. Halting mode (`haltOn: ["P0","P1"]`) records halt signal for `/sw-ship` (validated
    P0/P1 only). Persist gate result to `/tmp/sw-local-review-gate-result.json`.
11. **Persist edges (redaction):**
    - Scrub `ce-code-review` run dir after parsing:

      ```bash
      RUN_DIR="$(jq -r '.artifact_path // empty' /tmp/sw-local-review-raw.json)"
      [[ -n "$RUN_DIR" && -d "$RUN_DIR" ]] && rm -rf "$RUN_DIR"
      ```

    - `memory-preflight` write for durable learnings only (via `scripts/memory-redact.sh` — no raw dumps).
12. Phase-1-applied fixes stay in working tree for phase 2. Any phase-2 finding on a phase-1-touched line
    is annotated `contests applied fix` for the human (no automatic re-litigation).

## Phase 2 — external provider (`review.provider`)

Unchanged from prior single-phase flow:

1. Resolve provider from `workflow.config.json` → `review.provider`; read `providers/review/<provider>.md`.
   If `review.provider` is `none` or `review.enabled` is `false`, report that review is disabled for this
   repo and stop — do **not** invoke the provider CLI.
2. Gather delta: `git diff --cached --stat` and `git diff --stat`.
3. Stage new files (`??`) before `coderabbit review -t uncommitted` — untracked paths are invisible.
4. `memory-preflight` read for bot false-positives and file learnings.
5. Run provider local review (CodeRabbit):

   ```bash
   RUN_DIR=$(bash scripts/sw-tmp.sh resolve)
   if [[ -z "$RUN_DIR" ]]; then
     RUN_DIR=/tmp
   fi
   LOG_FILE="$RUN_DIR/sw-review-$(date +%Y%m%d%H%M%S)-$$.log"
   STATUS_FILE="$RUN_DIR/sw-review.status.json"
   coderabbit review -t uncommitted > "$LOG_FILE" 2>&1
   REVIEW_EC=$?
   REVIEW_STATUS="pass"
   [[ "$REVIEW_EC" -ne 0 ]] && REVIEW_STATUS="fail"
   jq -n --argjson ec "$REVIEW_EC" --arg st "$REVIEW_STATUS" --arg log "$LOG_FILE" \
     '{exitCode: $ec, status: $st, logPath: $log, provider: "coderabbit"}' > "$STATUS_FILE"
   chmod 600 "$STATUS_FILE"
   ```

   The verification-gate consumes `$STATUS_FILE` (stable path). When review is disabled (step 1), do not
   write the status file — the gate treats review evidence as absent.
6. Fix actionable findings; re-run at most once if substantive fixes applied; refresh `$STATUS_FILE` if
   re-run.
7. `memory-preflight` write for durable review learnings only (no raw bot dumps).

## Guardrails

- Load `agentsFile` before review.
- API keys from environment only.
- Do not use `--base` on CodeRabbit (branch review is a separate surface).
- Emit `sw-review.status.json` under the resolved run dir when phase 2 runs — verification-gate depends on it.
- Phase 1 does not replace phase-2 status signal.
- `check-gate.sh` remains sole CI oracle — local severity gate is additive.
