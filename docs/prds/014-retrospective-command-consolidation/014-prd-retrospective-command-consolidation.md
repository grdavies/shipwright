---
date: 2026-06-26
topic: retrospective-command-consolidation
brainstorm: docs/brainstorms/2026-06-26-retrospective-command-consolidation-requirements.md
frozen: true
frozen_at: 2026-06-26
---

# PRD 014 — Retrospective command consolidation

## Overview

Shipwright's post-delivery compounding surface is split across two overlapping commands whose names do not match
the operator mental model and whose human-approval gates block fully autonomous delivery. The orchestrator
`/sw-compound-ship` chains `retro → compound → memory-sync → status`; the atomic `/sw-compound` performs one
bounded write step. Operators cannot tell which to run or when, the name "compound" has no tie to post-delivery
reflection, and the approval / "did you merge?" gates stall the autonomous terminal path that PRD 013 A1 wants.

This PRD consolidates the surface into a single user-facing `/sw-retrospective` command with internal
`--pre-merge` / `--post-merge` phase dispatch and a `compound.autonomy` knob, deprecates the two old commands as
backward-compatible aliases, and gives PRD 013 A1 a single-sourced retrospective chain to invoke — all while
preserving fail-closed memory writes (R19), rule-class human gates (R21/R42), and "no false `complete` on a
declined merge" (R53). It derives from the frozen brainstorm
`docs/brainstorms/2026-06-26-retrospective-command-consolidation-requirements.md` (R1–R12) and closes
GAP-BACKLOG rows 26, 27, and 31.

## Goals

1. One user-facing command (`/sw-retrospective`) for all post-delivery compounding, with internal phase dispatch
   rather than two overlapping top-level commands.
2. A name that matches the operator mental model (retrospective), with the old names preserved as deprecated
   aliases for one release.
3. A `compound.autonomy` knob that lets the pre-merge chain run hands-off (for PRD 013 A1) without ever
   bypassing the memory or rule-class safety gates, and without ever producing a false `complete`.
4. A single-sourced retrospective chain the deliver conductor invokes, eliminating duplicated procedures.

## Non-Goals

- Changing what the retro / learnings / memory-sync / status steps *do* — only how they are surfaced and gated.
- Removing the deprecated `/sw-compound` and `/sw-compound-ship` aliases in this PRD (removal is a later release
  once the deprecation window closes; see DL-3).
- The deliver terminal sequencing itself (auto-run before terminal PR, PR/watch/stabilize, cleanup autonomy) —
  PRD 013 A1; this PRD only provides the single-sourced chain that A1 invokes.
- Memory provider source-of-truth policy — PRD 015.
- Weakening fail-closed memory writes (R19) or rule-class human gates (R21/R42).

## Requirements

R-IDs are carried forward from the frozen brainstorm (stable namespace; do not renumber). Requirement text
receives only clarifying edits.

### Consolidated command surface

- **R1** A single user-facing command `/sw-retrospective` MUST be the only top-level entry for post-delivery
  compounding, subsuming the chain `retro → compound (learnings) → memory-sync → status`.
- **R2** `/sw-retrospective` MUST support internal phase dispatch via `--pre-merge` (deliver in-loop, before the
  terminal PR) and `--post-merge` (standalone reconcile after merge detection); with no flag it MUST
  deterministically auto-detect the phase from deliver run-state and merge status.
- **R3** The atomic sub-steps (`retro` report, `memory-sync`, `status`) MUST remain script/skills-backed and be
  invoked internally by `/sw-retrospective`; the compound *write* step MUST NOT remain a standalone top-level
  command. Already-top-level atomics (`/sw-retro` report, `/sw-memory-sync`, `/sw-status`) are unchanged.

### Backward-compatible deprecation

- **R4** `/sw-compound` and `/sw-compound-ship` MUST become deprecated aliases that route to `/sw-retrospective`
  (`compound-ship` → phase auto-detect; `compound` → the atomic write step) and MUST emit a one-release
  deprecation notice naming `/sw-retrospective` as the replacement; observable behavior MUST be preserved during
  the deprecation window.
- **R5** The rename MUST be propagated everywhere the old names appear: `core/commands/`, `dist/` emit,
  `workflow.config.json` routing, conductor/deliver handoffs, rules, and any fixtures referencing `sw-compound`.

### Preserved semantics

