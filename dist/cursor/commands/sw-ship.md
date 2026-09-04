---
description: Gated orchestrator over the phase loop — advances on green, halts at human merge gate. Never merges.
alwaysApply: false
---

# `/sw-ship`

Orchestrates the atomic phase loop inside the worktree. Delegates to each command's procedure; never merges.

Load `skills/conductor/SKILL.md` and enforce `rules/sw-conductor.mdc` — **single source** for in-turn
continuation, legitimate halts, parallel dispatch, and self-wake/bounded-wait behavior (R18). Do not
re-implement loop or halt policy in this file.

## Conductor adoption (SHIP-A1..A4)

| ID | Requirement | Contract clause |
| --- | --- | --- |
| SHIP-A1 | Orchestrator-dispatched runs use `--phase-mode` plus worktree-scoped / explicit dispatch context; write durable `status.json`; suppress interactive merge pause | Legitimate-halt set; **Phase-mode contract** below |
| SHIP-A2 | On `sw-stabilize`, re-enter the stabilize loop in-turn until live green or remediation budget exhausted | In-turn self-continuation; legitimate-halt set |
| SHIP-A3 | CI `yellow` uses self-wake sentinel (or bounded in-turn poll fallback) — never end turn while checks pending | Self-wake / bounded wait; external-wait exhaustion |
| SHIP-A4 | Parallelize independent native review sub-agents when `sw-subagent-dispatch` heuristics allow; respect `worktree.parallelCeiling` | Parallel dispatch |

Human gates unchanged: interactive merge pause (non-phase-mode), validated P0/P1 local review halt, branch/scope
ambiguity, optional `--signal-id` feedback close.


## Execute tier (PRD 053)

When `execute.enabled` is true (default) and the active phase has ≥2 executable sub-tasks, phase entry:

1. Validates `execute-step-plan.json` via `python3 scripts/wave.py plan validate --tier execute`.
2. Fans out one bound `/sw-execute` Task per ref (`execute_fan_out` conductor mode).
3. Integrates green refs via `python3 scripts/wave.py execute integrate` (phase worktree, not merge queue).
4. Gates `sw-verify` until all refs are terminal (`execute_ship.py gate-check`).

`supervised` autonomy halts once per phase for DAG confirm; `autonomous` proceeds without plan halt.
Single-sub-task phases skip execute tier and use monolithic `/sw-execute`. Escape hatch:
`execute.enabled: false`.

## Chain

```
sw-tmp init → sw-execute → sw-verify → verification-gate → sw-review → sw-simplify → gap-check → sw-commit → sw-pr → sw-watch-ci → sw-stabilize → sw-ready → sw-tmp clean [PAUSE]
```

Canonical chain is single-sourced from `core/sw-reference/kernel-classification.json` (`canonicalPhaseChains.sw-ship`); `scripts/ship_phase_steps.py` derives `SHIP_CHAIN` from the same artifact.


- **pre-pr smoke (R4)** — after `sw-commit`, before `sw-pr`, run scoped pytest:
  `SW_TEST_SCOPE=phase python3 scripts/ship_pre_pr_smoke.py` (wraps `test_scope` + `run_pytest` via
  `scripts/test/_runner.py`). Any non-zero exit (failure, collection, import error) **halts** the chain;
  write `blocked` status with cause `pre-pr-smoke:*`. Reemit/reuse paths must run the same smoke (R4/R16).
- **build-chain verify (R25)** — before `sw-commit` when the phase diff touches paths in
  `core/sw-reference/build-chain-paths.json`, run `python3 scripts/ship-build-chain-check.py` (hard block on drift).
  Sync with full `python3 scripts/build-chain-sync.py` when check fails (not `copy-to-core` alone).
  `--force` is never an operator escape.
- **dist freshness (PRD 274)** — when packaged `scripts/` helpers drift from committed `dist/` zipapps, run
  side-effect-free `python3 scripts/dist_freshness.py detect` locally; stderr surfaces
  `python3 -m sw generate --all`. On the ship path before `sw-commit`, prefer
  `python3 scripts/dist_freshness_ship.py regen` (auto-regen + stage invocation outputs only) per
  `skills/ship/SKILL.md` (D3); fail closed on overlapping preexisting `dist/` edits or residual drift.
