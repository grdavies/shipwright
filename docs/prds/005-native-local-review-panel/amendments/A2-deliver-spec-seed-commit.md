---
date: 2026-06-24
amends: docs/prds/005-native-local-review-panel/005-prd-native-local-review-panel.md
frozen: true
frozen_at: 2026-06-24
---

# Amendment A2: `doc.afterTasks` seeds the frozen spec onto `<type>/<slug>` before `/sw-deliver run`

## Overview

Amendment A1 wired the `/sw-doc` `doc.afterTasks` boundary to dispatch `/sw-deliver run <frozen-task-list-path>`
as the post-freeze implementation entry. It left a structural gap: when `/sw-tasks` freezes the PRD and task
list, those artifacts are written into the working tree but are **not committed**. `/sw-deliver run` provisions
phase worktrees with `git worktree add`, which materializes only the **committed** tracked files of the
resolved `<type>/<slug>` branch — uncommitted working-tree edits never propagate into a freshly added worktree.
So a dispatched phase cannot see its own PRD/task list, and the spec is absent from the terminal
`<type>/<slug>` → `main` PR diff. This amendment closes that gap by making the boundary commit the frozen,
tracked `docs/prds/<n>-<slug>/` set onto `<type>/<slug>` before it dispatches. It does **not** change
`/sw-deliver` (PRD 004 scope) — that remains the parent's non-goal.

## Context

The fix belongs to `/sw-doc` orchestration, which A1 already owns, not to `/sw-deliver`. Two owners were
considered for seeding the spec commit: **Owner A** — `/sw-deliver run` self-seeds the commit at entry (covers
the manual `/sw-deliver run` invocation path too, but edits `/sw-deliver` = PRD 004 scope); **Owner B** — the
`doc.afterTasks` boundary commits the frozen docs onto `<type>/<slug>` before dispatch (stays inside `/sw-doc`,
composes with A1, respects the parent non-goal). This amendment pins **Owner B** for PRD 005; Owner A is left as
a PRD 004 follow-up for hardening the manual-invocation path and is not mandated here.

## Goals

1. **Spec is visible to phases** — every `/sw-deliver`-provisioned worktree contains the frozen PRD and task
   list, because they are committed on `<type>/<slug>` before provisioning.
2. **Spec lands in the terminal diff** — the frozen `docs/prds/<n>-<slug>/` set appears in the
   `<type>/<slug>` → `main` PR, committed on the feature branch rather than on `main`.
3. **Hands-off `auto` / `confirm`** — the seed commit is automatic and idempotent, so no manual `git` step is
   required before `/sw-deliver run` in `auto` or `confirm` mode.

## Non-Goals

- Changing `/sw-deliver` behavior (PRD 004 scope) — including who seeds the spec for a **manual**
  `/sw-deliver run` invocation (Owner A is a PRD 004 follow-up).
- Changing the `stop` | `confirm` | `auto` mode contract (which mode dispatches, the human-ack requirement
  for `confirm`, or A1 R76–R79). `stop` stays print-only (no repository mutation, per R82); the seed commit is
  added only to the `confirm` / `auto` dispatch path A1 already defined.
- Committing brainstorm artifacts or any untracked/ignored files.
- Auto-merging the feature branch or bypassing `/sw-ship` / the human merge gate.

## Requirements

- **R80** The `/sw-doc` `doc.afterTasks` boundary MUST commit the frozen documentation set for the feature —
  the tracked `docs/prds/<n>-<slug>/` directory (PRD, frozen task list, and any frozen amendments) — onto the
  resolved feature branch `<type>/<slug>` BEFORE dispatching `/sw-deliver run <frozen-task-list-path>` on
  `confirm` and `auto`. The structural reason: `/sw-deliver run` provisions phase worktrees via
  `git worktree add`, which materializes only committed tracked files of `<type>/<slug>`, so an uncommitted
  frozen spec is invisible to every provisioned worktree and absent from the terminal PR diff. The commit MUST
  be docs-only (no implementation files) and idempotent (a no-op when the frozen artifacts are already
  committed on the branch).