- **R6** Pre-merge `completed-pending-merge` semantics (parent compound R17–R20) MUST be preserved: a pre-merge
  run records `completed-pending-merge`, never `complete`.
- **R7** Memory writes performed during the chain MUST remain fail-closed (parent R19): a redaction/preflight
  failure aborts the write — never a silent drop or raw store.
- **R8** Rule-class promotions MUST remain human-gated (parent R21/R42) regardless of `compound.autonomy`.
- **R11** INDEX → `complete` MUST flip only on actual merge detection (parent R53/R56), even under
  `compound.autonomy: auto`; a declined merge MUST NOT produce a false `complete`.

### Autonomy + single-source

- **R9** The deliver conductor terminal-ship handoff MUST invoke `/sw-retrospective --pre-merge` as the single
  source of the retrospective chain — it MUST NOT duplicate the retro/compound/memory/status procedures (this is
  the chain PRD 013 A1 R20/DL-11 consumes).
- **R10** A `compound.autonomy` config knob (`supervised` | `auto`) MUST gate the approval / "did you merge?"
  prompts: `supervised` (default) preserves today's gates; `auto` runs the pre-merge chain and commits
  learnings/status on the feature branch when the terminal PR is green, treats merge as external, and triggers
  post-merge reconcile on merge detection without re-prompting. `auto` MUST NOT bypass R7 or R8.

### Cross-cutting

- **R12** All `core/` changes MUST propagate to `dist/cursor` and `dist/claude-code` via
  `python3 -m sw generate --all` (freshness gate passing), be covered by fixtures (alias routing, phase
  dispatch, autonomy knob, no-false-complete, fail-closed memory), and be documented in the affected skills,
  rules, and guides.

## Technical Requirements

- **TR1 — New `/sw-retrospective` command.** Add `core/commands/sw-retrospective.md` as the consolidated
  orchestrator with `--pre-merge` / `--post-merge` flags and no-flag auto-detection from deliver run-state +
  merge status; it invokes the existing retro/compound/memory-sync/status skills internally (R1, R2, R3).
- **TR2 — Deprecated aliases.** Rewrite `core/commands/sw-compound.md` and `core/commands/sw-compound-ship.md`
  as thin deprecation shims that print a one-release notice and route to `/sw-retrospective` with the mapped
  phase, preserving behavior (R4).
- **TR3 — Routing + handoff propagation.** Update `workflow.config.json` `routing`, `skills/conductor/SKILL.md`,
  `skills/deliver/SKILL.md`, `skills/compound/SKILL.md`, and any rule/fixture referencing `sw-compound` to point
  at `/sw-retrospective`; the conductor terminal-ship handoff calls `/sw-retrospective --pre-merge` (R5, R9).
- **TR4 — Autonomy knob.** Add `compound.autonomy` (`supervised` | `auto`, default `supervised`) to
  `workflow.config.json`, `.sw/config.schema.json`, and `/sw-setup` seeding; the pre-merge chain reads it to gate
  approval / "did you merge?" prompts only, never the R7/R8 safety gates (R10).
- **TR5 — Preserved-semantics wiring.** Ensure the consolidated command keeps `completed-pending-merge` on
  pre-merge (R6), fail-closed memory writes via the memory provider chokepoint (R7), human-gated rule-class
  promotion (R8), and merge-detection-only completion (R11) — reusing the existing compound/memory machinery, not
  re-implementing it.
- **TR6 — Emitter + docs + fixtures.** Regenerate `dist/` via `python3 -m sw generate --all`; add the fixtures in
  the Testing Strategy; update skills, `sw-naming.mdc` (command surface), and guides (R12).

## Security & Compliance

- **Memory chokepoint unchanged.** All memory writes continue through the redaction/preflight chokepoint
  fail-closed (R7); `compound.autonomy: auto` governs prompts, not safety (R10).
- **Rule-class human gate retained.** Promotion of a learning to a rule-class memory stays human-gated under all
  autonomy settings (R8).
- **No false state.** INDEX `complete` requires real merge detection (R11); autonomy cannot fabricate a merge.
- **No new secret surface.** The command consolidation and the autonomy knob are non-secret workflow config.

## Testing Strategy

