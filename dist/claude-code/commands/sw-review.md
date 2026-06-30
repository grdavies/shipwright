---
description: Local-then-provider code review — phase 1 multi-agent (ce-code-review) then phase 2 external provider. Does not run the CI gate or stabilize PR threads.
alwaysApply: false
---

# `/sw-review`

Two-phase local review over the uncommitted delta; phase 2 may run **heterogeneous** external providers (`review.providers` array, scalar back-compat) synthesized by `scripts/review_synthesize.py`. **phase 1** = native local panel (`review.local`,
default-on **`native`**); **phase 2** = external provider (`review.provider`, default **`none`**). Phase 1
runs **independently** of phase-2 opt-out — including when `review.provider: "none"`. CodeRabbit is opt-in via
`review.provider: "coderabbit"`.

## Scope

- Staged + unstaged changes only (not branch/PR history).
- Phase 1 before phase 2 — earliest substantive code-quality review is local.
- Does **not** compute CI gate verdict or resolve PR review threads — use `/sw-watch-ci` / `/sw-stabilize`.
- `gap-check` remains the sole requirements-completeness authority; local review is requirements-aware
  but emits no completeness verdict.

## Flags

- `--fast` / `--skip-local` — skip phase 1 for this run only; announce skip; do not change persisted config
  (R54). In phase-mode, record skip in durable status (R67).

## Phase 1 — local review (`review.local`)

1. **Pre-work search (mandatory)** — before the first substantive mutation, run `memory-preflight` **pre-work
   search** per `skills/memory/SKILL.md` **Pre-work search (mandatory)** (scoped to changed paths; classes
   `rule`, `decision`, `learning`, `code-context`, `design` plus known false-positives via
   `providers/<memory.provider>.md` — no direct provider call). Surface hits and reconcile applicable
   rules/contradicting decisions before review commentary.
2. Resolve `review.local` via `scripts/review-local-resolve.py` (schema defaults: `enabled: true`,
   `provider: "native"`, `apply: "auto"`).
   - `review.local.enabled: false` or `review.local.provider: "none"` → skip to phase 2 with message.
   - `--fast` / `--skip-local` → skip phase 1 for this run (announced).
3. Read `providers/code-review/<provider>.md` (`native` default).
4. **Soft dependency check** (`ce-code-review` only): if `ce-code-review` skill is unavailable → report
   `Local review skipped — ce-code-review skill not available.` and skip to phase 2 (fail-closed; **never**
   treat as clean pass). The `native` adapter has no soft dependency.
5. **Invariants (optional):** when `invariantsFile` is set, resolve relative to the review ref (PR head /
   worktree base). Surface to local review agents as non-negotiable constraints. Missing/unreadable blocks this
   review unless `invariantsOptional: true` or `--no-invariants` (logged).
6. Compute `base` = per-worktree `parentBranch` from phase state.
7. **Native panel — selection + activation record (R10):** when `review.local.provider` resolves to `native`,
   build diff JSON for the uncommitted delta and run:

   ```bash
   scripts/code-review-select.py --diff /tmp/sw-local-review-diff.json \
     > /tmp/sw-local-review-roster.json
   ```

   Announce the activation record: always-on **core** roster (`correctness`, `maintainability`,
   `scope-fidelity`, `testing`, `security`), **gated specialists** from `specialists[]`, and **matched signals**
   per specialist from `signals{}` (explainable panel; `previous-comments` excluded). Copy the record into the
   phase-1 run report. Roster selection is deterministic — never delegate to the model (`native.md` R58).
6. Invoke adapter per `providers/code-review/ce-code-review.md`:

   ```
   ce-code-review mode:agent base:<parentBranch> grouping:<review.local.grouping|auto>
   ```

   Capture raw JSON to `/tmp/sw-local-review-raw.json`.
7. Normalize:

   ```bash
   scripts/code-review-normalize.py --input /tmp/sw-local-review-raw.json --repo-root "$PWD" \
     > /tmp/sw-local-review-normalized.json
   ```

   - `status: skipped|failed|degraded` (no findings) → surface `reason`, skip remainder of phase 1,
     proceed to phase 2 — **never** deserialize as "0 findings → pass."
   - Requirement-stage findings are post-filtered in normalize (gap-check unaffected).
