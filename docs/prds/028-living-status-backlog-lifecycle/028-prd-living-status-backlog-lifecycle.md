---
brainstorm: docs/brainstorms/2026-06-27-living-status-backlog-lifecycle-requirements.md
date: 2026-06-27
topic: living-status-backlog-lifecycle
absorbs: [GAP-043, GAP-044, GAP-046]
frozen: true
frozen_at: 2026-06-27
---
# PRD 028 — Living-status backlog lifecycle mechanization

## Overview

`docs/prds/GAP-BACKLOG.md` is the living register of committed in-scope gaps, with a status lifecycle of
`open → planned → resolved`. Today that lifecycle is mostly manual, and each manual transition has silently
misrepresented backlog state this session. The upstream transition (`open → planned`, when a PRD or amendment
absorbs a gap) has no mechanism at all — GAP-039/GAP-040 were absorbed into PRD 024 A2 yet stayed `open`
until corrected by hand. The downstream transition (`planned → resolved`, when the absorbing PRD ships) is
only half-mechanized: PRD 009 R49 `reconcile-status.py gap-resolve` flips a row only when its status is
exactly `open` with a matching absorbed-by reference, so every `planned — PRD N` row is invisible to it
(confirmed stale on GAP-009/014/018–020/024). Stable IDs were added (ID column + index, GAP-044) but the
append protocol and index↔table integrity remain an unenforced manual contract.

This PRD mechanizes the full `open → planned → resolved` lifecycle end-to-end behind one shared writer,
single-sources the status enum, introduces a machine-readable `absorbs:` frontmatter linkage as the single
source of truth, adds fail-closed currency checks for both transitions, and adds an index↔table integrity
guard. It **extends** the existing PRD 009 R49/R50 machinery (`reconcile-status.py gap-resolve`,
`docs-currency-gate.py`, `living-status/SKILL.md`) rather than introducing a competing mechanism, and absorbs
GAP-043, GAP-044, and GAP-046.

## Goals

- Make the `open → planned` transition fire automatically when a frozen PRD or amendment declares the gaps it
  absorbs, so no absorbed gap silently stays `open`.
- Make the `planned → resolved` transition fire automatically when the absorbing PRD reaches `complete`, so
  no shipped gap silently stays `planned`.
- Replace prose-scraped linkage with a machine-readable `absorbs:` frontmatter contract that the same writer
  consumes at both freeze and ship.
- Enforce backlog integrity (single ID occurrence, index↔table agreement, accurate counts) and document the
  stable-ID append protocol so cross-links stop drifting.

## Non-Goals

- Doc-format parser unification across the authoring chain (GAP-045) — separate PRD.
- The in-flight authoring guard that prevents mutating an actively-implemented PRD (GAP-038) — separate PRD.
- INDEX and COMPLETION-LOG reconcile mechanics already shipped by PRD 009 R47/R48/R51 — consumed, not
  re-implemented.
- Any change to the human merge gate or to frozen PRD/amendment body immutability.
- A general-purpose backlog query/reporting UI beyond the `list --json` surface needed by the gate.

## Requirements

- **R1** The GAP status enum (`open` | `planned` | `partially resolved` | `resolved`) is single-sourced in
  `living-status/SKILL.md`; every backlog script and gate references that one vocabulary and rejects any
  status token outside it.
- **R2** Frozen PRDs and amendments MAY declare `absorbs: [GAP-NNN, …]` in frontmatter. This key is the
  authoritative gap↔artifact linkage; no command relies on description-prose scraping for absorption, and the
  legacy `"absorbed by PRD N"` scrape path is retained only as a read-time fallback for un-migrated rows.
- **R3** When a PRD or amendment is frozen (`/sw-freeze`) and declares `absorbs: GAP-NNN`, each referenced row
  whose status is `open` flips to `planned — PRD <n>[ A<k>]`, and the index counts refresh, atomically under
  the living-doc single-writer lock. The operation is idempotent: re-freezing or re-running against an
  already-`planned` row is a no-op.
- **R4** `reconcile-status.py gap-resolve --absorbing-prd <n>` treats a `planned — PRD <n>` row matching the
  absorbing PRD the same as an `open` row: when that PRD reaches `complete`, the row flips to
  `resolved (via PRD <n>[ PR #N])`. Linkage is resolved from the absorbing artifact's `absorbs:` frontmatter,
  not from prose. Non-matching rows are untouched.
- **R5** `docs-currency-gate.py` fails closed, scoped to the current run, when either consistency invariant is
  violated: (a) a frozen artifact in scope declares `absorbs: GAP-NNN` while that row is still `open`
  (declared-but-unflipped); or (b) a `planned — PRD <n>` row's absorbing PRD carries no matching `absorbs`
  reference (orphan-planned). Pre-existing unrelated historical drift does not block (consistent with R50).