- **sw-tmp** — at chain start: `python3 scripts/sw_bootstrap.py sw-tmp.py -- clean` then `python3 scripts/sw_bootstrap.py sw-tmp.py -- init` (records
  `runDir` in shipwright-state). At chain end: `python3 scripts/sw_bootstrap.py sw-tmp.py -- clean`. No `trap … EXIT` (markdown-orchestrated
  chain).
- **claims-audit** (PRD 064 R3) — after `behavioral-anomaly-check`, before `verification-gate`:
  `python3 scripts/claims_audit.py run --tasks <frozen-tasks> --phase-id <id> --agent-result $RUN_DIR/claims-audit-agent.json --out $RUN_DIR/claims-audit.status.json`.
  Dispatch `sw-claims-auditor` (cheap, clean-context) per `rules/sw-subagent-dispatch.mdc`; any claim `fail` halts via verification-gate.
- **behavioral-anomaly-check** (PRD 041 R28) — after `sw-verify`, before `verification-gate`:
  `python3 scripts/behavioral_anomaly_check.py --verify-status "$RUN_DIR/sw-verify.status.json"` `--ship-steps "$SW_RUN_DIR/ship-steps.json" --tasks <frozen-tasks> --out "$RUN_DIR/behavioral-anomaly.status.json"`. Advisory anomalies log + feed failure signatures; evidence-integrity mismatch blocks via verification-gate.
- **verification-gate** — `Load skills/verification-gate/SKILL.md`; run `scripts/verify-evidence.py` on
  structured status files under the resolved run dir. Policy by `inconclusiveClass`:
  - **Halt** on `not-verified` or `missing-required`.
  - **`no-baseline` / `unattributed`** — log loudly and **continue** into `sw-commit` (which owns the logged
    decision prompt). Does not override `check-gate.py`.
  - Logged overrides at `sw-commit` auto-file a durable follow-up gap (`capture_verify_override`);
    ship must not treat override as closure.
- **sw-simplify** — behavior-preserving deslop after review; re-runs verify + `simplify-gate.py`. **Halt** on
  `regressed`; **log and continue** on `inconclusive`. Skipped by `--fast` / `--skip-simplify`.
- **`sw-review`** — native phase-1 panel runs **in-chain by default** (resolved via
  `scripts/review-local-resolve.py`; fires even when `review.provider: "none"`). Only
  `review.local.enabled: false` or `review.local.provider: "none"` opts out (R14/R15). Local severity gate is
  **additive**: surface-only default (`haltOn: []` logs P0–P3 and continues, R26); promoted halting on validated
  P0/P1 stops the chain. Phase-1 writes `$runDir/sw-local-review-run-report.json` (R69); `gap-check` reads the
  advisory `scope_fidelity_advisory` block only — never alters binding verdict (R75). `review.noDefer` honored.
- `gap-check` default-on (`skills/gap-check`); `--fast` skips.
- `sw-stabilize` uses `stabilize-loop` when present.
- Terminal pause at merge gate — "ready to merge — your call" (suppressed under **phase-mode**; see below).
- **Issue annotation + safe close (PRD 045 R67/R70)** — under issue-store, after `sw-ready` on live green and
  before durable `merge-ready-green` status, invoke the deliver issue-batch annotate path
  (`wave.py issue-batch annotate`) so linked artifact issues receive PR links + phase status. Close-on-merge
  runs only after default-branch merge verification + deliver allowlist (`projectKey` + `sw:deliver-link`);
  separate-repo stores use explicit `issue-close` API (never unlinked `Closes`/`Fixes` keywords). Unverifiable
  close fails closed — write `blocked` status with cause, not interactive pause.

## Flags

- `--fast` — skip gap-check and sw-simplify; also skips native phase-1 panel when passed to embedded
  `sw-review` (R54).
