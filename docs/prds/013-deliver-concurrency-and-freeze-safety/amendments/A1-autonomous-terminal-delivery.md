---
date: 2026-06-26
amends: docs/prds/013-deliver-concurrency-and-freeze-safety/013-prd-deliver-concurrency-and-freeze-safety.md
frozen: true
frozen_at: 2026-06-26
---

# Amendment A1: Autonomous terminal delivery (retrospective → PR → CI-watch → stabilize → cleanup)

## Overview

PRD 013 hardened deliver-loop *state, locking, and freeze safety* but deliberately left the deliver-loop
**terminal path** (what happens once every phase is green-merged on `<type>/<slug>`) untouched. Three open
`GAP-BACKLOG.md` rows ask for that terminal path to run hands-off while keeping the merge to `main` human-gated:

1. **Retrospective not auto-run before the terminal PR** — today `compound-ship --pre-merge` is a later deliver
   phase that can halt for a human ack; operators expect the retrospective/compounding chain to run
   automatically at deliver end, **before** the `<type>/<slug>` → `main` PR is opened, with its artifacts on the
   feature branch.
2. **Terminal PR + CI-watch + stabilize should be autonomous** — the feature branch needs an open PR to `main`,
   then a bounded `/sw-watch-ci`, then `/sw-stabilize` on `red`/`blocked`, all without user intervention; merge
   to `main` must stay human-gated (no auto-merge, no force-push `main`, no dismissing failing checks).
3. **`/sw-cleanup` requires an explicit human confirm before apply** — fully autonomous deliver cannot prune
   merged branches/worktrees without a yes/proceed; a zero-interaction path is wanted only after a known-good,
   deterministic merge.

This amendment extends PRD 013's deliver-loop scope to cover the terminal path. It composes with — and does not
override — the parent's invariants: the merge-to-`main` gate stays human (PRD 013 Non-Goals; PRD 004/007), the
freeze/seed commit machinery (PRD 013 R1–R5) and PRD 005 amendment A2 (artifacts on `<type>/<slug>`, never
`main`) are preserved, and per-branch scoping (PRD 013 R6–R12) is unchanged. It adds new **opt-in, config-gated**
autonomy; default behavior is unchanged unless an operator opts in.

## Context

The terminal sequence the operator wants is:

```
all phases green-merged on <type>/<slug>
  → retrospective chain (retro → compound/learnings → memory-sync → status), artifacts committed on <type>/<slug>
  → open/update <type>/<slug> → main PR (existing phase-pr path)
  → push head → check-gate.sh watch loop (bounded)
  → on red/blocked: /sw-stabilize within deliver.remediation.maxAttempts
  → halt at the human merge gate (never auto-merge)
  → (post-merge detection) optional zero-interaction /sw-cleanup of the deterministic wouldRemove set
```

The retrospective chain's command identity is being consolidated by **PRD 014**
(`/sw-compound` → `/sw-retrospective`, with `compound.autonomy`). This amendment does **not** re-implement that
chain: it wires the deliver terminal path to invoke whatever single-sourced retrospective chain the repo
exposes (today `/sw-compound-ship --pre-merge`; after PRD 014, `/sw-retrospective --pre-merge`). The conductor's
in-turn self-continuation (PRD 009 R6/R13) owns the watch/stabilize cycle until `green` or a legitimate halt.

## Goals

1. **Retrospective before the terminal PR** — when all phases are green-merged, the retrospective chain runs
   automatically (no re-prompt in autonomous mode) and its artifacts are committed on `<type>/<slug>` so they
   ride into the terminal PR diff — never on `main`, never waiting for merge.
2. **Hands-off terminal ship** — terminal-ship creates/updates the PR, pushes the head, watches CI, and runs
   stabilize within a bounded remediation budget, all without user intervention, halting only at legitimate
   gates.
3. **Human merge gate preserved** — the terminal path never auto-merges, force-pushes `main`, or dismisses
   failing checks; the merge to `main` remains the human gate.
4. **Opt-in autonomy** — every new autonomous behavior is governed by a conservative-default config knob, so
   existing supervised flows are unchanged unless an operator opts in.
5. **Zero-interaction cleanup only when safe** — cleanup may apply its dry-run `wouldRemove` set without a
   confirm strictly after a deterministic merge, with no in-flight run, and never on the current/default branch;
   all PRD 011 fail-closed protections are retained.

## Non-Goals

- **Auto-merging to `main`, force-pushing `main`, or dismissing/overriding failing checks** — explicitly
  preserved as out of scope (parent Non-Goals; PRD 004/007 terminal merge gate).
- **Committing retrospective or any docs to `main`** — artifacts land on `<type>/<slug>` per PRD 005 A2
  R80–R82 / PRD 013 DL-1.
- **Re-implementing the retrospective chain** — command consolidation and the `compound.autonomy` contract are
  PRD 014; this amendment only invokes the single-sourced chain (see DL-11).
