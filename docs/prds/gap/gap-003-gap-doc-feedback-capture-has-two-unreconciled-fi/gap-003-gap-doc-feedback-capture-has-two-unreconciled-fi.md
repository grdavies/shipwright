---
id: gap-003-gap-doc-feedback-capture-has-two-unreconciled-fi
type: gap
status: open
title: Gap/doc-feedback capture has two unreconciled file paths and bypasses the planning_store backend interface
visibility: public
tags: [source:feedback, signal:feedback-gap-store-duplication-2026-06-30]
---

# Gap/doc-feedback capture has two unreconciled file paths and bypasses the planning_store backend interface

_Captured from feedback signal `feedback-gap-store-duplication-2026-06-30`._

## Evidence (validated in code)

Two gap-storage mechanisms coexist with **zero cross-reference**: `docs/prds/GAP-BACKLOG.md` (76
hand-maintained rows) and `docs/prds/gap/<unit-id>/` (canonical units; only `gap-001` existed before this
signal, and it has no corresponding `GAP-BACKLOG.md` row at all — confirmed by direct search). The
`living-status` skill says canonical gaps live under the gap-unit directory and `GAP-BACKLOG.md` should be a
generated, **read-only, frontmatter-only projection** during cutover. But `feedback/SKILL.md` Phase 3 still
instructs `/sw-feedback` to **hand-append a literal markdown row directly to `GAP-BACKLOG.md`** — the two
skill documents contradict each other, and the actual `GAP-BACKLOG.md` content (full prose rows, not
frontmatter stubs) matches the contradicting instruction, not the documented design.

The canonical mechanism itself bypasses the backend abstraction meant to make it portable. `planning_store.py`
already defines `put`/`get`/`exists`/`materialize` (PRD 034), and PRD 043 R33 plans to extend it with an
`issue-store` backend. But `planning_gap_capture.py` never calls it:

```70:73:scripts/planning_gap_capture.py
    if not dry_run:
        unit_dir.mkdir(parents=True, exist_ok=True)
        body_path.write_text(content, encoding="utf-8")
```

## Lineage

A same-day investigation (prior session, learning: "Memory Backend Functionality") independently reached the
same root conclusion from the PRD/task/brainstorm-authoring side: `/sw-prd`, `/sw-tasks`, and `/sw-brainstorm`
write markdown directly and never call `planning_store.put`, so "the MAJORITY of planning assets are not in
the store at all," and concluded **a new PRD was needed** to route authoring through the store. PRD 043 (now
in flight) is that PRD. This gap is the gap-capture-specific instance of the same architectural hole, checked
against the concrete dependent PRDs (044–047) that exist now.

## Why this isn't closed by PRDs 043–047

All five PRDs in the issue-backed-planning-store program were checked directly:

- **PRD 043** Non-Goals: file pipeline is "the default and only behavior when issue-store is unconfigured."
- **PRD 045** R21/R72/Technical-Requirements route gap-capture through `planning_store` + native issues —
  **but only when issue-store is active**; Non-Goals explicitly excludes "changing file-store behavior when
  `backend != issue-store`."
- **PRD 046** Non-Goals: "changing the file-store planning-graph behavior... when issue-store is inactive."
- **PRD 044 / 047**: migration tooling and Jira adapter respectively — not a fit for the standing default
  mechanism.

So after the whole program ships, a default (file-backend) install still has two unreconciled gap-storage
code paths, neither routed through `planning_store` — the exact problem PRD 043's own R33 interface exists to
prevent for any *other* future backend.

## Suggested remediation

1. Route `planning_gap_capture.py` (and the `/sw-feedback` Phase 3 "trivial gap" path) through
   `planning_store.put()` for **every** backend, including `memory`/`in-repo-public` — not only `issue-store`.
2. Reconcile `feedback/SKILL.md` Phase 3 with `living-status/SKILL.md`'s documented "frontmatter-only
   generated projection" contract for `GAP-BACKLOG.md`, or update whichever description is wrong.
3. Backfill/reconcile the existing drift: `gap-001` (and now `gap-002`/`gap-003`) have no `GAP-BACKLOG.md`
   counterpart; decide one authoritative direction before issue-store cutover compounds the divergence.
4. Land this **before** PRD 044's migration tooling and PRD 045's issue-native gap lifecycle, so migration
   has one well-defined file-side source to migrate from, not two.