- **R6** The stable-ID append protocol is documented in `living-status/SKILL.md` and `.sw/layout.md`: the next
  ID is `max(existing) + 1`, IDs are never reused, and cross-links use `GAP-NNN` tokens rather than row
  ordinals.
- **R7** A machine-checkable integrity guard verifies the GAP-BACKLOG index section against the detail table:
  every `GAP-NNN` appears exactly once in each, the index status equals the table status for each ID, and the
  header counts equal the actual per-status tallies. It fails closed on drift introduced by the current run
  and is invokable standalone and from `docs-currency-gate.py`.
- **R8** Header status counts (`resolved N`, `partially resolved N`, `planned N`, `open N`) are recomputed
  deterministically from the table whenever a flip occurs (R3/R4); they are never hand-maintained as an
  independent source.
- **R9** Every backlog mutation (R3/R4/R8) is idempotent under re-run for the same git facts and is serialized
  through the living-doc single-writer lock (PRD 013 R10/R12, PRD 022 R32) so concurrent waves or sessions
  cannot interleave partial writes.
- **R10** A single helper, `scripts/gap-backlog.py` (`list [--json]`, `check`, `flip`), is the sole writer of
  GAP-BACKLOG status; `/sw-freeze` (R3) and `gap-resolve` (R4) both route their mutations through it so the
  two paths cannot diverge.
- **R11** A one-shot backfill (`gap-backlog.py migrate` or a documented manual pass) derives `absorbs:`
  linkage for already-frozen PRDs/amendments from existing `planned — PRD N` / `resolved via PRD N` rows, so
  enabling R5 does not retroactively block on legacy rows that predate the `absorbs:` contract.
- **R12** Each behavior has a failing-before / passing-after fixture wired into
  `scripts/test/run-living-doc-fixtures.sh` and the `verify.test` manifest: freeze flips `open → planned` and
  refreshes counts; absorbing-PRD `complete` flips `planned → resolved`; a declared-but-unflipped row fails the
  gate; an orphan-`planned` row fails the gate; an index↔table mismatch fails the integrity guard; and a
  re-run of each flip is a verified no-op.

## Technical Requirements

- **TR1** (R1, R10) Home the status-enum constant and the parse/format/flip logic in
  `scripts/gap-backlog.py` (delegating to a small Python helper as the other `reconcile-status` subcommands
  do). `reconcile-status.py gap-resolve` calls into this helper rather than carrying its own table-rewrite
  Python so the two share one parser/writer.
- **TR2** (R2) Parse `absorbs:` via the existing frontmatter reader used by `doc_link.py` /
  `spec-union.py`; accept both inline (`absorbs: [GAP-001, GAP-002]`) and YAML block-list forms, and fail
  closed when a non-empty `absorbs:` key yields zero parsed IDs (mirrors the GAP-045 `supersedes`/`retracts`
  hardening intent so the directive is never silently dropped).
- **TR3** (R3) Add an absorption-flip step to the freeze path (`scripts/*freeze*` /`/sw-freeze` command) that,
  after immutability stamping, invokes `gap-backlog.py flip --absorbed-by <prd>[ --amendment <Ak>] --gaps …`
  for each declared gap, guarded by the living-doc lock. Frozen artifact bodies are never modified — only the
  GAP-BACKLOG row and counts.
- **TR4** (R4) Extend `cmd_gap_resolve` in `reconcile-status.py`: the match predicate becomes
  `status in {open, planned} and absorbed_by == absorbing`, where `absorbed_by` is resolved from the
  absorbing PRD's `absorbs:` frontmatter (preferred) or the legacy prose fallback; the resolved-row formatter
  is shared with TR1.
- **TR5** (R5, R7) Extend `docs-currency-gate.py` with the two consistency checks (declared-but-unflipped,
  orphan-planned) and the index↔table integrity check (R7), all scoped to current-run artifacts; emit precise,
  line-anchored causes. The integrity check is also exposed as `gap-backlog.py check` for standalone use.
- **TR6** (R6) Update `core/skills/living-status/SKILL.md` (GAP-BACKLOG section) and `.sw/layout.md` with the
  enum, the `absorbs:` contract, and the append protocol; regenerate `dist/` via the emitter.
- **TR7** (R8) The count refresh recomputes tallies from parsed rows inside `gap-backlog.py flip`; no caller
  passes counts in. The header block is rewritten deterministically.
- **TR8** (R9) Reuse the established living-doc lock helper (the same serialization used by
  `living-docs reconcile`); add no second lock. Mutations read-modify-write the whole table atomically.
- **TR9** (R11) `gap-backlog.py migrate` scans `docs/prds/*/` frontmatter and existing row prose to emit (and,
  with `--write`, apply) the derived `absorbs:` linkage and any catch-up flips; idempotent.
- **TR10** (R12) Add fixtures under the living-doc fixture harness; wire into `verify.test`; regenerate `dist/`
  and the golden parity manifest after any `core/` change.