- **Changing per-branch scoping, freeze-commit, or living-doc serialization** (PRD 013 R1–R12) — unchanged.
- **Weakening memory fail-closed writes or rule-class human gates** (PRD 007 / `memory-guardrails`) — retained.

## Requirements

R-IDs continue PRD 013's namespace (parent ends at R19; this amendment adds R20–R27). No parent requirement is
superseded or retracted — this amendment is purely additive (declared directive extension).

- **R20** When every phase reaches `green-merged` on `<type>/<slug>`, the deliver-loop terminal path MUST
  auto-invoke the retrospective chain (retro → compound/learnings → memory-sync → status) **before** opening the
  terminal `<type>/<slug>` → `main` PR, with no human re-prompt when terminal autonomy is enabled (R24). The
  retrospective MUST NOT wait for, or depend on, a merge to `main`.
- **R21** Retrospective artifacts (learnings, status, and any compound outputs) MUST be committed onto
  `<type>/<slug>` (never `main`, preserving PRD 005 A2 / PRD 013 DL-1) so they appear in the terminal PR diff.
  Memory writes during the chain MUST remain fail-closed (PRD 007 / `memory-guardrails`), and rule-class
  promotions MUST remain human-gated — autonomy never bypasses those gates.
- **R22** After the retrospective chain, the deliver-loop `terminal-ship` step MUST autonomously: (a) create or
  update the `<type>/<slug>` → `main` PR via the existing `phase-pr` path; (b) push the head; (c) run a bounded
  `check-gate.sh` / `/sw-watch-ci` loop; (d) on `red`/`blocked`, run `/sw-stabilize` within the
  `deliver.remediation.maxAttempts` budget — all without user intervention. The conductor's in-turn
  self-continuation (PRD 009 R6/R13) owns this watch/stabilize cycle until `green` or a legitimate halt.
- **R23** The terminal path MUST NOT auto-merge to `main`, force-push `main`, or dismiss/override failing
  checks. It MUST halt only at legitimate gates: exhausted remediation budget (`maxAttempts`), a destructive git
  operation, or an explicit `supervised` checkpoint. The merge to `main` is always the human gate.
- **R24** Terminal autonomy MUST be config-gated by a `deliver.terminal.autonomy` knob with values
  `supervised` | `auto`. `auto` runs the R20–R22 chain hands-off; `supervised` preserves today's halts
  (operator-driven retrospective + PR + watch). The default MUST be `supervised` (no behavior change without
  opt-in). The knob MUST be accepted by `.sw/config.schema.json` and seeded by `/sw-setup` defaults.
- **R25** A zero-interaction cleanup path MUST apply `/sw-cleanup`'s dry-run `wouldRemove` set without a human
  confirm **only when all** of: (a) the `<type>/<slug>` merge status is deterministic (not `indeterminate`);
  (b) no in-flight deliver lock or open journal exists for **any** scoped run (per PRD 013 R10 enumeration);
  (c) the target is neither the current nor the default branch. It MUST log the full report and MUST NEVER
  delete unmerged or protected items, and MUST NEVER use `rm -rf` on worktrees — all PRD 011 R8–R10 fail-closed
  protections are retained.
- **R26** Zero-interaction cleanup MUST be config-gated by `cleanup.autonomy` with values `confirm` | `auto`,
  defaulting to `confirm` (preserving PRD 011 R8–R10 agent-prompt-then-apply). When merge status is
  `indeterminate`, autonomy MUST fall back to the human gate regardless of the knob.
- **R27** All new behavior authored in `core/` (deliver/conductor skills, `sw-cleanup` command, config schema +
  defaults, fixtures) MUST be propagated to `dist/cursor` and `dist/claude-code` via
  `python3 -m sw generate --all` with the emitter freshness gate passing, and MUST be documented in
  `skills/deliver/SKILL.md`, `skills/conductor/SKILL.md`, `core/commands/sw-cleanup.md`,
  `rules/sw-workflow-sequencing.mdc`, and the relevant guides.

## Technical Requirements

- **TR-A1 — Terminal retrospective hook.** Extend the deliver-loop terminal path (`wave_terminal.py` /
  `skills/deliver/SKILL.md` terminal-ship) so that, on all-phases-`green-merged`, it invokes the single-sourced
  retrospective chain and commits its artifacts onto `<type>/<slug>` via the PRD 013 R5 idempotent seed helper
  (docs-only, never `main`) before any PR action (R20, R21).
- **TR-A2 — Autonomous PR/watch/stabilize.** In `deliver.terminal.autonomy: auto`, terminal-ship calls the
  existing `phase-pr` PR path, pushes head, then drives a bounded `check-gate.sh` loop with `/sw-stabilize`
  remediation up to `deliver.remediation.maxAttempts`; legitimate-halt taxonomy is reused from PRD 007/009 (no
  new merge authority) (R22, R23).
