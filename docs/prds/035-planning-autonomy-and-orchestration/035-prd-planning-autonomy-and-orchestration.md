---
date: 2026-06-27
topic: planning-feedback-lifecycle
brainstorm: docs/brainstorms/2026-06-27-planning-feedback-lifecycle-requirements.md
depends: [031, 032, 033, 034]
frozen: true
frozen_at: 2026-06-27
---

# PRD 035 — Planning Autonomy, Backlog Pull-In & Two-Track Orchestration

## Overview

The capstone of the unified Planning & Feedback Lifecycle: the autonomy posture, backlog pull-in, and the
two-track doc-edit workflow that removes per-edit PR friction. It adds **backlog pull-in** at PRD creation
and task generation (auto-*proposed*, human-confirmed), the **autonomy posture** (`maintenance-only` default
with a **bounded `full-conductor`** opt-in), the **two-track doc-edit** driver (batched mechanical auto-merge
vs auto-driven substantive PR), and finalizes the planning command surface. The mutation-safety guards now
live in PRD 032 (sequenced early); this PRD composes them.

`depends:` on PRD 031 (model), 032 (guards/in-flight signal), 033 (lifecycle/reconciler/scheduler), and 034
(visibility) — it composes all four. Derived from frozen brainstorm requirements R29–R31, R40–R43, and R48
(command surface); resolves brainstorm OQ1 (command naming) and OQ3 (related-detection strategy). This
closes the user's backlog-pull-in and doc-edit-friction concerns (lost-amendment and silent-mutation are
closed by PRD 032).

**Bounded autonomy (doc-review decision).** `maintenance-only` remains the safe default. The `full-conductor`
opt-in is **bounded**: it auto-decides only the **gap/absorption** class (the low-risk bookkeeping the user
asked to automate "like the implementation loop"), never auto-absorbs `private`/`memory` units, inherits the
conductor loop hard-stop with an explicit per-session mutation budget, and may only enqueue handoffs (no
nested orchestrator dispatch). This gives real autonomy on the safe class while keeping spec-quality
decisions human-gated.

## Goals

- Auto-propose backlog pull-in at unit creation and task generation, flagging stale/already-resolved items,
  with the human confirming what to absorb, and never leaking private-unit bodies into proposals.
- Define the autonomy posture (autonomous bookkeeping, human-gated content decisions) with a **bounded**
  `full-conductor` opt-in governed by the conductor's legitimate-halt model, a per-session mutation budget,
  and confidence-gated, reversible absorption restricted to the gap/absorption class and non-private units.
- Replace per-edit doc PRs with a two-track model (batched mechanical auto-merge vs auto-driven substantive
  PR) with an explicit mechanical allowlist, branch-protection detection, and lock serialization — always
  respecting branch protection.
- Finalize the planning command surface (reconciler entry, scheduler entry, posture config) without
  namespace sprawl.

## Non-Goals

- The unit model/migration/tokenizer (PRD 031); mutation-safety guards + in-flight signal (PRD 032);
  lifecycle/scheduler/reconciler (PRD 033); visibility/store (PRD 034).
- Any auto-merge to the protected `main`/trunk; the human merge gate for substantive specs is unchanged.
- Re-implementing the delivery conductor/wave engine; this consumes existing conductor primitives and never
  nests orchestrator dispatch.
- Full planning conductor *by default*, and **unbounded** in-loop auto-decision — `full-conductor` is an
  explicit opt-in and is bounded to the gap/absorption class with a mutation budget.
- Deliver-side in-loop learning/auto-amendment runtime (the cancelled-025 problem is reframed as the
  deliver-side feedback complement consuming this graph; its runtime is tracked separately, not built here).

## Requirements

- **R1** At PRD/unit creation, the graph is auto-scanned for related gap/units (shared file paths, tags, and
  id/lineage edges) and absorption candidates are *proposed*; the scan flags stale candidates already
  resolved/absorbed by a shipped unit; the human confirms which to absorb (gated authoring).
- **R2** At task generation (`/sw-tasks`), the backlog is re-scanned for newly-related items and PRD
  amendments are *proposed*; the human confirms.