8. **Dedup** overlapping findings per `native.md` (R70) before apply.
9. **P1 validation wave** (R22/R49/R62): for each P1, spawn independent fresh-context validator at deep tier
   (diff + neutral location only — never first reviewer's title / fix / reasoning). Confirmed → eligible for
   apply with `--validated`. Non-confirm / degraded → surface only. **Phase-mode:** all P1 surface as `blocked`
   — never auto-apply unattended P1 (R67).
10. **Apply** (Shipwright-owned, untrusted-output boundary, R19/R68):

    Resolve `review.local.apply` from resolve output (`auto` | `surface` | `off`). When not `auto`, skip apply
    (review + surface only).

    **Dirty tree (R64):** if `git status --porcelain` is non-empty before apply, refuse OR snapshot via
    `git stash push -u -m sw-local-review-pre-apply` and restore after the run.

    For each finding in deterministic order (severity, file, line):

    ```bash
    scripts/code-review-apply-check.py --finding '<json>' --repo-root "$PWD" \
      --apply-policy "$APPLY_POLICY" \
      ${PHASE_MODE:+--phase-mode} \
      ${VALIDATED:+--validated}
    ```

    Auto-apply when eligible: validated **P1** (interactive only), **P2/P3** with concrete `suggested_fix`,
    `requires_verification: false`, rails pass. **P0 never auto-applied.** Security-sensitive /
    behavior-altering / control-marker findings surface only. Apply through pf edit only.

    **Per-fix checkpoint (R64):** apply one fix → bounded `/sw-verify` → on fail revert **only that fix's
    hunks** and re-surface; on pass keep for phase 2. Re-anchor line numbers before next fix.

    **Circuit breaker (R24/R65):** identical normalized verify-failure signature → count toward cap (3 per
    finding, 10 per run). Trip → escalate (interactive) or `blocked` (phase-mode, R67).
11. **Severity gate:**

    ```bash
    scripts/code-review-gate.py \
      --input /tmp/sw-local-review-normalized.json \
      --gate-config /tmp/sw-local-review-gate.json
    ```

    Write gate config from `review.local.gate`. Surface-only default (`haltOn: []`) logs P0–P3 and
    continues. Halting mode (`haltOn: ["P0","P1"]`) records halt signal for `/sw-ship` (validated
    P0/P1 only). Persist gate result to `/tmp/sw-local-review-gate-result.json`.
12. **Run report (R69/R50):** resolve `runDir` via `python3 scripts/sw-tmp.py resolve` (or `shipwright-state`
    `runDir` when set). Write `$runDir/sw-local-review-run-report.json` per the contract in `native.md`:

    - announced roster + per-specialist selection reasons (from activation record)
    - counts: `applied`, `surfaced`, `reverted` (per severity)
    - `human_triage[]` — every surface-only finding with reason (P0, security-sensitive, unvalidated /
      non-confirmed P1, reverted-on-verify, circuit-breaker escalations)
    - `change_digest[]` — finding → file / line → applied hunk summary
    - `one_shot_revert` — documented command to undo this run's panel-applied hunks only
    - `scope_fidelity_advisory` — labeled **advisory**; names `gap-check` as binding completeness authority
      (forwarded to `/sw-ship` gap-check per R75; not persisted to durable memory per R50)
    - `instrumentation` — `phase_2_load` (panel-touched vs untouched counts) + `contested_apply.rate` (R74);
      initialized after phase 1; finalized after phase 2 when external review runs

    Announce report path in run output. Scrub report contents via `memory-redact.py` before any memory write
    (R29/R30):

    ```bash
    python3 scripts/memory-redact.py "$runDir/sw-local-review-run-report.json" \
      > "$runDir/sw-local-review-run-report.scrubbed.json"
    mv "$runDir/sw-local-review-run-report.scrubbed.json" "$runDir/sw-local-review-run-report.json"
    ```
13. **Persist edges (redaction, R29/R30):**
    - Scrub `ce-code-review` run dir after parsing:

      ```bash
      RUN_DIR="$(Python json -r '.artifact_path // empty' /tmp/sw-local-review-raw.json)"
      [[ -n "$RUN_DIR" && -d "$RUN_DIR" ]] && rm -rf "$RUN_DIR"
      ```

    - Remove native panel temp intermediates post-parse:

      ```bash
      for tmp in \
        /tmp/sw-local-review-diff.json \
        /tmp/sw-local-review-roster.json \
        /tmp/sw-local-review-raw.json \
        /tmp/sw-local-review-normalized.json \
        /tmp/sw-local-review-gate.json \
        /tmp/sw-local-review-gate-result.json; do
        rm -f "$tmp"
      done
      ```

    - Finding-derived memory writes only — each distilled learning MUST pass through the redaction chokepoint
      before `memory-preflight` persist (no raw reviewer output, diffs, or transcripts):

      ```bash
      while IFS= read -r finding; do
        REDACTED="$(printf '%s' "$finding" | python3 scripts/memory-redact.py)"
        # memory-preflight write distilled learning from $REDACTED
      done < <(Python json -c '.findings[]' /tmp/sw-local-review-normalized.json 2>/dev/null || echo '[]')
      ```
14. Phase-1-applied fixes stay in working tree for phase 2. Any phase-2 finding on a phase-1-touched line
    is annotated `contests applied fix` additively (never suppressed, R71).

## Phase 2 — external provider (`review.provider`)

Unchanged from prior single-phase flow:

1. Resolve provider from `workflow.config.json` → `review.provider`; read `providers/review/<provider>.md`.
   Canonical opt-out is `review.provider: "none"` (review gating off). If `review.provider` is `none` or
   `review.enabled` is `false` (deprecated), report that external review is off for this repo and stop — do
   **not** invoke the provider CLI. To use CodeRabbit, set `review.provider: "coderabbit"` in config or via
   `/sw-setup`.
2. Gather delta: `git diff --cached --stat` and `git diff --stat`.
3. Stage new files (`??`) before `coderabbit review -t uncommitted` — untracked paths are invisible.
4. `memory-preflight` read for bot false-positives and file learnings.
5. Run provider local review (CodeRabbit):

   ```bash
   RUN_DIR=$(python3 scripts/sw-tmp.py resolve)
   if [[ -z "$RUN_DIR" ]]; then
     RUN_DIR=/tmp
   fi
   LOG_FILE="$RUN_DIR/sw-review-$(date +%Y%m%d%H%M%S)-$$.log"
   STATUS_FILE="$RUN_DIR/sw-review.status.json"
   coderabbit review -t uncommitted > "$LOG_FILE" 2>&1
   REVIEW_EC=$?
   REVIEW_STATUS="pass"
   [[ "$REVIEW_EC" -ne 0 ]] && REVIEW_STATUS="fail"
   Python json -n --argjson ec "$REVIEW_EC" --arg st "$REVIEW_STATUS" --arg log "$LOG_FILE" \
     '{exitCode: $ec, status: $st, logPath: $log, provider: "coderabbit"}' > "$STATUS_FILE"
   chmod 600 "$STATUS_FILE"
   ```

   The verification-gate consumes `$STATUS_FILE` (stable path). When external review is off (step 1), do not
   write the status file — the gate treats review evidence as absent.
6. Fix actionable findings; re-run at most once if substantive fixes applied; refresh `$STATUS_FILE` if
   re-run.
7. **Instrumentation update (R74):** when phase 1 emitted `$runDir/sw-local-review-run-report.json` with
   `change_digest`, merge phase-2 metrics into `instrumentation`:

   - `phase_2_load.panel_touched` — actionable phase-2 findings whose `file`+`line` match a `change_digest`
     entry
   - `phase_2_load.panel_untouched` — actionable phase-2 findings on other lines
   - `contested_apply.contested_count` — findings annotated `contests applied fix`
   - `contested_apply.applied_count` — `change_digest | length`
   - `contested_apply.rate` — `contested_count / max(applied_count, 1)`

   Re-scrub the run report via `memory-redact.py` before any memory write.
8. `memory-preflight` write for durable review learnings only (no raw bot dumps); route through
   `scripts/memory-redact.py`.

**Communication intensity:** full

**Model tier:** build — resolve via `python3 scripts/resolve-model-tier.py --command sw-review`.

## Guardrails

- Load `agentsFile` before review.
- API keys from environment only.
- Do not use `--base` on CodeRabbit (branch review is a separate surface).
- Emit `sw-review.status.json` under the resolved run dir when phase 2 runs — verification-gate depends on it.
- Phase 1 does not replace phase-2 status signal.
- `check-gate.py` remains sole CI oracle — local severity gate is additive.
