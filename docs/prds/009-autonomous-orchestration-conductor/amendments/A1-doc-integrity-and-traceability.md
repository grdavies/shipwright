---
date: 2026-06-25
amends: docs/prds/009-autonomous-orchestration-conductor/009-prd-autonomous-orchestration-conductor.md
frozen: true
frozen_at: 2026-06-25
---

# Amendment A1: Living-doc currency + brainstorm↔PRD frontmatter traceability

## Overview

Two documentation-integrity gaps surfaced while reconciling the PRD ledger during the 009 documentation
run, and both are in scope for the autonomous conductor because the conductor owns the bookkeeping step that
keeps these artifacts accurate:

1. **Stale living-doc status.** PRD 005 shipped via PR #61 and was appended to `COMPLETION-LOG.md`, but the
   post-merge reconcile commit (`#63`) mis-targeted and left `INDEX.md` showing `not-started`; separately,
   the five `GAP-BACKLOG.md` items absorbed by PRD 007 (PR #67) stayed marked `open`. Both required manual
   detection and correction. The conductor must keep `docs/prds/INDEX.md`, `docs/prds/COMPLETION-LOG.md`, and
   `docs/prds/GAP-BACKLOG.md` mechanically current and gate on drift, so a shipped PRD is never left
   `not-started` and an absorbed gap is never left `open`.
2. **No brainstorm↔PRD frontmatter link.** A Full-tier PRD derives from a brainstorm, but nothing in either
   document's frontmatter records the relationship; the linkage lives only in prose. This amendment adds a
   mandatory back-reference on the PRD (and a forward reference on a writable brainstorm) plus a fail-closed
   traceability gate.

This amendment continues the parent R-ID namespace (parent ends at R46) with **R47–R55**. It does not modify
the parent file and changes no parent requirement; it extends the conductor's bookkeeping scope (parent
R11/R12 bookkeeping, R36 documentation) and the documentation-pipeline frontmatter contract in
`.sw/layout.md`.

**Scope note (authorized boundary-crossing).** Theme 2 (R52–R55) modifies `/sw-prd` and `/sw-freeze`, which
the frozen parent fenced out under its Non-Goal "Changes to documentation-pipeline semantics … other than
orchestrator autonomy." This extension is deliberate and maintainer-authorized; see DL-A1-4. Theme 1
(R47–R51) stays squarely within the conductor's bookkeeping scope.

## Context

