---
description: Gated orchestrator over the phase loop — advances on green, halts at human merge gate. Never merges.
alwaysApply: false
---

# `/sw-ship`

Orchestrates the atomic phase loop inside the worktree. Delegates to each command's procedure; never merges.

## Chain

```
sw-tmp init → sw-execute → sw-verify → verification-gate → sw-review → sw-simplify → gap-check → sw-commit → sw-pr → sw-watch-ci → sw-stabilize → sw-ready [PAUSE] → sw-tmp clean
```

- **sw-tmp** — at chain start: `bash scripts/sw-tmp.sh clean` then `bash scripts/sw-tmp.sh init` (records
  `runDir` in shipwright-state). At chain end: `bash scripts/sw-tmp.sh clean`. No `trap … EXIT` (markdown-orchestrated
  chain).
- **verification-gate** — `Load skills/verification-gate/SKILL.md`; run `scripts/verify-evidence.sh` on
  structured status files under the resolved run dir. Policy by `inconclusiveClass`:
  - **Halt** on `not-verified` or `missing-required`.
  - **`no-baseline` / `unattributed`** — log loudly and **continue** into `sw-commit` (which owns the logged
    decision prompt). Does not override `check-gate.sh`.
- **sw-simplify** — behavior-preserving deslop after review; re-runs verify + `simplify-gate.sh`. **Halt** on
  `regressed`; **log and continue** on `inconclusive`. Skipped by `--fast` / `--skip-simplify`.
- **`sw-review`** — native phase-1 panel runs **in-chain by default** (resolved via
  `scripts/review-local-resolve.sh`; fires even when `review.provider: "none"`). Only
  `review.local.enabled: false` or `review.local.provider: "none"` opts out (R14/R15). Local severity gate is
  **additive**: surface-only default (`haltOn: []` logs P0–P3 and continues, R26); promoted halting on validated
  P0/P1 stops the chain. Phase-1 writes `$runDir/sw-local-review-run-report.json` (R69); `gap-check` reads the
  advisory `scope_fidelity_advisory` block only — never alters binding verdict (R75). `review.noDefer` honored.
- `gap-check` default-on (`skills/gap-check`); `--fast` skips.
- `sw-stabilize` uses `stabilize-loop` when present.
- Terminal pause at merge gate — "ready to merge — your call" (suppressed under **phase-mode**; see below).

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
  run record via `scripts/shipwright-state.sh` before the implementation loop begins.

## State (per-worktree)

Via `scripts/shipwright-state.sh`: `shipStartedAt`, `lastCommand`, `phaseStatus`, `iteration`, `runDir`,
`phaseShip` (phase-mode step resume).

Resume: `--from` › `phaseShip.currentStep` (durable `ship-steps.json`) › `lastCommand` (next step) › chain start.

### Phase-mode step persistence (R58)

When `--phase-mode` / `SW_PHASE_MODE` is active, persist step-level state under the phase run dir:

```bash
# At chain start (after sw-tmp init records runDir):
bash scripts/ship-phase-steps.sh init --phase "${SW_PHASE_SLUG:-}"

# Before each step (records attempt counter):
bash scripts/ship-phase-steps.sh attempt --step sw-execute

# After each green step:
bash scripts/ship-phase-steps.sh advance --step sw-execute

# Sync into per-worktree shipwright.json for cross-agent resume:
bash scripts/shipwright-state.sh sync-ship-steps

# Resolve resume point (fresh agent):
bash scripts/ship-phase-steps.sh resolve-resume [--from STEP] [--last-command "$lastCommand"]
```

Default path: `$SW_RUN_DIR/ship-steps.json`, else `.cursor/sw-deliver-runs/<phase>/ship-steps.json`.
`ship-phase-status.sh` embeds the latest `shipSteps` snapshot in `status.json` when present.
Survives `sw-tmp clean` (same run-dir contract as `status.json`).

**Stale-green re-verify:** if `lastCommand` is `sw-ready` / `phaseStatus: green`, re-run `check-gate.sh` live
before reporting done. If no longer green → `phaseStatus: blocked`, re-enter at `sw-stabilize`.

## CI segment

After `sw-pr`: bounded wait per `checks.watch` (`maxWaitMinutes`, `pollSeconds`). `yellow` is not terminal —
poll until green, red, or budget exhausted. After `sw-stabilize` push, re-arm CodeRabbit barrier on new head.

Gate (authoritative):

```bash
GATE="${CURSOR_PLUGIN_ROOT:-$PWD}/scripts/check-gate.sh"
if OUT=$(bash "$GATE"); then GATE_EC=0; else GATE_EC=$?; fi
echo "$OUT" | jq .
```

Persist terminal green only on live `GATE_EC == 0`. Then `/sw-ready` and stop.

