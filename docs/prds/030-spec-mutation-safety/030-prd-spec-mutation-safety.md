---
brainstorm: docs/brainstorms/2026-06-27-spec-mutation-safety-requirements.md
date: 2026-06-27
topic: spec-mutation-safety
absorbs: [GAP-038]
frozen: true
frozen_at: 2026-06-27
---
# PRD 030 — Spec-mutation safety for in-flight implementation

## Overview

Authoring commands (`/sw-amend`, `/sw-tasks`, `/sw-prd`) can propose or commit changes to a frozen PRD or its
task list while that PRD is actively being implemented in a separate deliver run — a different worktree,
clone, or `main` ideation session. Nothing detects the in-flight state, and nothing routes a new task to the
running implementation, so the specification and the code can silently desync. Two real incidents on
2026-06-27 demonstrated this: a PRD 025 amendment authored on `main` proposed a change to PRD 022 while 022
was under active development, and a brainstorm session wanted to change in-flight PRD 013.

The signal needed to prevent this exists but is unusable across sessions: `.cursor/sw-deliver-state*.json`,
`.cursor/sw-deliver-runs/`, and `.cursor/sw-deliver.lock` are gitignored and per-checkout, and the authoring
commands never consult any implementation-state signal (`/sw-amend`'s only guard is "parent file is never
written"). This PRD introduces a durable, committed in-flight signal carried on each PRD's `INDEX.md` row
(status `in-progress` plus run id and implementing branch), set when a deliver run begins implementing a PRD
and cleared at terminal. It adds a fail-closed authoring-time guard to all three authoring surfaces that
refuses to mutate an in-flight PRD (with an opt-in route flag that records a handoff instead), makes the
signal self-heal against staleness, and proves the behavior with fixtures. It absorbs GAP-038.

## Goals

- Make an active implementation detectable from any session or clone via a committed, structured signal.
- Stop authoring commands from silently mutating a PRD or task list that is being implemented elsewhere.
- Provide an explicit, auditable route for a genuine mid-flight change instead of a silent edit.
- Ensure the signal cannot permanently false-block authoring when a run is abandoned or its branch is gone.

## Non-Goals

- Conductor queue/checkpoint pickup of a queued change while a run is live — the MVP blocks until the run
  terminalizes; automatic mid-run application is a future extension.
- Concurrent-run locking and scoped run identity — shipped by PRD 013 R10; this PRD consumes it, not
  re-implements it.
- The docs-on-a-branch policy (PRD 026 R28–R32) — complementary, not in scope.
- The GAP-BACKLOG status lifecycle (PRD 028) and doc-format parser unification (PRD 029).
- Any change to the `main` human merge gate or to frozen-artifact immutability.

## Requirements

- **R1** Each PRD's `INDEX.md` row carries a committed, structured in-flight signal — status `in-progress`
  plus the deliver run id and the implementing branch — so any session or clone can detect an active
  implementation from git alone.
- **R2** A deliver run sets the in-flight signal to `in-progress` (run id + branch) when it begins
  implementing a PRD, and clears it to `complete` or `not-started` at terminal merge or abandonment, written
  under the living-doc single-writer/serialization (PRD 013 R10/R12, PRD 022 R32).
- **R3** `/sw-amend`, `/sw-tasks`, and `/sw-prd` read the in-flight signal before their first mutation and
  fail closed with an actionable message (naming the run id and branch) when the target PRD is in-flight.
- **R4** Each guarded command exposes an explicit opt-in route flag that records the intended change as a
  handoff artifact rather than mutating the in-flight spec, and reports where the handoff was recorded.
- **R5** The signal is staleness-tolerant: when the recorded implementing branch no longer exists or the
  referenced deliver run is not live, the guard degrades to a warning rather than a hard block, and surfaces
  the staleness for reconciliation.
- **R6** A reconcile path in `/sw-status` / `reconcile-status.py` detects and repairs stale or missing
  in-flight markers by comparing INDEX markers against actual deliver runs and branch existence.
- **R7** The guard is provider- and topology-agnostic: it reads only the committed signal (git), never the
  gitignored local deliver state, so it behaves identically across worktrees and clones.
- **R8** The block path documents the manual handoff procedure — wait for terminal, then re-amend — in both
  the command output and the skill prose, so a blocked operator has a clear next step.
- **R9** A docs-currency check fails closed on bidirectional integrity violations: a PRD recorded
  `in-progress` with no live run, or a live deliver run whose PRD carries no `in-progress` marker.
- **R10** Fixtures prove the full contract: an in-flight PRD blocks each of `/sw-amend`, `/sw-tasks`, and
  `/sw-prd`; the opt-in route records a handoff; a stale marker degrades to a warning; and clearing the
  marker at terminal restores authoring.
- **R11** The guard is additive and runs before the first mutation without regressing the human merge gate,
  frozen-artifact immutability, or the existing memory pre-work obligation.
- **R12** Documentation (`living-status` skill, `.sw/layout.md`, and the three authoring command docs)
  describes the in-flight signal, the guard, the route flag, the staleness behavior, and the manual handoff.

## Technical Requirements

- **TR1** (R1, R2) Extend the `INDEX.md` row schema with an in-flight marker (e.g. status token
  `in-progress` plus a structured suffix `run:<id> branch:<name>`), parsed and written by the living-status
  helper (`scripts/reconcile-status.py` / a shared `living-status` writer), never by ad-hoc string edits.
- **TR2** (R2) Hook the set step into the deliver run entry (`wave_deliver_loop.py` / `wave.sh` spec-seed or
  run-start) and the clear step into the terminal path (terminal merge / run abandonment), reusing the
  living-doc lock so concurrent waves serialize INDEX writes.
- **TR3** (R3, R7) Add a shared guard helper (e.g. `scripts/inflight-guard.sh` / a `living-status` function)
  that resolves a PRD's INDEX marker from git and returns block/warn/clear; `/sw-amend`, `/sw-tasks`, and
  `/sw-prd` call it before mutation and map its verdict to exit codes (`0 clear`, `10 warn`, `20 block`).
- **TR4** (R4) Define a handoff artifact location and shape (e.g. an entry appended to the PRD's amendment
  intake or a `docs/prds/<n>-<slug>/HANDOFF.md`); the route flag (`--route`/`--handoff`) writes it and prints
  the path; never touches the frozen parent.
- **TR5** (R5, R6) Liveness check resolves the recorded branch via `git rev-parse --verify` and the run via
  the deliver run index where available; `reconcile-status.py inflight-reconcile --json` repairs drift.
- **TR6** (R9) Extend `docs-currency-gate.py` with the bidirectional in-flight integrity check; fail closed
  with actionable diagnostics; offline/degrade-open only when liveness cannot be determined (warn).
- **TR7** (R8, R12) Update `core/commands/sw-amend.md`, `core/commands/sw-tasks.md`, `core/commands/sw-prd.md`,
  `core/skills/living-status/SKILL.md`, and `.sw/layout.md`; regenerate `dist/` via the emitter after any
  `core/` change.
- **TR8** (R10) Add fixtures under a new `scripts/test/run-inflight-guard-fixtures.sh` (or extend the
  living-status harness): block-on-inflight (×3 surfaces), route-records-handoff, stale-degrades-to-warn,
  clear-restores-authoring; wire into `verify.test` and refresh the golden parity manifest.

## Security & Compliance

- No new external surface, host verb, or network call; the guard reads committed git state and local branch
  refs only.
- The handoff artifact is plain in-repo markdown subject to the existing redaction and secret-scan
  chokepoints; the route path never writes the frozen parent.
- Frozen-artifact immutability is preserved — the guard runs before any mutation and the parent PRD is never
  written by the guard or the route.
- The `main` human merge gate and push chokepoints are unchanged; the in-flight marker is informational, not
  an authority over merge.

## Testing Strategy

Fixtures (failing-before / passing-after), wired into the in-flight-guard suite and `verify.test`:

| Fixture | Asserts | R-IDs |
| --- | --- | --- |
| `block-amend-on-inflight` | `/sw-amend` against an `in-progress` PRD fails closed with run id + branch in the message | R3, R7 |
| `block-tasks-on-inflight` | `/sw-tasks` against an `in-progress` PRD fails closed | R3, R7 |
| `block-prd-on-inflight` | `/sw-prd` regenerating an `in-progress` PRD number fails closed | R3, R7 |
| `route-records-handoff` | the opt-in route flag records a handoff artifact and prints its path; parent unchanged | R4 |
| `stale-marker-degrades-to-warn` | a marker whose branch is gone / run not live yields warn, not block | R5 |
| `clear-at-terminal-restores` | clearing the marker at terminal restores normal authoring | R2 |
| `inflight-currency-bidirectional` | `docs-currency-gate` fails closed on in-progress-without-run and live-run-without-marker | R9 |
| `set-clear-under-lock` | concurrent INDEX writes serialize; marker set/clear is atomic | R2 |

Regression guard: existing living-status, docs-currency, and authoring-command fixtures must remain green.

## Rollout Plan

- **Phase 1 — Committed signal + lifecycle (R1, R2).** Extend the INDEX row schema and the living-status
  writer; wire set-at-run-start and clear-at-terminal under the living-doc lock. No guard yet — lowest risk.
- **Phase 2 — Authoring guard + route (R3, R4, R7, R8).** Add the shared guard helper and call it from
  `/sw-amend`, `/sw-tasks`, `/sw-prd`; add the opt-in route flag and handoff artifact; document the manual
  handoff.
- **Phase 3 — Staleness reconcile + currency (R5, R6, R9).** Liveness check, `inflight-reconcile`, and the
  bidirectional `docs-currency-gate` integrity check.
- **Phase 4 — Fixtures + docs + dist (R10, R11, R12).** Full fixture suite, `verify.test` wiring, command +
  skill + `.sw/layout.md` docs, and `dist/` + golden-manifest regeneration.

Backward compatible: PRDs without an in-flight marker behave exactly as today; the guard only blocks when a
committed `in-progress` marker resolves to a live run.

## Decision Log

- **D1** Carry the durable in-flight signal as a structured `in-progress` status on the committed
  `INDEX.md` row (run id + branch) — chosen over a separate committed registry file or a per-PRD lock file
  because INDEX is already the living-doc source of truth for PRD status and has currency machinery.
- **D2** The authoring guard fails closed by default with an opt-in route flag — chosen over warn-only (too
  weak to prevent silent desync) and refuse-only (no sanctioned path for a genuine mid-flight change).
- **D3** The MVP handoff blocks until the run terminalizes with a documented manual re-amend procedure —
  chosen over building conductor queue/checkpoint pickup now, which is deferred as a future extension.
- **D4** All three authoring surfaces (`/sw-amend`, `/sw-tasks`, `/sw-prd`) are guarded — `/sw-prd` included
  because a regenerated PRD can still target an in-flight number.
- **D5** Standalone PRD 030 (PRD 013 deliver-concurrency/freeze-safety lineage) rather than an amendment to
  the now-complete PRD 013 — a new capability is cleaner as its own PRD.
- **D6** The signal self-heals against staleness (branch existence + run liveness → warn, not block) —
  chosen because a committed marker left by a crashed/abandoned run would otherwise permanently false-block
  authoring (the INDEX-drift hazard).
- **D7** Set at deliver run start, cleared at terminal, written under the living-doc single-writer — chosen
  to keep the marker accurate without a separate heartbeat process.

## Open Questions

None — signal mechanism (D1), guard behavior (D2), handoff MVP (D3), guarded surfaces (D4), and PRD home
(D5) were all resolved with the operator before drafting.