Parent PRD 009 already treats accurate terminal-PR documentation as a first-class concern (it builds on
PRD 007's task-checkbox currency gate (R15) and completion-on-merge-detection (R53)). The parent's
bookkeeping requirements (R11 "no halt for release bookkeeping", R12 consolidated reports) assume the
bookkeeping itself is correct; the 005/007 drift shows it is not enforced for the three living index files.
This amendment makes living-doc reconciliation a mechanical conductor step with a drift gate, mirroring the
007 task-currency hard-block, and adds the missing brainstorm↔PRD frontmatter traceability that the
documentation pipeline never captured. R49 changes `docs/prds/GAP-BACKLOG.md` from the "read-only /
hand-maintained" contract documented in `core/skills/living-status/SKILL.md` to a mechanically-reconciled
artifact; the `living-status` skill and `scripts/reconcile-status.sh` are in scope to gain that path (the
file remains hand-appendable for new gaps — only `open` → `resolved` reconciliation becomes mechanical). The brainstorm↔PRD linkage is a documentation-pipeline integrity
addition bundled here per maintainer direction; it is enforced by `/sw-prd` and `/sw-freeze` and a gate,
not by the conductor loop.

## Goals

1. **No stale ledger.** A shipped PRD's `INDEX.md` status reflects merge state automatically; an absorbed
   `GAP-BACKLOG.md` item is flipped to resolved automatically when its absorbing PRD completes.
2. **Drift is caught, not discovered.** A documentation-currency gate hard-blocks the terminal merge gate on
   any INDEX/COMPLETION-LOG/GAP-BACKLOG inconsistency, instead of relying on a human noticing months later.
3. **Traceable derivation.** Every Full-tier PRD carries a resolvable `brainstorm:` back-reference (and a
   forward `prd:` reference on a writable brainstorm), validated by a fail-closed gate.

## Non-Goals

- Changing any parent R1–R46 requirement or the parent's autonomy/parallelism behavior.
- Editing frozen brainstorms in place — a forward `prd:` reference is written only when the brainstorm is
  not yet frozen; the PRD back-reference is the authoritative link.
- Retroactively backfilling brainstorm references across all historical PRDs (the gate applies going
  forward; historical backfill is optional cleanup, not required here).
- Introducing a new living-doc beyond the three named index files.
- Blocking a run on pre-existing historical ledger drift in rows unrelated to the current PRD — the R50
  gate is scoped to the current run's rows; bulk historical reconciliation is opt-in cleanup, not a blocker.

## Requirements

- **R47** A reconcile primitive MUST set `docs/prds/INDEX.md` status mechanically from durable run/merge
  state (keyed on merge detection, consistent with PRD 007 R53), targeting the correct PRD row; the
  conductor MUST invoke it in the bookkeeping step so a shipped PRD is never left `not-started` (the observed
  005 drift) and a status flip never lands on the wrong row (the observed `#63` mis-target). The canonical
  status enum (`not-started` | `in-progress` | `complete`) MUST be single-sourced in
  `core/skills/living-status/SKILL.md` so the primitive and the INDEX file cannot drift on spelling.
- **R48** `docs/prds/COMPLETION-LOG.md` append MUST be a single idempotent primitive (date, PRD, phase, PR,
  SHA) invoked by the conductor; re-running it on resume MUST NOT double-append, and a shipped PRD MUST NOT
  be omitted from the log.
- **R49** `docs/prds/GAP-BACKLOG.md` entries MUST carry a structured status and, when resolved, the
  resolving PRD plus R-IDs; when an absorbing PRD reaches `complete`, a reconcile primitive MUST flip the
  matching `open` gaps to `resolved` with the PRD/PR reference (the observed 007 gap drift), and MUST leave
  non-matching gaps untouched.
- **R50** A documentation-currency gate MUST run before the terminal merge gate and MUST hard-block on drift
  in the rows the current run touches — the delivered PRD's `INDEX.md` status row, its `COMPLETION-LOG.md`
  entry, and the `GAP-BACKLOG.md` items its PRD absorbs — when those disagree with merge/COMPLETION-LOG
  state. On divergence it MUST block until reconciled (parity with the PRD 007 R15 task-currency hard-block),
  not warn-and-continue. It MUST NOT block a run on pre-existing historical drift in rows unrelated to the
  current PRD.
- **R51** Living-doc updates (INDEX status, COMPLETION-LOG append, GAP-BACKLOG resolution) MUST be committed
  onto the feature branch in-loop by the conductor so the terminal PR reflects accurate ledger state,
  consistent with PRD 007's pre-merge bookkeeping (PRD 007 R16/R18).
- **R52** Full-tier PRD frontmatter MUST carry a `brainstorm:` reference (repo-relative path) to its source
  brainstorm; `/sw-prd` MUST write it at draft time, and the path MUST resolve to an existing brainstorm.
- **R53** When the source brainstorm is not frozen, a forward `prd:` reference (repo-relative path; a list
  when multiple PRDs derive from one brainstorm) MUST be written to the brainstorm frontmatter when the
  derived PRD is created or frozen, making the linkage bidirectional; a frozen brainstorm is not edited and
  the PRD back-reference (R52) remains the authoritative link.
- **R54** A frontmatter-traceability gate MUST validate that `brainstorm:`/`prd:` cross-references resolve to
  existing files and MUST fail closed on a dangling or missing reference for a Full-tier PRD; it MUST be
  wired into the documentation/test gate, and `.sw/layout.md` frontmatter contracts MUST document the new
  fields.
- **R55** `/sw-freeze` MUST verify the PRD↔brainstorm linkage (R52 present and resolvable) before stamping a
  Full-tier PRD `frozen: true`, so the back-reference cannot be omitted at freeze time.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `index-status-reconcile-from-merge` | INDEX status set from merge state; correct row; shipped PRD never `not-started` | R47 |
| `completion-log-idempotent-append` | append is idempotent on resume; no double-append; no omission | R48 |
| `gap-backlog-resolve-on-absorb` | absorbing-PRD completion flips matching `open` gaps to resolved; others untouched | R49 |
| `docs-currency-gate-block` | INDEX/COMPLETION-LOG/GAP-BACKLOG drift hard-blocks the terminal gate | R50 |
| `living-docs-committed-in-loop` | the three ledger updates are committed on the feature branch pre-merge | R51 |
| `prd-brainstorm-backref-written` | `/sw-prd` writes a resolvable `brainstorm:` back-reference on a Full-tier PRD | R52 |
| `brainstorm-prd-forwardref-written` | a writable brainstorm gets a forward `prd:` reference; frozen brainstorm untouched | R53 |
| `doc-link-traceability-gate` | dangling/missing brainstorm↔PRD reference fails closed; layout documents fields | R54 |
| `freeze-verifies-doc-linkage` | `/sw-freeze` blocks a Full-tier PRD freeze without a resolvable back-reference | R55 |

Emitter propagation of the new `core/` scripts/commands/rules to `dist/` is covered by parent R5; these
fixtures extend the existing doc/deliver/state suites invoked by `verify.test`.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-A1-1 | Living-doc reconciliation (INDEX/COMPLETION-LOG/GAP-BACKLOG) is a mechanical conductor step with a hard-block drift gate | The 005 stale-`not-started` row and the 007 still-`open` absorbed gaps both required manual detection; prose-driven reconcile mis-targets (`#63` flipped 004, not 005). Mechanical + gated, mirroring the 007 task-currency hard-block (R47–R51). |
| DL-A1-2 | Brainstorm↔PRD linkage is a mandatory PRD back-reference plus a best-effort forward reference, not a bidirectional edit of frozen brainstorms | Frozen artifacts must not be edited; the PRD `brainstorm:` field is authoritative, the brainstorm `prd:` forward pointer is written only when writable (R52, R53). |
| DL-A1-3 | The frontmatter link is enforced at author time (`/sw-prd`), freeze time (`/sw-freeze`), and by a fail-closed gate | Single enforcement point is bypassable; three layers match the freeze/spec-rigor defense-in-depth already used in the pipeline (R54, R55). |
| DL-A1-4 | **Authorized boundary-crossing:** R52–R55 knowingly extend beyond the frozen parent Non-Goal "Changes to documentation-pipeline semantics (`/sw-brainstorm` → `/sw-prd` → `/sw-tasks`) other than orchestrator autonomy." | The scope-guardian panel flagged that theme 2 modifies `/sw-prd` and `/sw-freeze`, which the parent fenced out. The maintainer explicitly authorized co-delivery in 009 (chose "authorize" over split/phase-only) because the conductor's bookkeeping integrity and the pipeline's frontmatter integrity share the "documentation stays accurate" goal and are being hardened in one pass. This decision is the human-owned authorization the boundary-crossing requires; it does not alter any parent R1–R46. |

## Open Questions

None.
