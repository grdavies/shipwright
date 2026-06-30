---
date: 2026-06-26
topic: retrospective-command-consolidation
prd: docs/prds/014-retrospective-command-consolidation/014-prd-retrospective-command-consolidation.md
frozen: true
frozen_at: 2026-06-26
---

# Tasks — PRD 014 Retrospective command consolidation

Generated from the frozen PRD `014-prd-retrospective-command-consolidation.md` (effective union R1–R12). Phases
are dependency-ordered: the new command lands first, then aliases + rename propagation, then the autonomy knob +
preserved-semantics wiring + conductor single-source, then docs/dist/fixtures.

## Tasks

### 1. New `/sw-retrospective` command + internal phase dispatch (M)

- [x] 1.1 Add the consolidated command (R1)
  - **File:** `core/commands/sw-retrospective.md`
  - **Expected:** single top-level command running `retro → compound → memory-sync → status`; description states scope + non-goals per `sw-naming.mdc`
- [x] 1.2 Internal phase dispatch + auto-detection (R2)
  - **File:** `core/commands/sw-retrospective.md`, `skills/compound/SKILL.md`
  - **Expected:** `--pre-merge` / `--post-merge` select the phase; no-flag deterministically resolves phase from deliver run-state + merge status
- [x] 1.3 Demote the compound write step to internal-only (R3)
  - **File:** `skills/compound/SKILL.md`, `core/commands/`
  - **Expected:** compound write step invoked internally; not a standalone top-level command; existing atomic `/sw-retro`, `/sw-memory-sync`, `/sw-status` unchanged

### 2. Deprecated aliases + rename propagation (M)

- [x] 2.1 Deprecation shims for old commands (R4)
  - **File:** `core/commands/sw-compound.md`, `core/commands/sw-compound-ship.md`
  - **Expected:** thin shims route to `/sw-retrospective` (`compound-ship` → phase auto-detect; `compound` → write step), preserve behavior, print one-release deprecation notice
- [x] 2.2 Propagate the rename across routing/handoffs/fixtures (R5)
  - **File:** `.cursor/workflow.config.json`, `rules/sw-naming.mdc`, `skills/deliver/SKILL.md`, `skills/conductor/SKILL.md`, fixtures referencing `sw-compound`
  - **Expected:** no live top-level `sw-compound` reference remains (only deprecated aliases); routing points at `/sw-retrospective`

### 3. Autonomy knob + preserved semantics + conductor single-source (M)

- [x] 3.1 Add `compound.autonomy` config + schema + seeding (R10)
  - **File:** `.cursor/workflow.config.json`, `.sw/config.schema.json`, `core/sw-reference/` setup defaults
  - **Expected:** `compound.autonomy` (`supervised` | `auto`, default `supervised`) accepted by schema and seeded by `/sw-setup`
- [x] 3.2 Wire autonomy to prompts only; keep safety gates (R7, R8, R10)
  - **File:** `skills/compound/SKILL.md`, `core/commands/sw-retrospective.md`
  - **Expected:** `auto` removes approval / "did you merge?" prompts; memory writes stay fail-closed; rule-class promotion stays human-gated under all settings
- [x] 3.3 Preserve pending-merge + no-false-complete (R6, R11)
  - **File:** `skills/compound/SKILL.md`, `scripts/reconcile-status.py`
  - **Expected:** pre-merge records `completed-pending-merge`; INDEX → `complete` only on real merge detection, even under `auto`
- [x] 3.4 Conductor terminal-ship single-source handoff (R9)
  - **File:** `skills/conductor/SKILL.md`, `skills/deliver/SKILL.md`
  - **Expected:** terminal-ship handoff invokes `/sw-retrospective --pre-merge`; no duplicated retro/compound/memory/status procedure

### 4. Docs, dist, fixtures (M)

- [x] 4.1 Fixture suite for consolidation behaviors (R12)
  - **File:** `scripts/test/run-retrospective-fixtures.sh`, `.cursor/workflow.config.json`
  - **Expected:** fixtures named in the PRD Testing Strategy exist and pass; suite registered in `verify.test`
- [x] 4.2 Documentation updates (R12)
  - **File:** `skills/compound/SKILL.md`, `rules/sw-naming.mdc`, `docs/guides/` (workflow guide)
  - **Expected:** consolidated command + autonomy knob documented; presence asserted by a fixture
- [x] 4.3 Emitter propagation + freshness gate (R12)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** `dist/` regenerated; `scripts/test/run-emitter-fixtures.sh` passes

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |
| 4 | 1, 2, 3 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1 | retrospective-single-entry |
| R2 | 1.2 | retrospective-phase-dispatch |
| R3 | 1.3 | retrospective-atomics-internal |
| R4 | 2.1 | compound-alias-deprecation |
| R5 | 2.2 | compound-rename-propagation |
| R6 | 3.3 | retrospective-pending-merge |
| R7 | 3.2 | retrospective-memory-fail-closed |
| R8 | 3.2 | retrospective-rule-class-gated |
| R9 | 3.4 | retrospective-conductor-single-source |
| R10 | 3.1, 3.2 | compound-autonomy-knob |
| R11 | 3.3 | retrospective-no-false-complete |
| R12 | 4.1, 4.2, 4.3 | retrospective-emitter-freshness / retrospective-docs-presence |