- **R3** Edge/status maintenance for absorption is autonomous (driven by PRD 033's reconciler); only the
  pull-in and amendment *choices* are human-gated.
- **R4** Pull-in proposals route through the PRD 034 visibility resolver: private-unit candidates contribute
  metadata only (id/title/status/edges, honoring opaque-title), never body text, even under opt-in semantic
  matching; the proposal confirm-list is in the 034 emission-point registry; a fixture proves a private gap's
  (non-opaque) title may appear in a proposal but its body never does.
- **R5** Pull-in similarity ships **deterministic-first** (shared file paths + tags + id/lineage edges);
  model-based semantic matching is an **opt-in enhancement** behind a config flag. Because every proposal is
  human-confirmed, precision/recall is not safety-critical; semantic matching only widens the *proposal* set
  and never auto-absorbs. A minimum-recall acceptance fixture asserts the known GAP-043/044/046 absorption
  cases appear in proposals on the migrated corpus. Proposals are **rank-thresholded** and repeat proposals
  for already-flagged stale candidates are suppressed (product proposal-fatigue mitigation).
- **R6** Mechanical/living maintenance graph bookkeeping runs autonomously with no prompts; content-authoring
  decisions (pull-in, amendments, priority changes, cancel/supersede) are auto-proposed but human-confirmed
  by default.
- **R7** A **pull-in / absorption confirm against a frozen or `planned` (frozen) unit** does not mutate the
  frozen unit: it is routed to an amendment track or a new superseding unit, and adding an `absorbs:` edge
  that would change frozen scope requires explicit `--accept-frozen-impact` (logged); freeze immutability
  (031 R17) has no pull-in exception (closes the adversarial frozen-graph-mutation scenario).
- **R8** A **bounded** `full-conductor` config opt-in elevates **gap/absorption-class** content decisions to
  in-loop auto-decision governed by the conductor's legitimate-halt model; it is off by default, never
  weakens the merge-to-`main` gate, **never auto-absorbs `private`/`memory` units** (those always require
  human confirm), and is subject to a **per-session autonomous-mutation budget + loop hard-stop** inherited
  from the conductor skill (halt + human resume after N mutations). Absorption still requires an explicit
  edge-confidence threshold and a reversible undo window before the PRD 033 reconciler materializes the flip.
- **R9** The `full-conductor` driver **only enqueues handoff commands**; it may not invoke `/sw-deliver`,
  `/sw-doc`, or any orchestrator from within its loop (no nested dispatch — `sw-naming`/`sw-conductor`
  boundary), and there is an explicit halt between a reconcile batch and any downstream dispatch.
- **R10** Mechanical/living maintenance edits are batched and committed via a docs-only PR with CI-gated
  auto-merge (or direct-to-trunk where the repo permits), without a per-edit PR.
- **R11** The two-track classifier uses an explicit **mechanical allowlist** limited to **reconciler-generated
  artifacts**: the INDEX active/archive **`derived` region only**, the SUPERSEDED manifest, and the generated
  gap index. The `inFlight` region is **never** mechanically edited (it is the PRD 032 deliver writer's sole
  region). **Any path under `docs/planning/<unit-id>/` — body or frontmatter — is substantive** (closes the
  adversarial frontmatter-edit misclassification); misclassification regression fixtures cover the boundary.
- **R12** Substantive authoring retains the docs-branch → docs-PR gate but is fully auto-driven
  (auto-provisioned worktree, auto-opened PR) so it is a single command rather than manual git.
- **R13** Branch protection is always respected: protection is detected via the host API (not assumed); when
  detection is ambiguous or `gh` auth is missing, the driver defaults to the PR path and never attempts a
  direct push. `allowDirectTrunk: true` requires a **live protection probe succeeding within a configured
  TTL** and is **never combined with auto-merge in public-repo templates**; under any detected protection it
  fails closed to the PR path.
- **R14** Two-track auto-merge and the PRD 033 reconciler serialize safely: the batched PR embeds a
  **monotonic content-hash covering both INDEX regions (`derived` + `inFlight`)** taken at open; the
  auto-merge is aborted if either region's hash advanced since — so a stale maintenance PR can never revert
  reconciler updates or clobber in-flight markers (closes the adversarial stale-PR/token-scope scenario).
- **R15** The planning command surface is finalized (see D6) and wired: a mechanical reconciler entry, a
  graph-driven scheduler entry, and the autonomy posture config key; commands resolve paths via the PRD 031
  helper.
- **R16** No regression to the documentation that feeds the delivery loop: frozen immutability, traceability,
  and spec-rigor gates are preserved; foundational frozen workflow invariants are retained.

## Technical Requirements

- **R17** A related-units scanner module produces ranked, threshold-gated absorption/amendment proposals from
  the graph; it is consumed by `/sw-prd` (creation) and `/sw-tasks` (generation), routes candidates through
  the visibility resolver (R4), and emits a confirm-list, never an auto-absorb.
- **R18** A two-track edit driver classifies an edit as mechanical (batched auto-merge PR / direct-to-trunk
  where permitted) vs substantive (auto-driven docs worktree + PR) using the R11 allowlist (generated
  artifacts only; any `docs/planning/<unit-id>/` path is substantive); it reuses the existing
  `docs_worktree.py`/`docs_pr.sh` machinery and adds a net-new `docs-merge.sh` (or `host_lib` merge+checks-
  wait, since `docs_pr.sh` stops at PR open), the host-API branch-protection probe (R13), and the
  both-region content-hash abort (R14) with fixtures mirroring the merge-queue fixtures.
- **R19** The autonomy posture is the `planning.autonomy` config key (`maintenance-only` default |
  `full-conductor`) **owned here** (PRD 033 reads it and stubs the default in the train); the bounded
  full-conductor path adopts the conductor skill's legitimate-halt model and records the confidence
  threshold, per-session mutation budget, undo window, and the gap/absorption-only + non-private scope for
  absorption.
- **R20** Autonomy/pull-in/two-track artifacts land in `core/` and propagate to both dist trees;
  `copy-to-core` parity and emitter-freshness fixtures cover the new scripts and config keys.
- **R21** This PRD updates the docs it changes, as **acceptance criteria**: `core/commands/sw-prd.md` and
  `core/commands/sw-tasks.md` (pull-in proposal confirm-list), `core/commands/sw-doc.md` (reconciler hook,
  two-track edits, posture), `core/commands/sw-feedback.md` + `core/skills/feedback/references/route-record.md`
  + `core/rules/sw-naming.mdc` (route gap-capture to gap units, not GAP-BACKLOG),
  `core/skills/git-workflow/SKILL.md` + `core/rules/sw-git-conventions.mdc` (two-track policy),
  `core/skills/conductor/SKILL.md` (bounded full-conductor legitimate-halt + mutation-budget + no-nested-
  dispatch clauses), **`core/sw-reference/config.schema.json` + both `workflow.config.example.json` copies +
  `docs/guides/configuration.md`** (the `planning.autonomy` enum key with cross-ref to 033 soft-enforce), and
  the **033-coordinated** `docs/guides/workflows.md`/`docs/guides/commands.md` (035-owned sections: two-track
  edit driver, mechanical allowlist, posture, full-conductor; the lifecycle/reconciler sections are
  033-owned).

## Security & Compliance

- **R22** Pull-in and amendment proposals route external/context payloads through `memory-redact.py` and
  embed them only in fenced untrusted blocks; the proposal step never forwards raw transcripts or provider
  memory payloads, and private-unit bodies/opaque titles are filtered by the visibility resolver (R4).
- **R23** `full-conductor` opt-in, any `--override`, `--accept-frozen-impact`, and direct-to-trunk are
  explicit, logged to durable state (who/when/why), and never the default; branch protection is never
  bypassed; the per-session mutation budget caps autonomous graph churn.
- **R24** Two-track auto-merge applies only to mechanical maintenance on the docs path (R11 allowlist) and
  never to substantive specs, the `inFlight` region, or the protected trunk merge gate; a pre-merge fixture
  fails the mechanical PR if any unit-body marker or `docs/planning/<unit-id>/` path appears in its diff, and
  runs the same secret-scan as pre-push.

## Testing Strategy

- Pull-in fixtures (R1–R5, R7, R17): related units proposed (not auto-absorbed); stale/already-resolved
  flagged + suppressed on repeat; absorption edges applied only after confirmation; `/sw-tasks` re-scan
  proposes amendments; a pull-in against a frozen unit routes to amendment/superseding (no frozen mutation
  without `--accept-frozen-impact`); private-unit bodies absent from proposals; minimum-recall on
  GAP-043/044/046.
- Posture fixtures (R6, R8–R9, R19): bookkeeping runs without prompts; content decisions gated by default;
  bounded `full-conductor` elevates only gap/absorption, never private units, halts at the mutation budget,
  enqueues handoffs only (no nested dispatch), with confidence threshold + reversible undo.
- Two-track fixtures (R10–R14, R18, R24): mechanical edits (generated artifacts only) batch + auto-merge (or
  direct-to-trunk only with a live protection probe within TTL, never with auto-merge on public templates); a
  frontmatter-or-body edit under `docs/planning/<unit-id>/` is forced substantive; the `inFlight` region is
  never mechanically edited; misclassification regression; branch-protection detection defaults to PR path
  when ambiguous; the both-region content-hash aborts a stale PR; no trunk-gate bypass.
- Command-surface fixtures (R15) and emitter/parity fixtures (R20); doc-currency fixtures (R21).
- No-regression (R16).

## Rollout Plan

1. **Pull-in proposals:** land the related-units scanner (deterministic-first, threshold-gated,
   visibility-filtered, frozen-safe) and the auto-propose/human-confirm flow in `/sw-prd` and `/sw-tasks`.
2. **Posture + command surface:** wire the `planning.autonomy` config (owned here), the finalized command
   surface, and the **bounded** `full-conductor` opt-in (gap/absorption-only, non-private, confidence
   threshold + undo + mutation budget + no nested dispatch).
3. **Two-track edits:** land the mechanical/substantive edit driver over the existing docs-worktree/PR
   machinery, the net-new `docs-merge.sh`, the host-API branch-protection probe, and the both-region
   content-hash reconciler serialization. This replaces the PRD 033 R17 interim no-auto-PR behavior.

## Decision Log

- **D1.** Autonomy = autonomous bookkeeping + human-gated content decisions by default (brainstorm K5) —
  protects spec quality (the user's hard constraint) while removing manual drudgery; `full-conductor` is an
  explicit, **bounded** opt-in.
- **D2.** Mutation-safety guards moved to PRD 032 (early) per the doc-review value-sequencing decision; this
  capstone composes them rather than owning them.
- **D3.** Pull-in is human-gated by default; bounded `full-conductor` adds a confidence threshold + reversible
  undo window before the reconciler materializes an `absorbs` flip (closes the adversarial wrong-auto-absorb
  scenario).
- **D4.** Two-track edits use an explicit mechanical allowlist restricted to reconciler-generated artifacts
  (INDEX `derived` region, SUPERSEDED manifest, gap index); **any `docs/planning/<unit-id>/` path — body or
  frontmatter — is substantive**, and the `inFlight` region is never mechanically edited (closes the
  adversarial frontmatter-misclassification and inFlight-clobber scenarios); auto-merge never touches the
  trunk gate.
- **D5.** Branch protection is detected via the host API, not assumed; ambiguous detection defaults to the PR
  path; `allowDirectTrunk` requires a live probe within TTL and never combines with auto-merge on public
  templates (closes the adversarial detection-failure scenario). The auto-merge plumbing is net-new
  (`docs-merge.sh`) because `docs_pr.sh` stops at PR open today.
- **D6.** Resolves brainstorm OQ1 (command naming): the planning surface **extends `/sw-doc`** rather than
  adding a top-level `/sw-plan`. The mechanical reconciler is `scripts/planning-graph.sh reconcile`
  (script-level, invoked by living-status and `/sw-doc`); graph-driven scheduling is `/sw-deliver next`
  (PRD 033); the autonomy posture is a `planning.autonomy` config key (`maintenance-only` default |
  `full-conductor`), not a new command — avoids namespace sprawl and reuses existing conductor adoption.
- **D7.** Resolves brainstorm OQ3 (related detection): deterministic-first (paths + tags + lineage),
  semantic matching opt-in. Because proposals are always human-confirmed, precision/recall is not
  safety-critical; a minimum-recall fixture guards the known absorption cases and rank-thresholding +
  repeat-suppression avoid proposal fatigue.
- **D8.** Reconciler/two-track serialization (R14) uses a **both-region INDEX content-hash** (not a
  derived-only or commit-SHA token) so a concurrent `inFlight` write cannot let a stale maintenance PR revert
  reconciler state (closes the adversarial token-scope scenario).
- **D9.** `full-conductor` is **bounded** (doc-review decision): gap/absorption-class only, never auto-absorbs
  private units, inherits the conductor loop hard-stop + per-session mutation budget, and only enqueues
  handoffs (no nested dispatch) — delivering the autonomy the user asked for on the safe class while the
  scope panel's gold-plating concern is contained and spec-quality decisions stay human-gated.
- **D10.** Pull-in/absorption against a frozen unit never mutates it (R7): it routes to amendment/superseding
  and requires `--accept-frozen-impact` for any frozen-scope edge — freeze immutability has no pull-in
  exception (closes the adversarial frozen-graph-mutation scenario).