- **R81** The feature branch `<type>/<slug>` that `/sw-doc` commits onto MUST resolve to the identical branch
  name `/sw-deliver run` later resolves for the same frozen task list (type from the PRD/triage tier, slug from
  the PRD directory slug) — same inputs MUST yield the same branch name. The derivation rule MUST be
  single-sourced, not independently re-implemented inside `/sw-doc`; if no shared resolver callable yet exists
  outside `/sw-deliver`'s own machinery, extracting one is a PRD 004 follow-up and MUST NOT be satisfied by
  forking a divergent copy in `/sw-doc`. This amendment changes only `/sw-doc` orchestration and MUST NOT modify
  `/sw-deliver` behavior; it relies on `/sw-deliver run` resolving and adopting an existing `<type>/<slug>`
  (rather than requiring a fresh branch). That adoption guarantee is an assumed `/sw-deliver` behavior — if
  `/sw-deliver` does not already adopt a pre-existing branch, closing that gap is a PRD 004 concern and is out
  of scope here.
- **R82** On `doc.afterTasks: stop`, `/sw-doc` MUST remain print-only (no repository mutation, preserving A1
  R77 semantics): it MUST print both the exact docs-only commit command that places the frozen
  `docs/prds/<n>-<slug>/` set onto `<type>/<slug>` (naming that branch) AND the A1 R77 next command
  `/sw-deliver run <frozen-task-list-path>`. The printed guidance MUST direct the commit onto `<type>/<slug>`
  and MUST NOT direct the frozen spec onto the default branch (`main`), because committing it to `main` drops
  the spec from the `<type>/<slug>` → `main` PR diff. The automatic seed commit (R80) applies to `confirm` and
  `auto` only; `stop` never mutates the repository.
- **R83** The R80 seed commit MUST exclude `docs/brainstorms/**` (which remains gitignored) and any other
  untracked or ignored path; only the frozen, tracked `docs/prds/<n>-<slug>/` artifacts are committed. As parity
  with A1 R79, when an agent (not a human) invokes `/sw-doc --after-tasks=auto`, the per-worktree run record
  written via `scripts/shipwright-state.sh` MUST also record the seed commit (branch plus commit SHA) before
  `/sw-deliver run` is invoked.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `doc-afterTasks-seed-confirm-auto` | `sw-doc.md` confirm/auto branch commits the docs-only `docs/prds/<n>-<slug>/` set onto `<type>/<slug>` before invoking `/sw-deliver run` | R80, R81 |
| `doc-afterTasks-seed-stop` | `sw-doc.md` stop branch is print-only and prints both the docs-only commit command onto `<type>/<slug>` and `/sw-deliver run`, naming the branch and never directing the spec onto `main` | R82 |
| `doc-afterTasks-seed-branch-derivation` | `sw-doc.md` derives `<type>/<slug>` via the shared `/sw-deliver` resolver, not a divergent re-implementation | R81 |
| `doc-afterTasks-seed-brainstorm-excluded` | `sw-doc.md` seed step excludes `docs/brainstorms/**` and records the seed commit (branch + SHA) via `shipwright-state.sh` for agent-triggered dispatch | R83 |

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-34 (PRD 005) | `doc.afterTasks` seeds a docs-only commit of the frozen `docs/prds/<n>-<slug>/` set onto `<type>/<slug>` before dispatching `/sw-deliver run` on `confirm` / `auto` (Owner B — boundary-owned commit); `stop` stays print-only and emits the commit + dispatch commands. | `git worktree add` materializes only committed tracked files, so an uncommitted frozen spec is invisible to provisioned phase worktrees and missing from the terminal PR diff; committing on the feature branch (not `main`) keeps the spec in the `<type>/<slug>` → `main` diff. Owner B keeps the fix inside `/sw-doc` scope and composes with A1, honoring the parent non-goal "Changing `/sw-deliver` (PRD 004)". Branch-name derivation is reuse-not-modify: if `/sw-deliver`'s resolver is not yet a shared callable, extracting one (and any `/sw-deliver` adopt-existing-branch guarantee) is a PRD 004 follow-up — the complementary Owner A (`/sw-deliver run` self-seeding for the manual-invocation path) is likewise deferred to PRD 004, not mandated here. |

## Open Questions

None.
