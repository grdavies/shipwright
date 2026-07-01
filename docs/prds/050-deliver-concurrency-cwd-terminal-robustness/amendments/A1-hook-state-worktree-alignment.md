---
date: 2026-07-01
amends: docs/prds/050-deliver-concurrency-cwd-terminal-robustness/050-prd-deliver-concurrency-cwd-terminal-robustness.md
brainstorm: docs/brainstorms/2026-07-01-hook-state-worktree-alignment-requirements.md
signal: feedback-hook-worktree-root-mismatch-2026-07-01
visibility: public
frozen: true
frozen_at: 2026-07-01
---

# Amendment A1: hook-state worktree alignment (concurrent worktree sessions)

## Overview

Parent PRD 050 Thread A (R1–R6) guards **git mutations** against the shared primary checkout under concurrency
(`freeze-commit`, `spec-seed`, `assert_primary_off_target`). It does **not** address a second split-authority
failure observed during concurrent `/sw-doc` PRD sessions: **ephemeral hook state** (pre-work memory search
records and dispatch-preflight nonces under `.cursor/hooks/state/`) is written by scripts using the caller's
`cwd` git toplevel (worktree) while registered `preToolUse` hooks read using Cursor's `workspace_roots[0]`
(IDE workspace — usually the primary checkout). Agents that correctly run prework/preflight from a worktree
still receive false `missing-prework-search-record` and `missing-preflight-nonce` denials.

This amendment extends Thread A with **R20–R33** (dual-layer fix): mechanical cwd-aware hook root resolution
as the default path, plus documented `move_agent_to_root` as the operator escape hatch when mechanical
alignment cannot apply. Input:
`docs/brainstorms/2026-07-01-hook-state-worktree-alignment-requirements.md`.

Deliver durable state (`.cursor/sw-deliver-state.<slug>.json`, locks, merge queue) remains repo-root
canonical per PRD 013 R28 — unchanged. Only gitignored hook ephemeral state follows the active worktree root.

## Context

**Observed failure mode (2026-07-01, concurrent PRD creation):**

1. `docs_worktree.py provision` creates `.sw-worktrees/docs-<topic>/`.
2. Agent runs `wave.py memory prework record` and `wave.py dispatch preflight` from worktree `cwd`.
3. Records land at `<worktree>/.cursor/hooks/state/`.
4. IDE workspace root stays on primary checkout.
5. `before_task_dispatch.py` → `workspace_root(payload)` → primary `.cursor/hooks/state/` → deny.

**Root cause:**

| Layer | Resolution | State path |
| --- | --- | --- |
| `wave.py`, `wave_memory_prework.py`, `wave_preflight.py` | `git -C $cwd rev-parse --show-toplevel` | Worktree |
| `sw_hook_util.workspace_root()` | First `workspace_roots[]`; `cwd` only when roots absent | Primary |

**DL-1 resolved (Cursor `preToolUse` `cwd` field):**

