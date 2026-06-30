---
date: 2026-06-26
topic: memory-source-of-truth
brainstorm: docs/brainstorms/2026-06-26-memory-source-of-truth-requirements.md
frozen: true
frozen_at: 2026-06-26
---

# PRD 015 — Provider-conditional memory source-of-truth

## Overview

Shipwright's decision-record contract (R32 / KTD3) hardcodes git as the authority: frozen
`docs/decisions/<n>-<slug>.md` records are authoritative and `decision`-class provider memories are
pointers/distillations only. Operators who enable an external memory provider (Recallium / MemPalace) expect
*memory* to be the authority for decisions, so the dual layer — local-only decision files plus overlapping
provider `DECISION` entries — reads as duplication, and legacy pre-policy memories conflict with current R32.

This PRD makes the source of truth **provider-conditional** for the `decision` doc class: an external provider
makes memory authoritative; `in-repo` / no provider keeps the git record authoritative (status quo). To survive
the hard constraints — the freeze/CI gate runs with the provider out of reach, `git worktree` only materializes
tracked files, and PR review must show the decision — a redacted, committed snapshot of every frozen decision
always rides the repo, marked non-authoritative under memory-SoT. It derives from the frozen brainstorm
`docs/brainstorms/2026-06-26-memory-source-of-truth-requirements.md` (R1–R12) and closes GAP-BACKLOG row 25.

## Goals

1. One authoritative store per mode: external provider → memory is SoT for decisions; in-repo/none → git is SoT.
2. CI freeze, worktree propagation, and PR review keep working without provider access, via an always-committed
   redacted snapshot.