- `--skip-local` — skip native phase-1 panel for this run only (announced; config unchanged, R54).
- `--skip-simplify` — skip sw-simplify only (gap-check still runs unless `--fast`).
- `--signal-id <id>` — after merge-ready pause, offer `/sw-feedback-close` for this backlog signal.
- `--from <step>` — resume mid-chain.
- `--dry-run` — print plan; no mutations.
- `--phase-mode` — non-interactive contract for `/sw-deliver` phase dispatch (R48/R18). Activation
  is CLI plus worktree-scoped state or explicit per-spawn dispatch env — not ambient process
  inheritance. See **Phase-mode contract** below.
- `--after-tasks <stop|confirm|auto>` — when `/sw-ship` is entered from the doc chain with a frozen task list,
  overrides `doc.afterTasks` for the **frozen-task-list → implementation-loop** boundary (same semantics as
  `/sw-doc --after-tasks`). When an agent supplies `--after-tasks=auto`, record the choice in the per-worktree
  run record via `scripts/shipwright-state.py` before the implementation loop begins.

## State (per-worktree)

Via `scripts/shipwright-state.py`: `shipStartedAt`, `lastCommand`, `phaseStatus`, `iteration`, `runDir`,
`phaseShip` (phase-mode step resume).

Resume: `--from` › `phaseShip.currentStep` (durable `ship-steps.json`) › `lastCommand` (next step) › chain start.

### Phase-mode step persistence (R58)

When `--phase-mode` is active (CLI and/or worktree-scoped / explicit dispatch context), persist
step-level state under the phase run dir:

```bash
# At chain start (after sw-tmp init records runDir):
python3 scripts/ship-phase-steps.py init --phase "${SW_PHASE_SLUG:-}"

# Before each step (records attempt counter):
python3 scripts/ship-phase-steps.py attempt --step sw-execute

# After each green step:
python3 scripts/ship-phase-steps.py advance --step sw-execute

# Sync into per-worktree shipwright.json for cross-agent resume:
python3 scripts/shipwright-state.py sync-ship-steps

# Resolve resume point (fresh agent):
python3 scripts/ship-phase-steps.py resolve-resume [--from STEP] [--last-command "$lastCommand"]
```

Default path: `$SW_RUN_DIR/ship-steps.json`, else `.cursor/sw-deliver-runs/<phase>/ship-steps.json`.
`ship-phase-status.py` embeds the latest `shipSteps` snapshot in `status.json` when present.
Survives `sw-tmp clean` (same run-dir contract as `status.json`).

**Plan authority (PRD 022):** when `phase-step-plan.json` exists in the phase run dir, `ship-phase-steps.py`
reads its step list as the **sole authority** for `advance`/`resolve-resume` and re-checks kernel ordering at
each step. Canonical `SHIP_CHAIN` (from `kernel-classification.json`) is the fallback only when no validated
plan is present. With default `orchestration.planPolicy: canonical`, behavior matches the hardcoded chain;
`proposed` step-plan adaptivity is live when `/sw-deliver` runs with `planPolicy: proposed` (default
`canonical` unchanged).

**Phase-entry proposed step plan (PRD 023):** under `planPolicy: proposed`, the phase executor proposes a
step list → `python3 scripts/wave.py plan validate --tier phase --phase-type ship` → persists
`phase-step-plan.json` in the phase run dir before the chain starts. `ship-phase-steps.py` reads that plan as
sole authority and re-checks kernel ordering at each `advance`; rejections fall back to canonical `SHIP_CHAIN`.

**Stale-green re-verify:** if `lastCommand` is `sw-ready` / `phaseStatus: green`, re-run `check-gate.py` live
before reporting done. If no longer green → `phaseStatus: blocked`, re-enter at `sw-stabilize`.

## CI segment

After `sw-pr`: bounded wait per `checks.watch` (`maxWaitMinutes`, `pollSeconds`). `yellow` is not terminal —
poll until green, red, or budget exhausted (SHIP-A3). Under conductor adoption, arm self-wake per
`skills/conductor/SKILL.md` **Self-wake sentinel** (or bounded in-turn poll fallback per **Self-wake environment
fallback**) — do not end the turn with only "waiting for CI" prose. After `sw-stabilize` push, re-arm CodeRabbit
barrier on new head.

Gate (authoritative):

