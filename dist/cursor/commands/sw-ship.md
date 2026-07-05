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
| SHIP-A1 | Orchestrator-dispatched runs use `--phase-mode` / `SW_PHASE_MODE`; write durable `status.json`; suppress interactive merge pause | Legitimate-halt set; **Phase-mode contract** below |
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


- **build-chain verify (R25)** — before `sw-commit` when the phase diff touches paths in
  `core/sw-reference/build-chain-paths.json`, run `python3 scripts/ship-build-chain-check.py` (hard block on drift).
  Sync with `python3 scripts/build-chain-sync.py` when check fails.
- **sw-tmp** — at chain start: `python3 scripts/sw-tmp.py clean` then `python3 scripts/sw-tmp.py init` (records
  `runDir` in shipwright-state). At chain end: `python3 scripts/sw-tmp.py clean`. No `trap … EXIT` (markdown-orchestrated
  chain).
- **behavioral-anomaly-check** (PRD 041 R28) — after `sw-verify`, before `verification-gate`:
  `python3 scripts/behavioral_anomaly_check.py --verify-status "$RUN_DIR/sw-verify.status.json"` `--ship-steps "$SW_RUN_DIR/ship-steps.json" --tasks <frozen-tasks> --out "$RUN_DIR/behavioral-anomaly.status.json"`. Advisory anomalies log + feed failure signatures; evidence-integrity mismatch blocks via verification-gate.
- **verification-gate** — `Load skills/verification-gate/SKILL.md`; run `scripts/verify-evidence.py` on
  structured status files under the resolved run dir. Policy by `inconclusiveClass`:
  - **Halt** on `not-verified` or `missing-required`.
  - **`no-baseline` / `unattributed`** — log loudly and **continue** into `sw-commit` (which owns the logged
    decision prompt). Does not override `check-gate.py`.
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
- `--phase-mode` — non-interactive contract for `/sw-deliver` phase dispatch (R48/R18). Also active when
  `SW_PHASE_MODE` is truthy (`1`, `true`, `yes`). See **Phase-mode contract** below.
- `--after-tasks <stop|confirm|auto>` — when `/sw-ship` is entered from the doc chain with a frozen task list,
  overrides `doc.afterTasks` for the **frozen-task-list → implementation-loop** boundary (same semantics as
  `/sw-doc --after-tasks`). When an agent supplies `--after-tasks=auto`, record the choice in the per-worktree
  run record via `scripts/shipwright-state.py` before the implementation loop begins.

## State (per-worktree)

Via `scripts/shipwright-state.py`: `shipStartedAt`, `lastCommand`, `phaseStatus`, `iteration`, `runDir`,
`phaseShip` (phase-mode step resume).

Resume: `--from` › `phaseShip.currentStep` (durable `ship-steps.json`) › `lastCommand` (next step) › chain start.

### Phase-mode step persistence (R58)

When `--phase-mode` / `SW_PHASE_MODE` is active, persist step-level state under the phase run dir:

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

**Model tier:** inherit — resolve delegated atomics via `python3 scripts/resolve-model-tier.py --command <child-slug>`; do not dispatch on bare `--command sw-ship`.

## Delegated atomics

Substantive chain steps delegate with bound model + intensity per child slug:

| Step | Delegate via | Skill / agent binding |
| --- | --- | --- |
| `sw-execute` | Task | `--command sw-execute` |
| `sw-review` (native panel) | Task per reviewer | `--command sw-review --agent <panel-agent-id>` |
| `sw-simplify` | Task when heuristics fire | `--command sw-simplify` |
| `sw-stabilize` | Task or in-turn chain | `--command sw-stabilize --skill stabilize` |

Resolve model: `python3 scripts/resolve-model-tier.py --command <child-slug>` (or `--agent` for panel agents).
Resolve intensity: `python3 scripts/resolve-intensity.py --command <child-slug>` (or `--agent|--skill`).

## Delegated Task binding contract

Before any delegated Task spawn from `/sw-ship`:

1. `python3 scripts/wave.py dispatch preflight --dispatch-id <id> --agent <agent-id> --command sw-ship --skill <active-skill>`
2. `python3 scripts/dispatch-check.py --agent <agent-id> --command sw-ship --skill <active-skill> --parent-model <parent-concrete-id> [--dispatch-id <id>]`
3. Stamp Task with explicit `model: <resolved-concrete-id>`; do not use `inherit`.

## Inline allowlist (closed)

`/sw-ship` may remain inline only for:

- Step sequencing/state sync (`ship-phase-steps`, `shipwright-state`) and gate reads.
- Mechanical command invocation (`sw-execute`, `sw-verify`, `sw-review`, etc.) without bypassing them.
- Emitting phase-mode status and merge-gate summaries.

Implementation/review authoring outside these bookkeeping paths delegates.

## Dispatch context redaction contract

Before dispatching any Task, redact non-config payloads (diff excerpts, CI/review output, feedback snippets,
memory-preflight data) via `python3 scripts/memory-redact.py`, then include only redacted/fenced
`untrusted_payload` content.


## Decision log (required)

Before PR create/update, capture a schema-valid `## Decision log` JSON block on the PR body (see `core/sw-reference/decision-log.schema.json`). Validate with `python3 scripts/decision_log.py ship-require --body-file <pr-body.md>`; missing/invalid records halt the ship chain (fail-closed; content routes through `scripts/memory-redact.py`).

## Guardrails

- Never merge or force-push.
- Advance only on green; never skip steps.
- Delegate — do not bypass command guardrails.
- All **merge-gate** truth from `check-gate.py` — verification-gate is pre-CI local evidence only.
- `inconclusive` with `no-baseline` / `unattributed` logs and continues; `missing-required` halts the ship chain.

## Phase-mode contract (`--phase-mode` / `SW_PHASE_MODE`)

When `/sw-deliver` dispatches `/sw-ship` for a phase, it MUST invoke with `--phase-mode` or set `SW_PHASE_MODE=1`.
Interactive human runs omit the flag (default).

### Activation

- CLI: `--phase-mode`
- Env: `SW_PHASE_MODE` truthy (`1`, `true`, `yes`, case-insensitive)
- Orchestrator SHOULD also set `SW_PHASE_SLUG=<phase-slug>` and optionally `SW_RUN_DIR` pointing at
  `.cursor/sw-deliver-runs/<phase>/` (see `.sw/layout.md`).

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

