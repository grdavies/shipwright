---
date: 2026-06-24
amends: docs/prds/005-native-local-review-panel/005-prd-native-local-review-panel.md
frozen: true
frozen_at: 2026-06-24
---

# Amendment A1: `doc.afterTasks` dispatches `/sw-deliver run`

## Overview

PRD 004 establishes `/sw-deliver run <frozen-task-list>` as the primary implementation entry point after
documentation freeze. The `/sw-doc` orchestrator's `doc.afterTasks` boundary still documents the legacy manual
chain (`/sw-worktree` → `/sw-start` → `/sw-execute` or `/sw-ship`), while user guides already document
`/sw-deliver run` as the post-freeze path. This amendment pins the doc→implementation handoff to
`/sw-deliver run` so PRD 005 dogfood (parent R67: native panel inside deliver-dispatched phase `/sw-ship`)
enters through the phase orchestrator. It does **not** change `/sw-deliver` behavior (PRD 004 scope).

## Context

The parent PRD's non-goals correctly exclude *changing* `/sw-deliver`, but wiring `doc.afterTasks` to invoke
`/sw-deliver run` is required for PRD 005 implementation to exercise the R67 phase-mode integration path
when documentation is completed via `/sw-doc`. PRD 004 noted this integration point but deferred the
`/sw-doc` wiring; this amendment closes that gap for PRD 005 without modifying PRD 004 requirements.

## Goals

1. **Single play button** — after frozen tasks, `confirm` and `auto` dispatch `/sw-deliver run <frozen-tasks>`,
   not a hand-rolled worktree + execute/ship chain.
2. **Accurate stop guidance** — `stop` mode prints `/sw-deliver run <path>` as the expected next command.
3. **Doc alignment** — `sw-doc.md`, naming rule, and user guides agree on the post-freeze entry command.

## Non-Goals

- Changing `/sw-deliver` behavior (PRD 004 scope).
- Changing `doc.afterTasks` mode semantics (`stop` | `confirm` | `auto`) or the human ack contract for
  `confirm`.
- Auto-dispatch wiring for decision records (no task lists).

## Requirements

- **R76** The `/sw-doc` `doc.afterTasks` boundary MUST use `/sw-deliver run <frozen-task-list-path>` as the
  sole implementation dispatch entry on `confirm` and `auto`: after human ack (`proceed` / `yes`) or on
  `auto`, the orchestrator MUST invoke `/sw-deliver run` with the frozen task-list path — it MUST NOT dispatch
  `/sw-worktree` → `/sw-start` → `/sw-execute` or a standalone `/sw-ship` as the primary implementation loop.
- **R77** On `doc.afterTasks: stop`, the orchestrator MUST print the frozen task-list path and the exact next
  command `/sw-deliver run <frozen-task-list-path>`; it MUST NOT recommend the legacy manual chain as the
  primary path.
- **R78** `core/commands/sw-doc.md`, `rules/sw-naming.mdc` (if `/sw-doc` boundary prose is present),
  `docs/guides/configuration.md`, and `docs/guides/getting-started.md` MUST document `/sw-deliver run` as the
  `confirm` and `auto` dispatch target and the `stop`-mode next command per R76/R77.
- **R79** When an agent (not a human) invokes `/sw-doc --after-tasks=auto`, the orchestrator MUST record the
  override in the per-worktree run record via `scripts/shipwright-state.sh` (who / when / mode) before
  dispatching `/sw-deliver run`, and MUST NOT inline implementation files in any `doc.afterTasks` mode.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `doc-afterTasks-stop-deliver` | `sw-doc.md` stop branch prints `/sw-deliver run` with frozen task-list path | R77, R78 |
| `doc-afterTasks-confirm-deliver` | `sw-doc.md` confirm dispatch invokes `/sw-deliver run`, not legacy worktree→execute chain | R76, R78 |
| `doc-afterTasks-auto-deliver` | `sw-doc.md` auto dispatch invokes `/sw-deliver run`; agent override recorded before dispatch | R76, R79 |
| `doc-afterTasks-guides-deliver` | `docs/guides/configuration.md` and `getting-started.md` name `/sw-deliver run` for stop/confirm/auto | R78 |

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-33 (PRD 005) | `doc.afterTasks` confirm/auto → `/sw-deliver run <frozen-tasks>`; stop prints same as next command | Closes PRD 004's deferred `/sw-doc` integration note for PRD 005 dogfood (R67). Aligns command docs with `docs/guides/workflows.md` and `docs/guides/configuration.md`. Does not change `/sw-deliver`. |

## Open Questions

None.