```bash
GATE="${CURSOR_PLUGIN_ROOT:-$PWD}/scripts/check-gate.py"
if OUT=$(bash "$GATE"); then GATE_EC=0; else GATE_EC=$?; fi
echo "$OUT" | Python json .
```

Persist terminal green only on live `GATE_EC == 0`. Then `/sw-ready` and stop.

**Feedback closure (optional):** when `--signal-id <id>` is set and human has confirmed closure, run
`/sw-feedback-close` after live green — requires verify status (and gate JSON when PR exists).

## Stop conditions

- Step failure or stabilize hard stop.
- **verification-gate** returns `not-verified` (fresh attributable failure).
- **verification-gate** returns `inconclusive` with `inconclusiveClass: missing-required`.
- **sw-simplify** / `simplify-gate.py` returns `regressed` (post-cleanup verify failure).
- **Local review gate** — when `review.local.gate.haltOn` includes validated P0/P1 and
  `/tmp/sw-local-review-gate-result.json` reports `verdict: halt`, stop for human triage (surface-only
  default logs and continues). Never overrides `check-gate.py`.
- **Native apply rails (phase-mode, R67)** — validated P1 MUST NOT auto-apply; surface as `blocked` with
  cause. Circuit-breaker trip → `blocked` (not interactive escalate). `--skip-local` refused or recorded in
  durable per-phase status.
- User ambiguity (branch/scope/config).
- CI budget exhausted while `yellow`.
- Merge gate reached on live green.

**Communication intensity:** inherit

**Model tier:** inherit — resolve delegated atomics via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command <child-slug>`; do not dispatch on bare `--command sw-ship`.

## Delegated atomics

Substantive chain steps delegate with bound model + intensity per child slug:

| Step | Delegate via | Skill / agent binding |
| --- | --- | --- |
| `sw-execute` | Task | `--command sw-execute` |
| `sw-review` (native panel) | Task per reviewer | `--command sw-review --agent <panel-agent-id>` |
| `sw-simplify` | Task when heuristics fire | `--command sw-simplify` |
| `sw-stabilize` | Task or in-turn chain | `--command sw-stabilize --skill stabilize` |

Resolve model: `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command <child-slug>` (or `--agent` for panel agents).
Resolve intensity: `python3 scripts/resolve-intensity.py --command <child-slug>` (or `--agent|--skill`).

## Delegated Task binding contract

Before any delegated Task spawn from `/sw-ship`:

1. `python3 scripts/wave.py dispatch preflight --dispatch-id <id> --agent <agent-id> --command sw-ship --skill <active-skill>`
2. Assemble the constructed Task prompt via `scripts/dispatch_prompt.py build` (R14/R25) — directive,
   optional context-block compression/path-ref, and redacted task body; write to a run-scoped path under
   `$SW_RUN_DIR/` or `.cursor/sw-deliver-runs/<phase>/`.
3. `python3 scripts/dispatch-check.py --agent <agent-id> --command sw-ship --skill <active-skill> --parent-model <parent-concrete-id> [--dispatch-id <id>] --prompt <constructed-prompt-path>`
4. Stamp Task with explicit `model: <resolved-concrete-id>` and `tool_input.prompt` equal to the validated
   prompt file; do not use `inherit`.

Example (phase-dispatch child Task):

```bash
PROMPT_PATH="${SW_RUN_DIR:-.cursor/sw-deliver-runs/${SW_PHASE_SLUG:-phase}}/dispatch-${DISPATCH_ID}-prompt.md"
INTENSITY_JSON=$(python3 scripts/resolve-intensity.py --agent "$AGENT" --command sw-ship --skill "$SKILL")
INTENSITY=$(echo "$INTENSITY_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['intensity'])")
INTENSITY_SOURCE=$(echo "$INTENSITY_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['source'])")
printf '%s' "$TASK_BODY" > "${PROMPT_PATH}.body"
python3 scripts/dispatch_prompt.py build \
  --intensity "$INTENSITY" \
  --intensity-source "$INTENSITY_SOURCE" \
  --body-file "${PROMPT_PATH}.body" \
  --context-json "${CONTEXT_BLOCKS_JSON:-[]}" \
  --out "$PROMPT_PATH"
