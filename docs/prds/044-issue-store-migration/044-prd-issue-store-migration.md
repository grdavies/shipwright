---
date: 2026-06-30
topic: issue-store-migration
brainstorm: docs/brainstorms/2026-06-30-issue-backed-planning-store-requirements.md
program: issue-backed-planning-store
depends: [043]
frozen: true
frozen_at: 2026-06-30
---

# PRD 044 — Issue-store migration

## Overview

This PRD adds durable, verified, bidirectional migration between the file-store and the `issue-store`
introduced by PRD 043 (core). It lets a project move existing planning artifacts (PRDs, gap units, task
lists, brainstorms) into issues, and move them back, without losing bodies or lifecycle state, and without
risking a corrupt half-migrated repository. It also retires the `GAP-BACKLOG.md` projection behind a
compatibility shim during transition (the gaps-as-issues behavior itself is PRD 045).

It depends on PRD 043 for the provider abstraction, canonical serialization and content-hash (R35), the
visibility resolver binding (R43), and the project-key/identification model (R10–R12/R42).

## Program

Part of the issue-backed planning store program (PRD 043 Program table). Owns **R16, R17, R38**. Depends on
PRD 043.

## Goals

- Provide a single bidirectional migration command (files ⇄ issues), idempotent and dry-run by default (R16).
- Verify every artifact by content-hash before removing any source (R16).
- Preserve bodies and full lifecycle state — open/frozen, edges/links, gap status — in both directions (R17).
- Make migration durable: journaled, resumable after partial failure, with rollback and a half-migrated doctor (R38).
- Retire `GAP-BACKLOG.md` behind a read-only compatibility shim during transition.

## Non-Goals

- The issue-store mode, adapters, canonical hashing, freeze, or security model — owned by PRD 043.
- Native gaps-as-issues behavior, commit/PR linkage, and milestones — owned by PRD 045.
- Scheduler / derived INDEX behavior — owned by PRD 046.
- Migrating decision-class artifacts; they remain file-native (PRD 043 D8).
- Changing default behavior; migration is an explicit, opt-in operator action.

## Requirements

- **R16** — A bidirectional migration command supports files-to-issues and issues-to-files, is idempotent, dry-run by default, and content-hash-verifies (via PRD 043 R35) before removing any source artifact; it is resumable after partial failure.
- **R17** — Migration preserves bodies and lifecycle state — open/frozen status, edges and links (the PRD 043 R29 `sw-edges` block plus native projections), and gap status — in both directions, so nothing about lifecycle is lost when switching modes.
- **R38** — Migration uses a durable journal with a per-artifact state machine (`pending` → `created` → `verified` → `source-removed`) and idempotency keys (source path + content-hash); ordering is verify-then-delete; resume is idempotent with defined rollback invariants; migration runs one direction at a time with `/sw-deliver` and the reconciler quiesced; a doctor subcommand detects and repairs half-migrated repositories.

## Technical Requirements

- **Migration engine.** A journal file under run-state (git-ignored) records per-artifact state and idempotency keys; the engine is restart-safe and never deletes a source before its target is hash-verified.
- **Quiesce.** Migration acquires an exclusive planning lock; it refuses to run while a deliver run or reconcile is active and instructs the operator to quiesce.
- **Dry-run default.** Without an explicit `--apply`, the command reports the full plan (creates, hash checks, deletions) and mutates nothing.
- **GAP-BACKLOG shim.** During transition, `GAP-BACKLOG.md` becomes a read-only projection of gap issues; a follow-up (PRD 045) makes gaps natively issue-backed. The shim is removed once a project completes migration.
- **Doctor.** `migrate doctor` enumerates artifacts whose journal state is inconsistent (created-but-unverified, verified-but-source-present) and offers idempotent repair or rollback.
- **Visibility gate.** Every create during migration resolves visibility via PRD 043 R43 before any API write; a private artifact targeting a public/shared store aborts that item and is reported (no partial private leak).

## Security & Compliance

- **Visibility fail-closed (PRD 043 R43).** Migration is a write path and inherits the resolver gate; private/`memory` artifacts are refused against a public or shared store.
- **Secret-scan (PRD 043 R45).** Bodies and comments written during migration pass the secret-scan chokepoint.
- **No source loss.** Verify-then-delete ordering plus the journal guarantees that an interrupted migration never leaves an artifact with neither a verified target nor its source.

## Testing Strategy

- **Round-trip equality (R16/R17).** files → issues → files asserts content-hash equality (PRD 043 R35) and lifecycle/edge/gap-status preservation.
- **Dry-run inertness (R16).** A dry-run run mutates nothing and reports a complete, accurate plan.
- **Partial-failure resume (R38).** Injected failure mid-migration asserts journaled idempotent resume, no source deleted before verification, and a clean final state.
- **Rollback / doctor (R38).** A deliberately corrupted journal state is detected and repaired by `migrate doctor` with documented invariants.
- **Quiesce enforcement (R38).** Migration refuses to run while a deliver/reconcile is active.
- **Privacy during migration (R17/PRD 043 R43).** A private artifact is refused against a public store on migration, with the rest of the batch unaffected.
- **GAP-BACKLOG shim.** During transition the projection is read-only and accurate; after completion the shim is removed cleanly.

## Rollout Plan

Default-inert; migration is an explicit operator command. Documentation exit-gate per PRD 043 R49.

1. **Migration engine + dry-run** — journal, idempotency keys, verify-then-delete, dry-run default (R16, R38).
2. **Lifecycle preservation** — bodies, open/frozen, edges/links, gap status both directions (R17).
3. **Resilience + doctor** — resume, rollback invariants, quiesce, `migrate doctor`; GAP-BACKLOG read-only shim (R38).

## Success Criteria

- **SC4 (lossless migration).** files → issues → files round-trips with content-hash equality and no lifecycle/edge/gap-status loss.
- **SC4a (durable resume).** An interrupted migration resumes idempotently with no source deleted before verification and no orphaned target.
- **SC4b (safe by default).** A migration without `--apply` mutates nothing.

## Documentation Impact

Per-phase exit-gates (PRD 043 R49):

- `docs/guides/workflows.md` / `commands.md` — migration command, dry-run/apply, quiesce, doctor (Phases 1–3).
- `.sw/layout.md` — migration journal location and semantics (Phase 1).
- `core/skills/feedback/SKILL.md` / gap-capture docs — GAP-BACKLOG read-only shim during transition (Phase 3).
- `core/commands/` — new migration command doc with non-goals (Phase 1).

## Decision Log

- **D44.1** — Migration is bidirectional, verified, idempotent, and dry-run by default (carries brainstorm D4).
- **D44.2** — Verify-then-delete with a durable journal is mandatory; no source is removed before its target is hash-verified.
- **D44.3** — Migration runs one direction at a time with deliver/reconcile quiesced, to avoid a dual-mode authoritative graph.
- **D44.4** — `GAP-BACKLOG.md` becomes a read-only shim during transition; native gaps-as-issues is PRD 045.

## Open Questions

None blocking. The concrete journal schema and the per-provider link/sub-issue projection mapping are
finalized during `/sw-tasks` against the PRD 043 capability matrix.