- **TR-A3 — Config + schema knobs.** Add `deliver.terminal.autonomy` and `cleanup.autonomy` to
  `workflow.config.json`, `.sw/config.schema.json`, and `/sw-setup` seeding defaults (both conservative)
  (R24, R26).
- **TR-A4 — Zero-interaction cleanup gate.** Add an autonomous apply path in `cleanup_lib.py` /
  `core/commands/sw-cleanup.md` keyed on `cleanup.autonomy: auto` + the R25 deterministic-merge / no-in-flight /
  not-current-or-default preconditions; reuse the PRD 011 `wouldRemove` computation and all fail-closed guards;
  `indeterminate` → human gate (R25, R26).
- **TR-A5 — Emitter + docs.** Regenerate `dist/` via `python3 -m sw generate --all`; update deliver/conductor
  skills, `sw-cleanup` command, sequencing rule, and guides (R27).

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `deliver-terminal-retro-before-pr` | retrospective chain auto-runs before the terminal PR; artifacts committed on `<type>/<slug>`, never `main` | R20, R21 |
| `deliver-terminal-retro-fail-closed` | memory writes stay fail-closed and rule-class promotions stay human-gated during the autonomous chain | R21 |
| `deliver-terminal-autonomous-watch-stabilize` | terminal-ship creates/updates PR → pushes head → watch → stabilize within `maxAttempts` with no user intervention | R22 |
| `deliver-terminal-no-auto-merge` | terminal path never auto-merges/force-pushes `main`/dismisses checks; halts at exhausted budget / destructive git | R23 |
| `deliver-terminal-autonomy-knob` | `deliver.terminal.autonomy: auto` runs hands-off; `supervised` (default) preserves halts; schema accepts the knob | R24 |
| `cleanup-autonomy-auto-after-merge` | `cleanup.autonomy: auto` applies only the `wouldRemove` set when merge is deterministic + no in-flight run + not current/default; logs the report | R25 |
| `cleanup-autonomy-indeterminate-falls-back` | `indeterminate` merge → human gate regardless of knob; default `confirm` preserves PRD 011 behavior; protected/unmerged never deleted | R25, R26 |
| `terminal-autonomy-emitter-freshness` | `dist/` regenerated and fresh after the `core/` changes | R27 |
| `terminal-autonomy-docs-presence` | deliver/conductor skills, `sw-cleanup` command, sequencing rule describe the terminal autonomy + cleanup knobs | R27 |

Per-R traceability is finalized in the PRD 013 task-list refresh (`/sw-tasks` against the U8 union); these
fixtures extend `run-deliver-loop-fixtures.sh` and `run-cleanup-fixtures.sh`.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-8 (PRD 013) | Retrospective runs before the terminal PR and commits artifacts onto `<type>/<slug>`, never `main`, and never waits for merge | Operators want post-delivery reflection captured in the PR diff; committing on the feature branch preserves PRD 005 A2 / PRD 013 DL-1 (spec/docs land in the `<type>/<slug>` → `main` diff, not on `main`). |
| DL-9 (PRD 013) | Terminal-ship drives PR → watch → stabilize autonomously, but the merge to `main` stays human; halt only at legitimate gates | Full autonomy up to the merge gate matches the operator request while preserving the PRD 004/007 invariant and PRD 013 Non-Goal (no auto-merge / force-push / check dismissal). The conductor's existing self-continuation owns the loop — no new merge authority is introduced (adversarial + scope-guardian lenses). |
| DL-10 (PRD 013) | New autonomy is opt-in, config-gated, conservative-default (`deliver.terminal.autonomy: supervised`, `cleanup.autonomy: confirm`) | A silent behavior change to a destructive-adjacent path (cleanup, PR/push) is unacceptable; opt-in knobs let teams adopt autonomy deliberately and keep the default identical to today (product + adversarial lenses). |
| DL-11 (PRD 013) | A1 invokes the single-sourced retrospective chain; it does not re-implement it | Command consolidation (`/sw-compound` → `/sw-retrospective`) and the `compound.autonomy` contract are PRD 014; A1 wires the terminal path to whatever single chain the repo exposes (today `/sw-compound-ship --pre-merge`), so the two PRDs compose without divergence. Ordering: PRD 014 should land first, or A1's wiring resolves the current `compound-ship` chain until it does (coherence lens). |
| DL-12 (PRD 013) | Zero-interaction cleanup only after a *deterministic* merge with no in-flight run and not current/default | Cleanup is destructive-adjacent; the strictest preconditions guarantee we only prune a known-good, fully-merged branch, and `indeterminate` always falls back to the human gate, retaining every PRD 011 protection (adversarial lens). |

## Open Questions

None. The retrospective-chain identity dependency is resolved structurally (DL-11: invoke the single-sourced
chain, consolidation is PRD 014). The conservative defaults (DL-10) make the amendment safe to freeze ahead of
PRD 014; enabling `auto` end-to-end is an operator opt-in once both land.