python3 scripts/dispatch-check.py --agent "$AGENT" --command sw-ship --skill "$SKILL" \
  --parent-model "$PARENT_MODEL" --dispatch-id "$DISPATCH_ID" --prompt "$PROMPT_PATH"
```

## Inline allowlist (closed)

`/sw-ship` may remain inline only for:

- Step sequencing/state sync (`ship-phase-steps`, `shipwright-state`) and gate reads.
- Mechanical command invocation (`sw-execute`, `sw-verify`, `sw-review`, etc.) without bypassing them.
- Emitting phase-mode status and merge-gate summaries.

Implementation/review authoring outside these bookkeeping paths delegates.

## Dispatch context redaction contract

Before dispatching any Task, redact non-config payloads (diff excerpts, CI/review output, feedback snippets,
memory-preflight data) via `python3 scripts/sw_bootstrap.py memory-redact.py`, then include only redacted/fenced
`untrusted_payload` content.


## PRD 274 decision acknowledgements (sync + build hygiene)

- **D1** — Cluster deliver-closeout sync denylist, operator-local purge, and scripts↔dist freshness/regen
  into one hygiene wave (PRD 274) rather than scattered gap-only fixes; ship/docs reference the unified surface.
- **D2** — Prefer mechanical re-pin fixes (`core_content_sync` denylist/purge, `dist_freshness_ship.py`
  auto-regen) over docs-only workarounds that tell operators to delete untracked mirror files after each sync.

## Decision log (required)

Before PR create/update, capture a schema-valid `## Decision log` JSON block on the PR body (see `core/sw-reference/decision-log.schema.json`). Validate with `python3 scripts/decision_log.py ship-require --body-file <pr-body.md>`; missing/invalid records halt the ship chain (fail-closed; content routes through `scripts/memory-redact.py`).

## Guardrails

- Never merge or force-push.
- Advance only on green; never skip steps.
- Delegate — do not bypass command guardrails.
- All **merge-gate** truth from `check-gate.py` — verification-gate is pre-CI local evidence only.
- `inconclusive` with `no-baseline` / `unattributed` logs and continues; `missing-required` halts the ship chain.

## Ship-loop driver (PRD 065)

Interactive `/sw-ship` and phase-mode `/sw-deliver` dispatch share `scripts/ship_loop.py` — one driver, one
evidence contract. **Quick-tier** work compiles through `scripts/graph/quick_ship_compile.py` to a fixed
WorkflowGraph declared in `core/sw-reference/kernel-classification.json` (`canonicalPhaseChains.sw-ship`).
The topology is configuration-declared only — no adaptive PRD 272 capability selection. Operator entry
remains `/sw-ship`; the graph halts at merge-ready and **never merges**.

**Quick graph-native (PRD 271 R7/R15):** Quick-tier `/sw-ship` compiles to a fixed WorkflowGraph via
`quick_ship_compile.py` — same operator entry, no `/sw-graph-*` commands. The deliver **conductor** fans out
phases on `/sw-deliver`; it is **not** the `GraphScheduler` owning loop for node execution.


| Mode | Entry | Evidence root | Merge pause |
| --- | --- | --- | --- |
| Interactive | `/sw-ship` (no `--phase-mode`) | `.cursor/sw-ship-runs/<phase>/` | Retained — "ready to merge — your call" |
| Phase-mode | `/sw-deliver` `dispatch-ship` / `dispatch-batch` | `.cursor/sw-deliver-runs/<phase>/gate-evidence/` | Suppressed — `merge-ready-green` only |

**Quick graph compile (R7/R27):** before the chain starts, the driver MAY materialize the fixed graph via
`python3 -c "from graph.quick_ship_compile import compile_quick_ship_graph, QuickShipCompileOptions; ..."`
or through `ship_loop.py` helpers (`compile_quick_ship_for_phase`). Lifecycle parity:
`sw-execute` → `sw-verify` → `verification-gate` → `sw-review` → `sw-simplify` → `gap-check` → `sw-commit`
→ `sw-pr` → `sw-watch-ci` → `sw-stabilize` → `sw-ready` → `sw-tmp-clean`. Review nodes use verifier
independence floor (distinct judgment vote; no self-review). Verification-gate and ready-gate semantics
are unconditional whether or not a PR exists yet.