## Security & Compliance

- No new external surface, host verb, or network call is introduced; all logic is local file manipulation of
  `docs/prds/GAP-BACKLOG.md` under the existing lock.
- GAP-BACKLOG rows and the `absorbs:` key carry only gap IDs and PRD numbers — no transcripts or secrets; the
  memory redaction chokepoint is unaffected.
- Frozen PRD/amendment immutability is preserved: the freeze flip writes only the living GAP-BACKLOG file, not
  the frozen artifact body.
- The push and merge chokepoints and the `main` human gate are unchanged.

## Testing Strategy

Fixtures (failing-before / passing-after), wired into `scripts/test/run-living-doc-fixtures.sh` and
`verify.test`:

| Fixture | Asserts | R-IDs |
| --- | --- | --- |
| `freeze-absorbs-flips-open-to-planned` | freezing an artifact declaring `absorbs: GAP-NNN` flips the `open` row to `planned` and refreshes counts | R3, R8 |
| `ship-flips-planned-to-resolved` | absorbing PRD reaching `complete` flips its `planned — PRD N` rows to `resolved` | R4 |
| `gap-resolve-ignores-nonmatching` | a `planned` row for a different PRD is untouched by `gap-resolve` | R4 |
| `gate-fails-declared-but-unflipped` | a frozen artifact declaring `absorbs: GAP-NNN` with the row still `open` fails the currency gate | R5 |
| `gate-fails-orphan-planned` | a `planned — PRD N` row whose PRD declares no matching `absorbs` fails the gate | R5 |
| `integrity-fails-index-table-mismatch` | an index/table status or presence/count mismatch fails the integrity guard | R7 |
| `flip-rerun-is-noop` | re-running freeze-flip and gap-resolve against already-transitioned rows changes nothing | R3, R4, R9 |
| `absorbs-block-list-parsed` | `absorbs:` as a YAML block list parses; a non-empty key yielding zero IDs fails closed | R2, TR2 |
| `migrate-derives-legacy-linkage` | `gap-backlog.py migrate` derives `absorbs:` linkage for legacy rows idempotently | R11 |

Regression guard: existing `gap-resolve` open→resolved behavior, `living-docs reconcile`, and
`docs-currency-gate` historical-drift tolerance must remain green.

## Rollout Plan

- **Phase 1 — Shared writer + enum (R1, R10, R8).** Introduce `scripts/gap-backlog.py` (+ Python helper) as
  the single parser/writer with deterministic count refresh; single-source the enum. Lowest-risk foundation.
- **Phase 2 — `absorbs:` linkage + freeze flip (R2, R3).** Frontmatter contract + absorption-time
  `open → planned` flip wired into the freeze path under the lock.
- **Phase 3 — Ship flip + gates (R4, R5, R7).** Extend `gap-resolve` for `planned`, add the bidirectional
  currency checks and the index↔table integrity guard.
- **Phase 4 — Docs, migration, fixtures (R6, R9, R11, R12).** Append-protocol docs, one-shot backfill, the
  full fixture set, and `dist/` + golden-manifest regeneration.

Backward compatible: existing `open + absorbed-by` rows still resolve; legacy `planned — PRD N` rows are
migrated by R11 before R5 is enforced, so no historical row blocks the gate at enablement.

## Decision Log

- **D1** Standalone PRD 028 rather than a PRD 009 A3 amendment (operator decision); the PRD extends the shared
  R49/R50 machinery and routes all writes through one helper (R10) to honor the "one shared `gap-resolve`
  machinery, not a competing mechanism" constraint.
- **D2** Machine-readable `absorbs:` frontmatter is the single source of truth for linkage — chosen over an
  authored `Absorbed-by` column or description-prose scraping, which are model-dependent and fragile.
- **D3** Mechanize the full lifecycle (open→planned at freeze, planned→resolved at ship) and gate both
  directions — chosen over fixing only the downstream flip, because both halves silently misrepresented state
  this session (GAP-043 downstream, GAP-046 upstream).
- **D4** Reuse the existing living-doc single-writer lock and the R50 current-run gate scoping — no new
  concurrency model and no new lock.
- **D5** Include a machine-checkable index↔table integrity guard (GAP-044) rather than a docs-only convention,
  because the manual contract has already drifted.
- **D6** One shared writer `gap-backlog.py` consumed by both freeze (R3) and `gap-resolve` (R4), so the two
  transition paths cannot diverge in parsing or formatting.
- **D7** One-shot backfill (R11) migrates legacy rows before R5 is enforced, so the very rows that motivated
  this PRD do not block the new gate at enablement.

## Open Questions

None — all decisions were resolved with the operator before drafting (standalone PRD vs amendment: D1;
linkage mechanism: D2; lifecycle scope: D3; integrity-guard scope: D5).
