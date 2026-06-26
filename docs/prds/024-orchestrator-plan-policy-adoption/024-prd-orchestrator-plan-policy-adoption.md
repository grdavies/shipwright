---
brainstorm: docs/brainstorms/2026-06-26-guidelined-autonomous-orchestration-requirements.md
date: 2026-06-26
topic: orchestrator-plan-policy-adoption
frozen: true
frozen_at: 2026-06-26
---
# PRD 024 — Orchestrator plan-policy adoption (fan-out)

## Overview

This is **PRD-4 of the four-PRD guidelined-autonomous-orchestration program** (021 → 022 → 023 → 024). After
the `/sw-deliver` pilot (PRD-023) proves the mechanism is safe and valuable, this PRD fans the proved pattern
out to the remaining orchestrators — `/sw-debug`, `/sw-doc`, `/sw-feedback` — so all four entry points route
plans through the same capability selector (PRD-021) and plan-validation gate (PRD-022), with consistent
behavior and preserved legitimate halts.

Each adoption *references* the shared conductor contract and the shared gate/selector — it does not re-author
loop logic or re-specify the kernel. The convergence order follows the PRD 009 adoption audit:
`/sw-ship` → `/sw-debug` → `/sw-doc` → `/sw-feedback` (`/sw-ship` and `/sw-deliver` are covered by the pilot
and existing conductor work; this PRD lands `/sw-debug`, `/sw-doc`, `/sw-feedback`).

Source brainstorm R-IDs carried forward verbatim. This PRD owns R18–R20 and re-asserts the cross-cutting
R21/R22/R23 per adopted orchestrator.

## Goals

1. `/sw-debug`, `/sw-doc`, and `/sw-feedback` adopt the shared conductor contract plus the plan-policy surface
   and capability manifest, referencing (not duplicating) the shared contract.
2. Every adopted orchestrator routes its plan through the same `wave.sh plan validate` gate and the same
   capability selector, so behavior is consistent across implement/debug/feedback/document.
3. The legitimate-halt set is preserved per orchestrator; only routine turn-yields are removed.

## Non-Goals

- The manifest/selector (PRD-021), kernel/gate/guidelines/flag (PRD-022), and the deliver pilot + benefit
  metric + intra-phase parallelism (PRD-023) — all consumed, not rebuilt.
- Turning `proposed` on by default — the default remains `canonical`, gated by the PRD-023 benefit metric.
- Rewriting doc-review panel human gates (`gated_auto` / `manual`) or auto-merging to `main`.
- Duplicating conductor-contract prose into each command file.

## Requirements

### Owned — adoption + consistency + preserved halts

- **R18** `/sw-debug`, `/sw-doc`, and `/sw-feedback` adopt the shared conductor contract plus the plan-policy
  surface and capability manifest, in the sequenced order from the 009 adoption audit, each *referencing* the
  shared contract rather than re-authoring loop logic.
- **R19** The legitimate-halt set is preserved per entry point: doc-review `manual`/`gated_auto` trade-offs,
  the `main`-merge gate, feedback trigger confirmation, and exhausted budgets remain human-gated; routine
  yields are removed.
- **R20** Each adopted entry point routes its plan through the same plan-validation gate (R6) and capability
  selector (R10), so behavior is consistent across implement/debug/feedback/document.

### Cross-cutting (re-asserted per adopted orchestrator)

- **R21** The chosen plan, the resolved capability set, and any plan rejections (with reason) for each
  phase/run are surfaced in the run log and the consolidated halt/terminal report for each adopted
  orchestrator.
- **R22** Each adopted orchestrator's plan-driven runs stay bounded by the existing autonomy budgets and the
  no-progress circuit breaker.
- **R23** No-auto-merge-to-`main`, push/secret-scan chokepoint, single-flight merge under concurrency, and
  memory redaction guarantees are unchanged for every adopted orchestrator.

## Technical Requirements

- **TR1 — `/sw-debug` adoption.** Route `/sw-debug` plan shape through the gate + selector; after one human
  route confirmation, continue in-turn (per 009 audit DBG-A1); preserve the RCA human-decision halt and Sentry
  degrade-and-continue behavior (R18–R20).
- **TR2 — `/sw-doc` adoption.** Route `/sw-doc` plan shape through the gate + selector; preserve doc-review
  `manual`/`gated_auto` halts and the `doc.afterTasks` checkpoint (R18, R19).
- **TR3 — `/sw-feedback` adoption.** Route `/sw-feedback` plan shape through the gate + selector; preserve the
  single human handoff confirmation per signal and fail-closed hook/monitor triggers (R18, R19).
- **TR4 — Shared-contract references.** Each adopted command/skill references `skills/conductor`, the gate,
  and the selector rather than duplicating them (R18).
- **TR5 — Per-orchestrator surfacing + budgets + invariants.** Plan/capability/rejection surfacing (R21),
  budget binding (R22), and safety invariants (R23) wired and fixture-asserted for each adopted orchestrator.
- **TR6 — Emitter propagation + freshness.** Regenerate both dist trees; freshness gate green.

## Security & Compliance

- **Preserved legitimate halts (R19).** Adoption removes only routine turn-yields; safety/quality human gates
  (doc-review trade-offs, feedback trigger confirmation, main-merge) remain.
- **Consistent kernel enforcement (R20, R23).** Every adopted orchestrator uses the same fail-closed gate and
  the same deterministic kernel; no orchestrator gets a weaker path.
- **Fail-closed triggers.** `/sw-feedback` hook/monitor triggers remain human-gated; the gate never
  auto-dispatches untrusted triggers.

## Testing Strategy

- **Per-orchestrator adoption (R18, R20):** fixtures show `/sw-debug`, `/sw-doc`, `/sw-feedback` routing plans
  through the shared gate + selector with consistent results.
- **Preserved halts (R19):** fixtures assert each orchestrator's legitimate halts still fire and routine
  yields are gone.
- **Surfacing/budgets/invariants (R21–R23):** per-orchestrator fixtures for run-log surfacing, budget trips,
  and safety invariants under `proposed`.
- **Emitter freshness:** stale artifact fails the gate. All wired into `verify.test` suites.

## Rollout Plan

1. Adopt in 009-audit order: `/sw-debug` → `/sw-doc` → `/sw-feedback`, each behind `orchestration.planPolicy`
   (default `canonical`).
2. Each adoption lands green with its fixtures before the next begins.
3. Default stays `canonical` across all orchestrators; any default flip remains gated by the PRD-023 benefit
   metric and is out of scope here.

## Decision Log

- **Fan-out after pilot** (brainstorm convergence + 009 DL-10 order): adopt only after `/sw-deliver` proves
  the mechanism, to avoid spreading an unproven pattern across four orchestrators.
- **Reference, don't duplicate** (R18): each orchestrator cites the shared contract/gate/selector; no loop
  prose duplication.
- **Legitimate halts preserved** (R19): autonomy removes routine yields only, never safety/quality gates.

## Open Questions

None — resolved in the brainstorm (2026-06-26). Adoption order is inherited from the 009 audit; the default
flip to `proposed` is out of scope and gated by PRD-023's metric.