- **Driver delegation** — `wave.py` interactive ship and deliver `dispatch-ship` both invoke
  `ship_loop.py <worktree> drive --phase <slug>`; mechanical steps drain in-process, agent steps surface
  `awaitAgent` to the conductor.
- **Evidence enforcement** — `merge-ready-green` is refused unless every mandatory gate has a
  binding-valid record per its mode (`merge_ready_enforcement.py` / `gate_evidence.py`). Missing, stale,
  head-mismatched, or forged evidence fails closed with a named cause.
- **Interactive parity** — no compatibility window: identical `merge-ready-green` refusal semantics in both
  modes; interactive runs do **not** emit a deliver terminal acceptance record.
- **Bypass flags** — `--fast` / `--skip-local` / `--skip-simplify` skip only optional/advisory gates; each
  skip writes an explicit record; no combination suppresses a mandatory gate.

## Phase-ship hygiene floors (PRD 278 R1–R2)

Phase-mode `/sw-ship` may auto-repair three hygiene halts via `scripts/phase_ship_hygiene.py` before
terminal status — **automate-or-fail-closed** (D2); no silent operator file surgery.

| Step / gate | Trigger | Safe auto-repair | Hard refuse |
| --- | --- | --- | --- |
| `gap-check` | Missing `gap-check.status.json` | Authoritative gap evaluation for exact phase HEAD → binding pass write | Forged pass without `evaluationProvenance` or HEAD skew (D4) |
| `deliver-loop` / terminal prepare | `tasks-currency-divergence` | Re-sync checkbox ledger from `source_task_list` | Mutating frozen task-list bytes or inventing completion |
| `wave_terminal` / terminal prepare | `prTestPlan-manifest-missing` | Mirror orchestrator gate-cache manifest when safe | No authoritative manifest source |

When auto-repair refuses, the chain halts with typed `cause` + `resumeCommand` (typically
`/sw-ship --phase-mode --from <step>`). Regression:
`scripts/unit_tests/planning/test_phase_ship_hygiene_autorepair.py`. Deliver-level detail:
`core/commands/sw-deliver.md` **Closeout hardening**.

## Phase-mode contract (`--phase-mode`)

When `/sw-deliver` dispatches `/sw-ship` for a phase, it MUST invoke with `--phase-mode` and carry
phase-mode context via **worktree-scoped state** (`.cursor/sw-worktree-state.json` → `phaseMode`)
and/or an **explicit dispatch environment** set on that spawned process only. Interactive human runs
omit the flag (default). Ambient process environment alone must not activate phase-mode.

### Activation

- CLI: `--phase-mode`
- Worktree-scoped state: deliver writes `phaseMode` under the phase worktree before ship drive
- Explicit dispatch env: per-spawn bindings (`SW_PHASE_MODE`, `SW_PHASE_SLUG`, `SW_RUN_DIR`,
  `SW_PHASE_ID`, `SW_TASK_LIST`) set by the dispatcher for that child only — never inherited from a
  sibling worktree or ambient orchestrator shell
- Orchestrator SHOULD also set `SW_PHASE_SLUG=<phase-slug>` and optionally `SW_RUN_DIR` pointing at
  `.cursor/sw-deliver-runs/<phase>/` (see `.shipwright/layout.md`) on the dispatched process

### Durable planning-backend disable + CI companion step

Persistent operating modes no longer rely on process-global kill-switch env. Operators disable the
issue-store backend with the durable record CLI:

```bash
python3 scripts/planning_backend_control.py disable --set-by <who> --reason <why>
python3 scripts/planning_backend_control.py enable
```

The disable record lives under `git rev-parse --git-common-dir` (`shipwright/planning-backend-disable.json`)
and is **local-only** — a fresh CI clone cannot see a machine-local record. Companion CI propagation:
declare the intended backend (or closeout `override="issue-store"`) in workflow/CI configuration for
that run so CI does not silently diverge from local disable authority. Legacy `SW_PLANNING_KILL_SWITCH`
is a warn-only shim and must not change resolution.