Cursor's published hook contract documents `cwd` as a standard input field on `preToolUse` (and
`postToolUse` / `postToolUseFailure`) for agent tool calls — see
[Cursor Hooks — preToolUse](https://cursor.com/docs/hooks#pretooluse). Example payload includes
`"cwd": "/project"` alongside `workspace_roots`. Shipwright fixtures (`run_memory_prework_fixtures.py`,
`task-dispatch-hook-feasibility.py`) already pass `cwd` in synthetic `preToolUse` evaluations.

**Caveat (fail-closed requirement):** `beforeShellExecution` payloads may carry an empty `cwd` (observed in
third-party hook deep-dives). R20 therefore MUST treat absent/empty/non-directory `cwd` as "mechanical
alignment unavailable" and retain `workspace_roots[0]` — R23/R24 operator contract (`move_agent_to_root`)
becomes the required remediation when roots diverge under those conditions. R20 MUST NOT assume `cwd` is
always populated for every hook event type; alignment applies to `preToolUse` agent tool calls where `cwd`
is present and resolves to a recognized worktree.

**Relationship to PRD 049:** PRD 049's operator worktree contract and `deliver_cwd_guard` address in-flight
deliver-run cwd refusal and repo-root vs implementation distinction. This amendment is orthogonal — hook
ephemeral state alignment, not deliver durable state or default-branch guards. Cross-link only; do not merge
primitives (PRD 049 D5).

## Goals

1. Agents working in any Shipwright worktree (docs, orchestrator, phase, feature) can run prework + dispatch
   preflight from worktree `cwd` and pass `preToolUse` gates without false denials when IDE workspace ≠
   worktree.
2. Concurrent worktree sessions each own isolated `.cursor/hooks/state/` trees — no cross-contamination.
3. Single-checkout sessions (workspace = cwd toplevel) show zero regression.
4. When mechanical alignment cannot apply, operators have an explicit, documented `move_agent_to_root` path.

## Non-Goals

- Moving deliver durable state into worktrees (PRD 013 R28 / PRD 049 R1 — unchanged).
- Keying hook state by worktree slug at repo root for multi-session-same-workspace concurrency (deferred).
- Changing memory provider search behavior — only hook-state breadcrumb paths.
- `sessionStart` worktree informational injection (DL-2 deferred to implementer; default: silent).
- Editing frozen parent PRD 050 body in place.

## Requirements

Continue parent namespace (parent ends at R19; this amendment adds R20–R33).

### Thread A extension — Hook-state worktree alignment

- **R20** (origin: brainstorm R1; DL-1) `sw_hook_util.workspace_root()` MUST resolve hook-state root
  consistently with script-layer `repo_root()` when **all** of the following hold:
  1. `payload.cwd` is a non-empty string resolving to an existing directory;
  2. `git -C <cwd> rev-parse --show-toplevel` yields a toplevel that differs from `workspace_roots[0]`;
  3. `is_shipwright_worktree(cwd_toplevel, primary_toplevel)` (R21) returns true.
  When (1–3) hold, return cwd's git toplevel. Otherwise retain today's `workspace_roots[0]`-first behavior
  (with existing `cwd` / `Path.cwd()` fallbacks when roots absent).

- **R21** (origin: brainstorm R2) A shared module `scripts/worktree_root.py` (or extension of
  `worktree_lib.py` if colocated helpers already exist) MUST export
  `is_shipwright_worktree(toplevel: Path, primary: Path) -> bool`: true when the path is (a) under
  `<primary>/.sw-worktrees/` or (b) a non-primary entry in `git worktree list` for the repository. R21 MUST
  be used by `workspace_root()` (R20) and script-side guards (R25).

- **R22** (origin: brainstorm R3) All hook consumers reading/writing `.cursor/hooks/state/` MUST use
  `workspace_root(payload)` only — no ad-hoc root resolution. Minimum surfaces: `before_task_dispatch.py`,
  `before-submit-guardrails.py`, Cursor/Claude hook adapters.

- **R23** (origin: brainstorm R4) `core/commands/sw-doc.md`, `core/commands/sw-worktree.md`, and
  `core/skills/git-workflow/SKILL.md` MUST document: after worktree provision, when IDE workspace and
  terminal/worktree cwd diverge, call Cursor `move_agent_to_root` to the worktree path **or** rely on R20
  mechanical alignment when `preToolUse` carries a valid worktree `cwd`. Explain that hooks read hook state
  from the R20-resolved root, not necessarily the IDE workspace folder.

- **R24** (origin: brainstorm R5) `scripts/docs_worktree.py` provision and resume JSON output MUST include
  `nextSteps`: `cd <path>`, `move_agent_to_root <path>`, and a surface-appropriate
  `python3 scripts/wave.py memory prework record --surface <cmd>` example for docs workflows.

- **R25** (origin: brainstorm R6) `wave_memory_prework.py` and `wave_preflight.py` MUST fail closed (exit
  non-zero with remediation on stderr) when the write root (cwd git toplevel) differs from the primary
  checkout path **and** R21 returns false for cwd — remediation MUST name both paths and recommend
  `move_agent_to_root`.

- **R26** (origin: brainstorm R7) When R20 alignment applies (R21 true, valid cwd), script-side writers MUST
  NOT emit warnings — transparent mechanical path.

- **R27** (origin: brainstorm R8) Fixture `hook-state-worktree-cwd-alignment` MUST prove: `workspace_roots` =
  primary, `cwd` = sibling `.sw-worktrees/docs-fixture/`, `memory prework record` written from cwd → first
  mutating `preToolUse` passes; without record → `missing-prework-search-record`.

- **R28** (origin: brainstorm R9) Fixture `hook-state-dispatch-preflight-worktree-alignment` MUST prove:
  dispatch preflight written from worktree cwd → bound `Task` passes; without → `missing-preflight-nonce`.

- **R29** (origin: brainstorm R10) Fixture `hook-state-primary-no-false-positive` MUST prove: when `cwd` and
  `workspace_roots[0]` resolve to the same toplevel, behavior matches pre-amendment baseline.

- **R30** (origin: brainstorm R11) Fixture `hook-state-ambiguous-worktree-fail-closed` MUST prove: when cwd
  is absent/empty or not a recognized worktree and roots would diverge, hooks fail closed with remediation
  referencing `move_agent_to_root` — no silent wrong-root reads.

- **R31** (origin: brainstorm R12) `.sw/layout.md` MUST document: deliver durable state = repo-root
  canonical; hook ephemeral state (`.cursor/hooks/state/*`) = follows R20-resolved active root.

- **R32** (origin: brainstorm R13) `core/` doc/hook changes require `python3 scripts/build-chain-sync.py`
  before amendment freeze.

- **R33** (origin: brainstorm R14) On ship, gap unit for signal
  `feedback-hook-worktree-root-mismatch-2026-07-01` (`plugin-self` / `meta-shipwright`) flips to `resolved`
  referencing PRD 050 A1 — fixture-gated, not narrative closure.

## Technical Requirements

- **TR14** (R20/R21/R22) — Implement `is_shipwright_worktree()` in `scripts/worktree_root.py` (stdlib +
  `subprocess` `git worktree list` only; Python-first). Update `core/hooks/sw_hook_util.py:workspace_root()`
  to call R21 before returning `workspace_roots[0]`. Mirror to `dist/` via build-chain-sync.

- **TR15** (R25/R26) — Add optional `--primary <path>` probe to `wave_memory_prework.py` and
  `wave_preflight.py` dispatch writer: when cwd toplevel ≠ primary and R21 false, refuse with remediation.
  Primary defaults to `git worktree list` first entry or `workspace_roots[0]` when `SW_WORKSPACE_ROOT` env is
  set by the platform (probe only; do not require env).

- **TR16** (R23/R24/R31) — Doc and `docs_worktree.py` `nextSteps` updates; layout table row for hook-state
  vs deliver-state split.

- **TR17** (R27–R30) — Register four fixtures in `core/sw-reference/pr-test-plan.manifest.json`; add harness
  cases to `scripts/test/run_memory_prework_fixtures.py` and/or new
  `scripts/test/run_hook_worktree_alignment_fixtures.py`.

Roll into parent Thread A rollout (parent Rollout Plan step 1): implement TR14–TR16 alongside TR1–TR4;
fixtures TR17 with Thread A fixture batch.

## Testing Strategy

Add to parent Testing Strategy:

- `hook-state-worktree-cwd-alignment` (R27, TR17)
- `hook-state-dispatch-preflight-worktree-alignment` (R28, TR17)
- `hook-state-primary-no-false-positive` (R29, TR17)
- `hook-state-ambiguous-worktree-fail-closed` (R30, TR17)

No regression to PRD 019 R8 prework gate, PRD 017 R23 dispatch preflight keyed records (PRD 024 A2 R38), or
PRD 013 R28 deliver-state canonicalization.

## Decision Log

- **D-A1-1 (2026-07-01):** Dual-layer fix (mechanical R20 + operator R23/R24) — operator-only rejected as
  fragile; repo-root keyed hook state rejected as conflating ephemeral hook state with conductor runtime.
- **D-A1-2 (2026-07-01):** Scope all Shipwright worktrees, not docs-only — orchestrator/phase hit the same
  mismatch.
- **D-A1-3 (2026-07-01):** DL-1 resolved — Cursor documents `cwd` on `preToolUse`; R20 requires valid cwd +
  R21 recognition; absent/empty cwd → fail-closed to operator contract (R30).
- **D-A1-4 (2026-07-01):** DL-2 deferred — `sessionStart` worktree mention stays out of scope; implementer
  may add informational line later without amendment.

## Security & Compliance

- R21 uses local `git worktree list` only — no new network surface.
- R20 MUST NOT broaden hook-state reads outside the repository's linked worktrees (prevents arbitrary path
  injection via crafted `cwd`).
- Fail-closed posture preserved: ambiguous or unrecognized cwd never silently reads primary hook state when
  records were written elsewhere.
