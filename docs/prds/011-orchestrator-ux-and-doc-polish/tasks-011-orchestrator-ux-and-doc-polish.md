---
date: 2026-06-25
topic: orchestrator-ux-and-doc-polish
prd: docs/prds/011-orchestrator-ux-and-doc-polish/011-prd-orchestrator-ux-and-doc-polish.md
frozen: true
frozen_at: 2026-06-25
---

# Tasks — PRD 011 Orchestrator UX and documentation polish

Generated from the frozen PRD `011-prd-orchestrator-ux-and-doc-polish.md` (effective union R1–R16).
Phases are dependency-ordered; the doc/command edits are independent, and the final phase wires fixtures,
guides, and the emitter.

## Tasks

### 1. `/sw-doc` post-freeze command surface + confirm prominence (S/M)

- [ ] 1.1 Replace primary post-freeze command with `/sw-deliver run` across all modes (R1, R3)
  - **File:** `core/commands/sw-doc.md`
  - **Expected:** `stop` prints `/sw-deliver run <frozen-task-list-path>`; `confirm`/`auto` dispatch the same; no raw `bash scripts/wave.sh deliver-loop` remains as the *primary* next/dispatch command (allowed only as a documented "underlying driver" note)
- [ ] 1.2 Retain idempotent docs-only spec-seed on the boundary (R2)
  - **File:** `core/commands/sw-doc.md`
  - **Expected:** `bash scripts/wave.sh spec-seed --task-list <path>` printed on `stop` and executed before dispatch on `confirm`/`auto`; docs-only, onto `<type>/<slug>` never `main`, idempotent, excludes `docs/brainstorms/**`
- [ ] 1.3 Dedicated, prominent `confirm` checkpoint block (R5, R7)
  - **File:** `core/commands/sw-doc.md`
  - **Expected:** confirm output has its own heading, a direct yes/proceed question, and a paused-state line; ack grammar table (only `proceed`/`yes` continues) left unchanged
- [ ] 1.4 Re-emit checkpoint on un-acked return (R6)
  - **File:** `core/commands/sw-doc.md`
  - **Expected:** an unrelated message while a `confirm` halt is pending maps to `stop` (no dispatch) and re-emits the checkpoint block

### 2. `/sw-cleanup` agent-driven confirm (S)

- [ ] 2.1 Agent consent prompt → agent runs apply on ack (R8, R10)
  - **File:** `core/commands/sw-cleanup.md`
  - **Expected:** procedure step replaces "run `python3 scripts/cleanup.py --confirm --yes` yourself" with an agent prompt; on explicit ack the agent runs `python3 scripts/cleanup.py --confirm --yes` (or `SW_CLEANUP_CONFIRM=1`); declined/silent/ambiguous → no apply; manual command kept as documented escape hatch
- [ ] 2.2 Preserve fail-closed protections verbatim (R9)
  - **File:** `core/commands/sw-cleanup.md`
  - **Expected:** protections section (current/default/unmerged branch, active/locked worktrees, in-flight deliver run, indeterminate squash, no `rm -rf`) unchanged; apply deletes only the reviewed `wouldRemove` set; no change to `scripts/cleanup.py`

### 3. Optional repo link-check script + wiring (M)

- [ ] 3.1 Add `scripts/docs-link-check.py` (R11, R13)
  - **File:** `scripts/docs-link-check.py`
  - **Expected:** parses repo-relative markdown links + intra-doc anchors across `README.md` and `docs/guides/**` (optionally `docs/prds/**`); emits JSON `{"verdict":"pass|broken-links","findings":[...]}`; skips `http`/`https`; no network access
- [ ] 3.2 Advisory-by-default with `--strict` opt-in + harness wiring (R12)
  - **File:** `scripts/docs-link-check.py`, `.cursor/workflow.config.json`
  - **Expected:** default exit 0 with logged findings; `--strict` exits 20 on broken links; wired into `verify.test`/doctor in advisory mode

### 4. Fixtures, guides, dist propagation (M)

- [ ] 4.1 Fixture suite for all new behaviors (R15)
  - **File:** `scripts/test/run-ux-polish-fixtures.sh`, `.cursor/workflow.config.json`
  - **Expected:** fixtures named in the PRD Testing Strategy table exist and pass; suite registered in `verify.test`
- [ ] 4.2 Update user guides to the new surfaces (R16)
  - **File:** `docs/guides/getting-started.md`, `docs/guides/configuration.md`, `docs/guides/workflows.md`
  - **Expected:** guides name `/sw-deliver run` as the post-freeze command, describe the prominent confirm checkpoint, and the agent-driven `/sw-cleanup` confirm
- [ ] 4.3 Emitter propagation + freshness gate (R14)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** `dist/` regenerated; `scripts/test/run-emitter-fixtures.sh` passes

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |
| 3 | none |
| 4 | 1, 2, 3 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1 | doc-afterTasks-stop-deliver-run |
| R2 | 1.2 | doc-afterTasks-confirm-auto-deliver-run |
| R3 | 1.1 | doc-afterTasks-stop-deliver-run |
| R4 | 1.1 | doc-afterTasks-deliver-run-fixtures-pass |
| R5 | 1.3 | confirm-checkpoint-prominent |
| R6 | 1.4 | confirm-reemit-on-unacked-return |
| R7 | 1.3 | confirm-ack-grammar-unchanged |
| R8 | 2.1 | cleanup-agent-confirm-flow |
| R9 | 2.2 | cleanup-protections-preserved |
| R10 | 2.1 | cleanup-agent-confirm-flow |
| R11 | 3.1 | docs-link-check-pass |
| R12 | 3.2 | docs-link-check-advisory-default |
| R13 | 3.1 | docs-link-check-offline |
| R14 | 4.3 | ux-polish-emitter-freshness |
| R15 | 4.1 | run-ux-polish-fixtures.sh (full suite) |
| R16 | 4.2 | ux-polish-guides-aligned |