3. Default behavior unchanged for existing repos (`auto` + in-repo = today's R32/KTD3).
4. Conflicts and legacy pre-policy memories reconcile through `/sw-memory-audit` without weakening redaction,
   the rule-class human gate, or the trust boundary.

## Non-Goals

- Extending the SoT switch to `learning`/`design`/other doc classes in v1 (decision-only; see DL-2).
- Changing the memory provider adapter contract or swapping providers (PRD 010).
- Making the freeze gate provider-transactional — it stays auditable; the provider is out of CI reach (DL-3).
- Removing the committed decision snapshot under any mode — CI, worktrees, and PR review depend on it (DL-1).
- Weakening the redaction chokepoint (R41), rule-class human gate (R42), or trust boundary (R43).

## Requirements

R-IDs are carried forward from the frozen brainstorm (stable namespace; do not renumber). Requirement text
receives only clarifying edits.

### Source-of-truth policy

- **R1** A provider-conditional source-of-truth policy MUST govern the `decision` doc class: an external memory
  provider → memory is authoritative; `in-repo` / no provider → the git record is authoritative (status quo
  R32/KTD3).
- **R2** A `memory.sourceOfTruth` config knob (`repo` | `memory` | `auto`) MUST select the authority; `auto` MUST
  derive it from provider class (external → `memory`, `in-repo`/none → `repo`). Default MUST be `auto`,
  preserving today's behavior for existing in-repo repos. `.sw/config.schema.json` MUST accept the knob.
- **R3** The SoT switch MUST be scoped to the `decision` doc class in v1; `learning`/`design`/other classes stay
  distillation-only unless a future explicit config extends scope.

### Always-committed snapshot + freeze/CI contract

- **R4** Regardless of SoT, a **redacted committed snapshot** of each frozen decision record MUST exist under
  `docs/decisions/` (frontmatter + body), so `check-frozen.py`, `git worktree` propagation, and PR review work
  without provider access. Under memory-SoT the snapshot MUST be marked non-authoritative (pointer to the
  provider record).
- **R5** The freeze/CI contract MUST remain auditable, not transactional: `/sw-freeze` and `check-frozen.py` MUST
  NOT require the provider to be reachable and MUST operate on the committed snapshot. A provider write of the
  authoritative record (memory-SoT) MUST be best-effort with a recorded audit breadcrumb, never a CI gate.

### Pointer inversion + supersede

- **R6** The authority pointer MUST invert with SoT: repo-SoT → the provider `decision` memory points at the git
  record (`relatedFiles`); memory-SoT → the committed git snapshot carries a forward pointer to the
  authoritative provider record. Exactly one side is authoritative at a time.
- **R7** `docs/decisions/SUPERSEDED.log` MUST remain the committed supersede manifest in both modes; on supersede
  the authoritative side MUST be updated and `/sw-memory-sync` MUST reconcile the non-authoritative pointer
  best-effort.

### Compound + audit

- **R8** `/sw-retrospective` (compound) `decision` writes MUST respect SoT: under repo-SoT store a pointer (never
  the record body — today's rule); under memory-SoT store the content-bearing authoritative record (via the
  redaction chokepoint) and keep the committed snapshot as the pointer.
- **R9** `/sw-memory-audit` MUST resolve git↔provider conflicts per the active SoT, flag content-bearing
  `decision` memories that contradict the authoritative side, and provide a one-time reconcile path for legacy
  pre-policy memories (e.g. Recallium #2059/#2068) when switching modes.

### Safety + migration + cross-cutting

- **R10** Redaction (R41), the rule-class human gate (R42), and the trust boundary (R43) MUST hold identically in
  both modes; a provider write of decision content MUST pass `scripts/memory-redact.py` first. A provider outage
  MUST degrade to the committed snapshot with a warning and MUST NOT block the workflow.
- **R11** Switching an existing repo from repo-SoT to memory-SoT MUST be an explicit operator action with a
  one-time `/sw-memory-audit` reconcile; the default (`auto` + in-repo) MUST produce no behavior change.
- **R12** All `core/` changes MUST propagate to `dist/` via `python3 -m sw generate --all` (freshness gate
  passing), be covered by fixtures, and be documented in `skills/memory/SKILL.md`, `rules/memory-guardrails.mdc`,
  `.sw/layout.md`, and the memory guide.

## Technical Requirements

- **TR1 — SoT resolver.** Add a resolution helper (e.g. `scripts/memory-sot.py` or a `memory-preflight` step)
  that reads `memory.sourceOfTruth` + provider class and returns the authoritative side for the `decision` class
  (`repo` | `memory`); single-sourced for freeze, compound, and audit (R1, R2, R3).
- **TR2 — Snapshot writer.** `/sw-freeze` (decision path) MUST always write/refresh the redacted committed
  snapshot under `docs/decisions/` via the redaction chokepoint, stamping `authoritative: repo|memory` and a
  forward pointer under memory-SoT (R4, R6, R10).
- **TR3 — Freeze/CI offline-safe.** `check-frozen.py` + `/sw-freeze` operate only on the committed snapshot and
  never call the provider; the memory-SoT provider write is a best-effort post-stamp step that records an audit
  breadcrumb (R5).
- **TR4 — Pointer inversion + supersede.** `memory-preflight` write recipe + `scripts/reconcile-status.py` /
  `SUPERSEDED.log` handling honor the inverted pointer per SoT; `/sw-memory-sync` reconciles the
  non-authoritative pointer best-effort (R6, R7).
- **TR5 — Compound SoT branch.** The `/sw-retrospective` decision-write path branches on TR1: pointer under
  repo-SoT, content-bearing authoritative record under memory-SoT (chokepoint always) (R8).
- **TR6 — Audit conflict + legacy reconcile.** `/sw-memory-audit` gains a SoT-aware conflict pass that flags
  contradicting content-bearing decision memories and offers a one-time legacy reconcile on mode switch (R9,
  R11).
- **TR7 — Config + schema + migration default.** Add `memory.sourceOfTruth` to `workflow.config.json`,
  `.sw/config.schema.json`, and `/sw-setup` seeding (default `auto`); document the explicit switch + reconcile
  (R2, R11).
- **TR8 — Emitter + docs + fixtures.** Regenerate `dist/`; update memory skill, guardrails rule, layout, and
  guide; add the Testing Strategy fixtures (R12).

## Security & Compliance

- **Redaction is mode-independent and mandatory.** Every provider write of decision content passes
  `scripts/memory-redact.py` (R41) before persist; the committed snapshot is likewise redacted (R4, R10). No raw
  transcript or secret is ever stored on either side.
- **Trust boundary unchanged (R43).** The provider still holds only project-scoped operational data via
  least-privilege credentials in the environment; making it authoritative for decisions does not grant it new
  credential scope. A compromised provider is mitigated by the always-committed redacted snapshot (git remains a
  recoverable copy).
- **Rule-class human gate unchanged (R42).** Decision-SoT does not auto-promote anything to rule-class; rule
  promotion stays human-gated and allowlisted.
- **Fail-closed vs availability.** Freeze/CI never depend on the provider (R5); a provider outage degrades to the
  snapshot with a warning (R10) — availability of the workflow is preserved without compromising redaction.
- **No false authority.** Exactly one side is authoritative at a time (R6); `/sw-memory-audit` detects and
  reconciles drift (R9) so the two layers cannot silently diverge.

## Testing Strategy

All fixtures extend the existing harness invoked by `workflow.config.json` `verify.test` (notably the memory and
freeze suites).

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `memory-sot-resolve-auto` | `auto` resolves external provider → `memory`, in-repo/none → `repo`; explicit `repo`/`memory` honored; schema accepts the knob | R1, R2 |
| `memory-sot-decision-scope-only` | the SoT switch applies only to the `decision` class; `learning`/`design` stay distillation-only | R3 |
| `memory-sot-snapshot-always-committed` | a redacted decision snapshot is committed under `docs/decisions/` in both modes; marked non-authoritative under memory-SoT | R4, R6 |
| `memory-sot-freeze-offline` | `/sw-freeze` + `check-frozen.py` pass with the provider unreachable; memory write is best-effort with an audit breadcrumb | R5 |
| `memory-sot-pointer-inversion` | repo-SoT → provider points at git record; memory-SoT → snapshot points at provider record; exactly one authoritative | R6 |
| `memory-sot-supersede-reconcile` | `SUPERSEDED.log` committed in both modes; `/sw-memory-sync` re-points the non-authoritative side | R7 |
| `memory-sot-compound-branch` | `/sw-retrospective` stores a pointer under repo-SoT and a content-bearing record under memory-SoT (chokepoint always) | R8 |
| `memory-sot-audit-conflict` | `/sw-memory-audit` flags a contradicting content-bearing decision memory and offers a one-time legacy reconcile on switch | R9, R11 |
| `memory-sot-redaction-fail-closed` | a redaction failure aborts the provider write and the snapshot write (no raw store) | R10 |
| `memory-sot-default-no-change` | default `auto` + in-repo reproduces today's R32/KTD3 behavior exactly | R2, R11 |
| `memory-sot-emitter-freshness` | `dist/` regenerated and fresh | R12 |
| `memory-sot-docs-presence` | memory skill, guardrails rule, layout, and guide describe the SoT policy | R12 |

Per-R traceability is finalized in `/sw-tasks`.

## Rollout Plan

- **Single feature branch** `feat/memory-source-of-truth`, delivered in dependency-ordered phases: (1) SoT
  resolver + config/schema/defaults (R1–R3); (2) always-committed redacted snapshot + offline-safe freeze/CI
  (R4, R5, R10 snapshot path); (3) pointer inversion + supersede reconcile (R6, R7); (4) compound SoT branch +
  audit conflict/legacy reconcile + migration (R8, R9, R11); (5) docs + dist + fixtures (R12).
- **Backward compatible.** Default `auto` + in-repo is today's behavior (R2, R11); the snapshot is additive; the
  freeze gate never gains a provider dependency (R5).
- **Bootstrap caution.** First adoption of `memory.sourceOfTruth: memory` SHOULD be supervised and follow a
  `/sw-memory-audit` reconcile of legacy memories (R9, R11).
- **Emitter.** Regenerate `dist/` after every `core/` change; freshness gate enforces parity.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Always commit a redacted decision snapshot under `docs/decisions/`, even under memory-SoT | CI freeze runs with the provider out of reach, `git worktree` only materializes tracked files, and PR review must show the decision; dropping the file would break all three (feasibility + adversarial lenses). |
| DL-2 | Scope the SoT switch to the `decision` class in v1 | Decisions are the operator's stated pain (duplication); broadening to `learning`/`design` now would expand blast radius without evidence (scope-guardian lens). |
| DL-3 | Keep freeze/CI auditable, not transactional; provider write is best-effort | The provider is unreachable in CI; a transactional gate would make freeze flaky and provider-coupled. Authority + an audit breadcrumb, with reconcile via `/sw-memory-audit`, matches the existing "auditable not transactional" pointer model (feasibility lens). |
| DL-4 | `memory.sourceOfTruth: auto` defaults from provider class; default preserves repo-SoT for in-repo | Operator expectation is provider-driven, but some teams want git authority even with a provider; an explicit knob with a no-change default avoids surprising existing repos (product + scope-guardian lenses). |
| DL-5 | Invert exactly one authoritative pointer per mode; reconcile via audit | Two authoritative copies is the duplication complaint; a single authority with a non-authoritative pointer (either direction) and an audit pass keeps them consistent (coherence + adversarial lenses). |
| DL-6 | Redaction (R41) / rule-class gate (R42) / trust boundary (R43) are mode-independent | Changing where authority lives must not change what content is allowed to persist or who approves rule promotion; safety is orthogonal to authority (security lens). |

## Open Questions

None. The CI-reach constraint is resolved by the always-committed snapshot (DL-1); v1 scope is decision-only
(DL-2); the default preserves existing behavior (DL-4) so no forced migration.