**Feedback closure (optional):** when `--signal-id <id>` is set and human has confirmed closure, run
`/sw-feedback-close` after live green — requires verify status (and gate JSON when PR exists).

## Stop conditions

- Step failure or stabilize hard stop.
- **verification-gate** returns `not-verified` (fresh attributable failure).
- **verification-gate** returns `inconclusive` with `inconclusiveClass: missing-required`.
- **sw-simplify** / `simplify-gate.sh` returns `regressed` (post-cleanup verify failure).
- **Local review gate** — when `review.local.gate.haltOn` includes validated P0/P1 and
  `/tmp/sw-local-review-gate-result.json` reports `verdict: halt`, stop for human triage (surface-only
  default logs and continues). Never overrides `check-gate.sh`.
- **Native apply rails (phase-mode, R67)** — validated P1 MUST NOT auto-apply; surface as `blocked` with
  cause. Circuit-breaker trip → `blocked` (not interactive escalate). `--skip-local` refused or recorded in
  durable per-phase status.
- User ambiguity (branch/scope/config).
- CI budget exhausted while `yellow`.
- Merge gate reached on live green.

**Communication intensity:** inherit

**Model tier:** inherit — resolve delegated atomics via `bash scripts/resolve-model-tier.sh --command <child-slug>`; do not dispatch on bare `--command sw-ship`.

## Delegated Task binding contract

Before any delegated Task spawn from `/sw-ship`:

1. `bash scripts/wave.sh dispatch preflight --dispatch-id <id> --agent <agent-id> --command sw-ship --skill <active-skill>`
2. `bash scripts/dispatch-check.sh --agent <agent-id> --command sw-ship --skill <active-skill> --parent-model <parent-concrete-id> [--dispatch-id <id>]`
3. Stamp Task with explicit `model: <resolved-concrete-id>`; do not use `inherit`.

## Inline allowlist (closed)

`/sw-ship` may remain inline only for:

- Step sequencing/state sync (`ship-phase-steps`, `shipwright-state`) and gate reads.
- Mechanical command invocation (`sw-execute`, `sw-verify`, `sw-review`, etc.) without bypassing them.
- Emitting phase-mode status and merge-gate summaries.

Implementation/review authoring outside these bookkeeping paths delegates.

## Dispatch context redaction contract

Before dispatching any Task, redact non-config payloads (diff excerpts, CI/review output, feedback snippets,
memory-preflight data) via `bash scripts/memory-redact.sh`, then include only redacted/fenced
`untrusted_payload` content.

## Guardrails

- Never merge or force-push.
- Advance only on green; never skip steps.
- Delegate — do not bypass command guardrails.
- All **merge-gate** truth from `check-gate.sh` — verification-gate is pre-CI local evidence only.
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

At chain end (`sw-ready` or any halt), write durable status via `scripts/ship-phase-status.sh`:

```bash
# Live green at merge gate (R18 — no pause, no merge):
bash scripts/ship-phase-status.sh --verdict merge-ready-green \
  --phase "${SW_PHASE_SLUG:-}" --head "$(git rev-parse HEAD)" \
  ${PR:+--pr "$PR"} [--gate-json /tmp/gate.json]

# Any other halt (R48 — blocked, not interactive):
bash scripts/ship-phase-status.sh --verdict blocked --cause "<short cause>" \
  --phase "${SW_PHASE_SLUG:-}"
```

Default output path: `$SW_RUN_DIR/status.json`, else `.cursor/sw-deliver-runs/<phase>/status.json`.
Survives `sw-tmp clean` (R47/R38). Never commit these paths (`/sw-commit` excludes them).

| Outcome | `verdict` | Agent behavior |
| --- | --- | --- |
| Live `check-gate.sh` green | `merge-ready-green` | Suppress "ready to merge — your call"; exit `0` **without merging** |
| `verification-gate` halt (`not-verified`, `missing-required`) | `blocked` | Write `--cause`; exit non-zero; no prompt |
| Local review gate halt (validated P0/P1) | `blocked` | Write `--cause`; exit non-zero; no prompt |
| Native P1 in phase-mode (validated, not applied) | `blocked` | Write `--cause`; exit non-zero; no prompt |
| Native apply circuit-breaker trip | `blocked` | Write `--cause`; exit non-zero; no prompt |
| Branch/scope/config ambiguity | `blocked` | Write `--cause`; exit non-zero; no prompt |
| CI budget exhausted / stabilize hard stop | `blocked` | Write `--cause`; exit non-zero; no prompt |

Phase-mode **never merges**. The human merge gate is reserved for `<type>/<slug> → main` on the orchestrator
(R18/R23). `/sw-deliver` owns phase → `<type>/<slug>` merges (R19).