### Terminal outcomes (machine-readable)

At chain end (`sw-ready` or any halt), write durable status via `scripts/ship-phase-status.py`:

```bash
# Live green at merge gate (R18 — no pause, no merge):
python3 scripts/ship-phase-status.py --verdict merge-ready-green \
  --phase "${SW_PHASE_SLUG:-}" --head "$(git rev-parse HEAD)" \
  ${PR:+--pr "$PR"} [--gate-json /tmp/gate.json]

# Any other halt (R48 — blocked, not interactive):
python3 scripts/ship-phase-status.py --verdict blocked --cause "<short cause>" \
  --phase "${SW_PHASE_SLUG:-}"
```

Default output path: `$SW_RUN_DIR/status.json`, else `.cursor/sw-deliver-runs/<phase>/status.json`.
Survives `sw-tmp clean` (R47/R38). Never commit these paths (`/sw-commit` excludes them).

| Outcome | `verdict` | Agent behavior |
| --- | --- | --- |
| Live `check-gate.py` green | `merge-ready-green` | Suppress "ready to merge — your call"; exit `0` **without merging** |
| `verification-gate` halt (`not-verified`, `missing-required`) | `blocked` | Write `--cause`; exit non-zero; no prompt |
| Local review gate halt (validated P0/P1) | `blocked` | Write `--cause`; exit non-zero; no prompt |
| Native P1 in phase-mode (validated, not applied) | `blocked` | Write `--cause`; exit non-zero; no prompt |
| Native apply circuit-breaker trip | `blocked` | Write `--cause`; exit non-zero; no prompt |
| Branch/scope/config ambiguity | `blocked` | Write `--cause`; exit non-zero; no prompt |
| CI budget exhausted / stabilize hard stop | `blocked` | Write `--cause`; exit non-zero; no prompt |

Phase-mode **never merges**. The human merge gate is reserved for `<type>/<slug> → main` on the orchestrator
(R18/R23). `/sw-deliver` owns phase → `<type>/<slug>` merges (R19).

### Single-flight ship lease + PR idempotency (PRD 036 R1–R5)

Before `sw-pr` touches a phase head under deliver dispatch:

1. **Per-head lease** — `python3 scripts/wave.py ship-lease acquire --integration <integration> --phase-branch <head>`
   (keyed `(integrationBranch, phaseBranch)` under `.cursor/sw-deliver-locks/`; heartbeat TTL
   `SW_SHIP_LEASE_STALE_SECONDS`, default 300s).
2. **PR idempotency** — phase-mode `host_pr_create` routes through `create_or_reuse_phase_pr`: `pr-list` filtered
   by integration base under the lease, reuse open PR or create once; `openPrNumber` persisted to deliver state.
3. **Base pin** — integration branch from durable deliver state only; `SW_INTEGRATION_BRANCH` is harness-only.
4. **Release** — `python3 scripts/wave.py ship-lease release` after the list→create window closes.

`dispatch-ship` runs **in-turn** in the conductor; only `dispatch-batch` backgrounds sub-agents on distinct heads.

### Terminal status provenance + recovery (PRD 036 R13–R17)

`scripts/ship-phase-status.py` emits a deterministic SHA256 `provenanceMarker` over canonical fields
(`verdict`, `phase`, `head`, gate-subset, `shipSteps` checksum; excluding `writtenAt`). The marker is
integrity/shape only — merge enqueue still re-verifies live host evidence (`check-gate.py` on the current
head). Hand-editing `status.json` is never valid.

**Blessed recovery** when a phase is `stuck-stale` or status is non-terminal despite green live evidence:

```bash
/sw-ship --phase-mode --from <terminal-step>
```

Re-run from the last durable `ship-steps.json` step (typically `sw-ready` chain tail: `sw-stabilize`,
`sw-watch-ci`, or `sw-ready`). Recovery acquires the per-head ship lease, re-derives the verdict from live
evidence, and atomically re-emits `status.json`. Set `SW_RECOVERY_ACTOR=<actor>` so `run.log` records the
invocation. The deliver driver may also auto re-emit via `canonical-reemit` within
`deliver.statusReemit.maxAttempts` (default 2).