All fixtures extend the existing harness invoked by `workflow.config.json` `verify.test` (notably the
compound/retro and command-surface suites).

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `retrospective-single-entry` | `/sw-retrospective` runs the full `retro → compound → memory-sync → status` chain as one command | R1 |
| `retrospective-phase-dispatch` | `--pre-merge` / `--post-merge` select the right phase; no-flag auto-detects from run-state + merge status | R2 |
| `retrospective-atomics-internal` | the compound write step is not a standalone top-level command; sub-steps invoked internally | R3 |
| `compound-alias-deprecation` | `/sw-compound` + `/sw-compound-ship` route to `/sw-retrospective`, preserve behavior, and print the one-release notice | R4 |
| `compound-rename-propagation` | no live top-level reference to `sw-compound` remains in routing/handoffs/fixtures (only deprecated aliases) | R5 |
| `retrospective-pending-merge` | a pre-merge run records `completed-pending-merge`, never `complete` | R6 |
| `retrospective-memory-fail-closed` | a redaction/preflight failure aborts the memory write (no silent drop / raw store) | R7 |
| `retrospective-rule-class-gated` | rule-class promotion stays human-gated under `compound.autonomy: auto` | R8 |
| `retrospective-conductor-single-source` | the deliver conductor terminal-ship handoff invokes `/sw-retrospective --pre-merge`; no duplicated procedure | R9 |
| `compound-autonomy-knob` | `auto` runs the pre-merge chain hands-off and commits learnings/status on the feature branch when the PR is green; `supervised` (default) preserves gates | R10 |
| `retrospective-no-false-complete` | INDEX flips to `complete` only on real merge detection; a declined merge does not | R11 |
| `retrospective-emitter-freshness` | `dist/` regenerated and fresh | R12 |
| `retrospective-docs-presence` | skills, naming rule, and guides describe the consolidated command + autonomy knob | R12 |

Per-R traceability is finalized in `/sw-tasks`.

## Rollout Plan

- **Single feature branch** `feat/retrospective-command-consolidation`, delivered in dependency-ordered phases:
  (1) new `/sw-retrospective` command + internal phase dispatch (R1–R3); (2) deprecated aliases + rename
  propagation across routing/handoffs/fixtures (R4, R5); (3) `compound.autonomy` knob + preserved-semantics
  wiring (R6–R8, R10, R11) + conductor single-source handoff (R9); (4) docs + dist + fixtures (R12).
- **Backward compatible.** Old command names keep working through the aliases for one release (R4); absent
  `compound.autonomy` resolves to `supervised` (today's behavior). Removal of the aliases is a later release.
- **Ordering vs PRD 013 A1.** This PRD SHOULD land before PRD 013 A1 enables end-to-end `auto`; until then A1's
  wiring resolves the current `compound-ship` chain (A1 DL-11). The two compose: A1 invokes the single-sourced
  chain this PRD defines.
- **Emitter.** Regenerate `dist/` after every `core/` change; freshness gate enforces parity.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Consolidate to a single `/sw-retrospective` with internal `--pre-merge`/`--post-merge` dispatch | Removes the operator confusion of two overlapping commands; flags express the deliver-in-loop vs standalone modes without a second top-level surface (product + scope-guardian lenses). |
| DL-2 | Name it `/sw-retrospective`; keep the atomic `/sw-retro` report distinct | Matches the operator mental model (post-delivery reflection) without colliding with the existing atomic retro *report* step (coherence lens). |
| DL-3 | Deprecate `/sw-compound` + `/sw-compound-ship` as aliases for one release, not a hard break | External docs/automation may reference the old names; a one-release alias + notice avoids breakage while steering usage (feasibility lens). |
| DL-4 | `compound.autonomy` gates prompts only, never the memory/rule-class safety gates | Autonomy is about removing the "did you merge?" / approval friction, not about loosening fail-closed memory (R19) or rule-class human gates (R21/R42) (adversarial lens). |
| DL-5 | INDEX `complete` flips only on real merge detection even under `auto` | A declined merge must never read as `complete`; merge-detection-gated completion preserves R53 under autonomy (adversarial lens). |
| DL-6 | Provide a single-sourced chain for the deliver conductor, do not duplicate procedures | PRD 013 A1 must invoke one chain; duplicating retro/compound/memory/status in the conductor would diverge (coherence + scope-guardian lenses). |

## Open Questions

None. Deprecation window is one release (DL-3); naming is resolved (DL-2); autonomy/safety boundary is fixed
(DL-4, DL-5).
