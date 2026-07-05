---
superseded-by: PRD 055
date: 2026-06-30
amends: docs/prds/045-issue-native-dev-tracking/045-prd-issue-native-dev-tracking.md
absorbs: [gap-003-gap-doc-feedback-capture-has-two-unreconciled-fi]
frozen: true
frozen_at: 2026-06-30
visibility: public
---

# Amendment A1: Unify gap-capture behind `planning_store` for every backend, not only `issue-store`

## Overview

`/sw-feedback` validated (2026-06-30) that gap/doc-feedback capture has **two unreconciled mechanisms** with
zero cross-reference today: `docs/prds/GAP-BACKLOG.md` (76 hand-maintained rows, actively used) and
`docs/prds/gap/<unit-id>/` (canonical units; the lone pre-existing unit, `gap-001`, has no `GAP-BACKLOG.md`
counterpart at all). Neither mechanism routes through the `planning_store.py` `put`/`get`/`exists` interface
that PRD 034 defined and that this program's PRD 043 (R33) extends with an `issue-store` backend:
`scripts/planning_gap_capture.py` writes raw files directly. Full evidence is recorded in the canonical gap
unit `docs/prds/gap/gap-003-gap-doc-feedback-capture-has-two-unreconciled-fi/`.

This PRD already plans to touch `scripts/planning_gap_capture.py` and the gap lifecycle (R21/R72,
Technical Requirements: "Gap issues... route through `planning_store`"), but **only when issue-store is
active** — the parent's Non-Goals explicitly exclude "changing file-store behavior when `backend !=
issue-store`." That leaves the default (file-backend) install with the exact duplication this signal
reports, permanently, even after the whole issue-backed-planning-store program ships. This amendment closes
that gap by requiring gap-capture route through `planning_store` for **every** configured backend — file
included — before the issue-store-specific behavior (R21/R72) is layered on top of the same interface. It
continues the parent R-ID namespace into the reserved **R75–R79** band and does not modify the parent file.

## Context

PRD 043's own R33 exists precisely to make artifact storage backend-agnostic; gap-capture should be the
first, smallest proof that the interface actually decouples "what gets created" from "where it's stored" —
instead, today it's a third, independent bypass of that interface, on top of the GAP-BACKLOG.md/gap-unit
split. A same-day, independent investigation (prior to this signal) reached the parallel conclusion that PRD
authoring commands (`/sw-prd`, `/sw-tasks`, `/sw-brainstorm`) also bypass `planning_store.put` entirely — this
amendment does not attempt to fix that broader authoring-path gap (out of scope for PRD 045, whose program
role is dev-tracking, not core artifact storage), but explicitly notes it as a related, larger open item the
operator should track separately, likely against PRD 043 itself or a follow-on.

## Goals

1. `scripts/planning_gap_capture.py` calls `planning_store.put()` for the gap-unit body on every backend
   (`in-repo-public`, `local-synced`, `memory`, and — once R21 lands — `issue-store`), never a direct
   `Path.write_text()`.
2. `/sw-feedback` Phase 3's "trivial in-scope gap" path stops instructing a hand-appended
   `docs/prds/GAP-BACKLOG.md` row as the default mechanism; it routes through the same `planning_gap_capture.py`
   → `planning_store` path used everywhere else, regardless of backend.
3. `docs/prds/GAP-BACKLOG.md`'s actual behavior matches one documented description, not two contradicting
   ones (`feedback/SKILL.md` Phase 3 vs. `living-status/SKILL.md`'s "frontmatter-only generated projection").
4. Existing drift (`gap-001`, and the `gap-002`/`gap-003` captured by this signal, all missing
   `GAP-BACKLOG.md` counterparts) is reconciled in one direction before issue-store cutover compounds it
   further.

## Non-Goals

- Fixing the broader PRD/task/brainstorm authoring-path bypass of `planning_store` (separate, larger item;
  flagged above for independent tracking, not owned by PRD 045's dev-tracking scope).
- Any other R21/R72/R67–R74 behavior (native gap issues, safe close-on-merge, comment doc-review,
  milestones) — unchanged.
- Migrating existing file-native gaps into issues — owned by PRD 044, unaffected by this amendment.

## Requirements

- **R75** — `scripts/planning_gap_capture.py` MUST write the gap-unit body via `planning_store.put()`
  (resolving the active `planning.store.backend`), for every backend value, not only `issue-store`. The
  current direct-file-write path is replaced, not duplicated behind a backend conditional.
- **R76** — `/sw-feedback` Phase 3's "trivial in-scope gap" route MUST call the same `planning_gap_capture.py`
  entrypoint used elsewhere (capturing a canonical gap unit through `planning_store`) instead of instructing
  a hand-appended `docs/prds/GAP-BACKLOG.md` table row, independent of the active backend. R72's write-through
  `GAP-BACKLOG.md` projection (issue-store-active case) and this requirement's file-backend case share the
  same upstream capture call; they differ only in which backend `planning_store` resolves to.
- **R77** — `core/skills/feedback/SKILL.md` Phase 3 and `core/skills/living-status/SKILL.md`'s
  `GAP-BACKLOG.md` description are reconciled to state one consistent contract (generated/write-through
  projection, never hand-appended) for every backend — not only the issue-store-active case R72 already
  documents.
- **R78** — A one-time reconciliation pass cross-links or backfills the pre-existing drift between
  `docs/prds/GAP-BACKLOG.md` rows and `docs/prds/gap/<unit-id>/` units that predate R75–R77 (at minimum:
  `gap-001`, `gap-002`, `gap-003`), so the file-backend gap store has a single authoritative direction before
  PRD 044's migration tooling or PRD 045's R21 native-issue cutover need to read from it.
- **R79** — The broader authoring-path gap (PRD/task/brainstorm commands bypassing `planning_store.put`) is
  explicitly out of scope for this amendment; it is recorded here only as a flagged dependency for separate
  tracking (e.g. against PRD 043 or a follow-on), so it is not silently dropped.

## Technical Requirements

- **TR-A1-1** (R75) Replace `planning_gap_capture.py:capture_gap`'s direct `mkdir`/`write_text` with a
  `planning_store.get_backend(root).put(unit_id, body_path, content, content_class="gap")` call; preserve the
  existing frontmatter/body shape so `gap-001`-style units remain byte-compatible under the default
  (`in-repo-public`/`memory`) backends.
- **TR-A1-2** (R76) Update `core/skills/feedback/SKILL.md` Phase 3's "Trivial in-scope" row and the gap
  backlog entry-format section to invoke `planning_gap_capture.py capture` rather than a literal markdown
  append example.
- **TR-A1-3** (R77) Edit `core/skills/living-status/SKILL.md` and `core/skills/feedback/SKILL.md` so both
  describe the same `GAP-BACKLOG.md` contract; extend R72's write-through/doctor language to apply when
  `backend == memory`/`in-repo-public` too, not only `issue-store`.
- **TR-A1-4** (R78) A one-shot reconciliation script (or documented manual pass) appends/links the missing
  `GAP-BACKLOG.md` rows for pre-existing orphan gap units, or vice versa, per whichever direction R77
  settles on as authoritative.

## Testing Strategy

| Fixture | Behavior |
|---------|----------|
| `gap-capture-routes-through-planning-store` | `planning_gap_capture.py capture` on each shipped backend (`in-repo-public`, `local-synced`, `memory`) calls `planning_store.put`, never a direct file write |
| `feedback-trivial-gap-no-hand-append` | `/sw-feedback` Phase 3 trivial-gap routing produces a canonical gap unit via `planning_gap_capture.py`, not a literal `GAP-BACKLOG.md` row edit |
| `gap-backlog-skill-docs-consistent` | `feedback/SKILL.md` and `living-status/SKILL.md` describe the same `GAP-BACKLOG.md` contract (doc-consistency fixture, not just code) |
| `gap-unit-backlog-reconciled` | Pre-existing orphan gap units (`gap-001`–`gap-003`) have a resolved, non-contradictory backlog relationship after the reconciliation pass |

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-A1-1 | Gap-capture routes through `planning_store` for every backend, not only `issue-store` | The parent's own Non-Goal would otherwise leave the default install's duplication permanently unfixed even after the full program ships |
| DL-A1-2 | The broader authoring-path (`planning_store.put`) gap is flagged, not fixed, here | Out of PRD 045's dev-tracking scope; avoids silent scope creep while still surfacing the dependency for the operator |
| DL-A1-3 | Existing orphan gap units get a one-time reconciliation pass rather than being left as permanent drift | Avoids compounding the inconsistency further once PRD 044 migration and PRD 045 R21 native-issue cutover start reading from the file-backend gap store |

## Open Questions

None blocking. Resolved during `/sw-tasks`: which direction (`GAP-BACKLOG.md` rows generated from gap units,
or gap units backfilled from `GAP-BACKLOG.md` rows) is authoritative for the R78 reconciliation pass.
