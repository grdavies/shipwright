---
date: 2026-06-30
visibility: public
topic: issue-store-planning-graph
brainstorm: docs/brainstorms/2026-06-30-issue-backed-planning-store-requirements.md
program: issue-backed-planning-store
depends: [043-issue-backed-planning-store, 044-issue-store-migration, 045-issue-native-dev-tracking]
frozen: true
frozen_at: 2026-06-30
---

# PRD 046 — Issue-store planning-graph derivation

## Overview

This PRD makes the planning graph **issue-derived** when the issue-store backend is active: a label-driven
scheduler and an issue-derived INDEX/living-status (R25), epic + sub-issue hierarchy for task lists (R23),
the disposition of the committed `inFlight` region, reconciler/scheduler integration with PRD 031/032/033,
cross-project recall wiring, and the request-budget that keeps issue-derived views within provider rate
limits. It completes the issue-store experience: when it lands, the planning graph follows the issues with no
authoring stub files and no dual file/issue maintenance.

This PRD **owns** core R-IDs **R23** and **R25** and **references** the core contracts it builds on —
PRD 043 R27 (cross-project recall), R34 (region-disposition matrix contract), R43 (issue-derived INDEX
redaction), R39 (deliver/CI request budget), R42 (body-marker verification), R45 (secret-scan chokepoint),
R28 (visibility/destination resolver), R33 (single pinned backend), R9/R35 (canonical body), and PRD 045 R70
(deliver issue-batch journal / runId), R22 (deliver annotations), R21 (gap labels). New hardening
requirements use the program-allocated band **R80–R99** (PRD 043 Program table); cross-PRD references are
written `PRD 0NN RNN`.

This PRD completes the interim posture recorded in PRD 043 R34/D5b (file/pointer-derived INDEX until this
lands); it supersedes R34's interim issue-derived clause with a committed, reconciler-read-only projection —
not PRD 043 R7 (no-stub-files), which still holds.

## Adopter impact

- **P-A — Default file-store user.** Inert. The PRD 031/032/033 file-store planning graph, reconciler,
  `inFlight` committed region, and `/sw-deliver next` are byte-for-byte unchanged (PRD 043 R1/R3).
- **P-B — Greenfield issue-store adopter.** Primary beneficiary: an always-fresh planning graph derived from
  issues, a scheduler that runs from issue truth, cross-clone in-flight visibility, and zero stub-file drift.
- **P-C — Shared multi-project planner.** Gains cross-project recall (R90) but is the highest-risk surface for
  private-title leakage into a derived INDEX (R82/R84) and cross-project rationale exposure (R90); both fail
  closed.

## Goals

- Derive INDEX/living-status and drive the scheduler from issue queries when issue-store is active, with no
  authoring stub files (R25), at parity with file-store semantics.
- Keep in-flight work visible across clones by projecting the deliver-owned `inFlight` tuple into the
  committed INDEX (read-only) so PRD 032's cross-clone contract holds without stub files (R80/D22).
- Map task lists to provider epic + sub-issue hierarchy with a portable checkbox fallback and consistent
  parent/child status (R23/R91).
- Keep every derived view within a documented, per-provider request budget that fails closed rather than
  serving a partial or stale graph (R81/R85/R86).
- Never leak private artifacts through the derived INDEX, the query cache, or cross-project recall
  (R82/R84/R90).

## Non-Goals

- The backend, freeze, identification, canonical hashing, the R34 matrix *contract* (PRD 043).
- Dev-tracking transport: gap lifecycle, safe close-on-merge, doc-review comments, PR annotation authoring,
  milestones (PRD 045). 046 **reads** issue state/labels and annotations; it does not author them.
- Migration of incumbent file artifacts (PRD 044); 046 consumes the 044 cutover, it does not perform it.
- Jira (PRD 047). Changing the file-store planning-graph behavior (PRD 031/032/033) when issue-store is
  inactive.

## Requirements

### Scheduler and derived INDEX (owned)

- **R25** — Status/tier/priority labels drive the planning scheduler (`/sw-deliver next`), and the planning INDEX/living-status is a **read-only derived view** of issue queries when issue-store is configured, per the PRD 043 R34 region-disposition contract and PRD 043 R43 redaction. 046 derives from issue state/labels and the PRD 045 R22 annotations; it never authors them.

### Task hierarchy (owned)

- **R23** — Task lists map to a provider epic + sub-issue-per-phase where supported (PRD 043 R30/R31 capability matrix), degrading to a checkbox / body-encoded phase list where not; deliver updates sub-issue or checkbox state as phases merge under the PRD 043 R39 + PRD 045 R70 transaction/budget model.

### Region disposition and committed inFlight (R80)

- **R80** — A region-disposition matrix implements the PRD 043 R34 contract for issue-store mode: `structural` and `derived` INDEX rows are issue-derived read-only projections, and the deliver-owned `inFlight` tuple is **written to run-state (sole writer) and projected read-only into the committed INDEX `inFlight` region** (reconciler/authoring-guard read-only), so PRD 032's cross-clone CAS/lease contract is satisfied from committed git state — not run-state alone, which is git-ignored and invisible across clones. An optional tracking issue is an additional read-only projection. The projection is written at deliver run-start and on each phase transition; run-state is the single authority; a divergence doctor fails closed on run-state ↔ projection ↔ tracking-issue skew. No authoring stub files are created (PRD 043 R7). The `inFlight` region is never mechanically edited (it remains the deliver writer's sole region).

### Request budget, cache, and fail-closed derivation (R81–R86, R88, R93)

- **R81** — A request-budget model bounds derived-view cost: per-operation call counts, a maximum pagination depth, and a query cache TTL keyed on content-hash, documented per provider against its rate-limit floor (GitHub secondary limits; GitLab; Jira) so a full INDEX refresh has a known ceiling. This budget covers derived-view/INDEX refresh and **composes with** (does not replace) the PRD 043 R39 deliver/CI floor and PRD 045 R74 multi-issue batch budget via a shared accounting ledger; scheduler-critical budget is reserved separately from bulk refresh.
- **R82** — Issue-derived INDEX rows resolve visibility via the PRD 043 R43 + PRD 034 R4 resolver **at ingest**: `private`/`memory` units always emit opaque titles (`{id}: [private]`) and id/status/edges only — never sensitive titles or bodies in the tracked code-repo projection. Edge metadata for private/`memory` units is redacted per PRD 043 R29 (edges are not semantically anonymized; high-sensitivity units route to a private store).
- **R83** — `discover_units` is **backend-pluggable** (`file` | `issue`) and is the single shared source for `planning_index_gen`, `inflight_signal`, `authoring_guard`, and the PRD 033 reconciler/scheduler; the issue-store source feeds the same visibility-resolution and discovery path before any issue-mode INDEX/inFlight/scheduler behavior is enabled.
- **R84** — The R81 cache stores **only post-redaction projections** — never raw private titles, bodies, or edge blocks; the secret-scan chokepoint (PRD 043 R45) runs on issue-derived ingest (`issue-get`/`search` canonical form) **before** redaction and **before** any cache write; the cache key is namespaced (`projectKey + queryFingerprint + generationEpoch`), distinct from the artifact canonical-hash namespace.
- **R85** — Cache invalidation is **poll-on-reconcile** (no webhook dependency): a cache hit at deliver run-start and at `/sw-deliver next` revalidates live issue open/closed state + labels against lightweight search metadata (`updated_at`/content-hash); a scheduler must never schedule a frozen or closed unit from a stale entry; a TTL floor plus forced-refresh triggers (post-mutation, deliver run-start) bound staleness.
- **R86** — Partial or paginated derivation **fails closed**: a pagination ceiling reached with more results (`hasNextPage`) marks the refresh `index-incomplete`; the scheduler/reconciler refuse to publish or consume a partial INDEX without an explicit, operator-acknowledged degraded mode, inheriting the PRD 043 R39 halt semantics. Budget exhaustion mid-refresh is a fail-closed `index-incomplete`, never a silent truncation.
- **R88** — Concurrent INDEX regeneration is serialized by a single-writer lock or a monotonic generation token (PRD 035 both-region pattern); readers reject a non-monotonic generation so a torn derived projection is never consumed.
- **R93** — Request-budget usage is operator-observable: counts-only logging (no bodies/tokens), an alert threshold before the ceiling is breached, and a documented throttle/halt surface so a shared high-churn store degrades visibly rather than silently.

### Cutover and parity (R87, R92)

- **R87** — The 043→046 cutover is single-authority and gated: exactly one `discover_units` source per run (run-pinned backend, PRD 043 R33); a per-region mutual-exclusion authority in the R80 matrix; an explicit quiesce coordinated with PRD 044 migration so file-derived and issue-derived regions are never simultaneously authoritative; a doctor detects dual-source; and the legacy `INDEX.md` disposition (deleted, pointer-only, or reconciler-regenerated read-only) is defined for the cutover.
- **R92** — A parity fixture asserts the issue-derived INDEX/living-status **semantically** matches file-store output (not byte-compare, since projections differ in form); the reconciler divergence doctor fails closed when issue-derived and committed projections disagree beyond tolerance.

### Hierarchy integrity and recall (R89–R91, R94)

- **R89** — An `inFlight` tracking issue (R80) routes through the PRD 034 `redact_inflight_tuple` + resolver: opaque title/body for `private`/`memory` units, a confidential issue type where supported, and **refusal** to create a tracking issue for a private/`memory` unit on a public or shared store (PRD 043 R28 fail-closed).
- **R90** — Cross-project recall implements **PRD 043 R27**: recall queries are scoped by source `projectKey` + caller authorization; pointer dereference passes through `memory-redact` on read so project B cannot retrieve project A's private rationale or raw issue excerpts; a deterministic ranking/tie-break is defined when multiple projects match; deliverable content is never duplicated into memory.
- **R91** — Epic/parent status is the **aggregate** of its children: label reconciliation runs on read; the derivation fails closed when an epic's children contradict the parent's tier/status; on hierarchy conflict the body-encoded `sw-edges` block (PRD 043 R47) is authoritative and native links/sub-issues are reconciled-on-read projections.
- **R94** — Epic/sub-issue projection is bound to the PRD 043 R31 capability matrix with a per-provider verb table (which verbs are REST vs capability-gated GraphQL per PRD 043 R50), a per-phase API-call budget (R81), and a mandatory checkbox/body fallback when sub-issues are unavailable (including GitHub-only deployments); an absent capability degrades with a documented operator notice, deliver continues.

(R95–R99 reserved for this PRD's band.)

## Technical Requirements

- `discover_units` gains an issue-store source (R83) feeding `planning_index_gen`/`planning_graph` so the
  reconciler, scheduler, `inflight_signal`, and `authoring_guard` are backend-agnostic and share one
  visibility-resolution path.
- `inFlight` disposition (R80): deliver writes the tuple to run-state and projects it read-only into the
  committed INDEX `inFlight` region (and an optional tracking issue); the committed projection is the
  cross-clone surface PRD 032 reads; CAS/lease semantics are preserved against the committed region.
- Query cache (R84): post-redaction projections only; key `projectKey + queryFingerprint + generationEpoch`;
  secret-scan on ingest; generation token for monotonic reads (R88).
- Budget ledger (R81/R93): shared accounting with PRD 043 R39 and PRD 045 R74; per-provider ceilings; alert
  threshold; `index-incomplete` signal consumed by scheduler/reconciler (R86).
- Epic/sub-issue projection via the PRD 043 R31 capability matrix (R94); checkbox/body fallback otherwise.
- Cross-project recall (R90): project-scoped memory queries through the recall provider; `memory-redact` on
  dereference.
- New capability-index entries: issue-derived INDEX, epic/sub-issue verbs, linked-PR (GraphQL gate), cache,
  and concurrency, registered in `core/sw-reference/capability-index.json`.

## Security & Compliance

- **Derived-INDEX redaction (R82) + cache safety (R84).** Resolver-at-ingest, opaque private titles, edge
  redaction; cache holds only post-redaction projections; secret-scan (PRD 043 R45) on issue-derived ingest.
- **inFlight projection (R80/R89).** Committed projection and tracking issue carry only redacted tuples;
  private/`memory` units are opaque or refused on public/shared stores (PRD 043 R28).
- **Cross-project recall (R90).** ProjectKey-scoped, authorization-checked, `memory-redact` on read.
- **Stale-cache safety (R85).** Live revalidation prevents scheduling a frozen/closed/private-mutated unit.
- **Token scope.** Any GraphQL verb used for derivation (R94) adds minimum scopes to the PRD 043 R44/R37
  scope table, probed at init; counts-only budget logging (R93).
- **Residual risks.** Application-layer `projectKey` scoping (PRD 043 R11/R42) is not provider-enforced
  authorization; GitHub lacks per-issue privacy (PRD 043 R28), so private units on a code-repo issue store
  require a separate private planning repo; edge metadata is not semantically anonymized (PRD 043 R29).

## Testing Strategy

- **Derived INDEX + scheduler (R25/R92):** issue-derived INDEX/living-status semantically matches the
  file-store parity fixture; `/sw-deliver next` schedules from issue labels.
- **Committed inFlight (R80/D22):** deliver writes run-state and a committed read-only projection readable
  from a second clone; PRD 032 CAS/lease holds; divergence doctor fails closed; no stub files.
- **Budget + fail-closed (R81/R86/R93):** a full refresh stays within the per-provider ceiling; a pagination
  ceiling with `hasNextPage` yields `index-incomplete` and the scheduler refuses a partial INDEX; budget
  alert fires before breach.
- **Cache safety (R82/R84/R85):** a private unit is opaque in the derived INDEX; the cache never stores/serves
  a raw private title/body; a secret in an issue body is caught on ingest; a stale cache hit is revalidated
  and a closed/frozen unit is not scheduled.
- **Hierarchy (R23/R91/R94):** epic/sub-issue projection on a supporting provider, checkbox fallback on a
  non-supporting one; parent status aggregates children and fails closed on contradiction.
- **Recall (R27 via R90):** cross-project rationale is discoverable via memory pointers without deliverable
  duplication; project B cannot retrieve project A's private rationale.
- **Concurrency + cutover (R88/R87):** concurrent regeneration is serialized by generation token; the cutover
  leaves a single authoritative `discover_units` source with no dual INDEX.
- **Doc-impact fixture:** `run-planning-046-doc-impact-fixtures.sh` asserts per-phase doc updates.

## Success Criteria

1. With issue-store active, the operator runs `/sw-deliver next` and `/sw-status` from issue-derived state
   with no stale file INDEX and zero planning stub files; the INDEX is a read-only projection.
2. In-flight work is visible across clones: the committed `inFlight` projection (and optional tracking issue)
   reflects run-state and satisfies PRD 032's cross-clone CAS; the reconciler derives `in-progress`
   correctly.
3. A full INDEX refresh stays within the documented per-provider budget; on budget or pagination exhaustion
   the system fails closed (`index-incomplete`) and never schedules from a partial or stale view.
4. Private units appear in the derived INDEX as opaque metadata only; the cache never serves unredacted
   private data, and issue-derived ingest passes secret-scan.
5. Task lists render as epic + sub-issues where supported and as a checkbox fallback otherwise, with parent
   status aggregating children and failing closed on contradiction.
6. Cross-project recall returns linked rationale via project-scoped, redacted memory pointers with zero
   deliverable duplication; another project's private rationale is never surfaced.
7. Issue-derived INDEX/living-status matches file-store semantics on a parity fixture, and the 043→046
   cutover leaves a single authoritative source with no dual INDEX.

## Rollout Plan

Per-phase documentation-impact gate backed by `run-planning-046-doc-impact-fixtures.sh` (precedent PRD
034/035/043/045). Each phase updates its affected docs before shipping (PRD 043 R49).

1. **Backend-pluggable discovery + region disposition + committed inFlight** (R80, R83, R87, R88, D22).
   *Docs:* `.sw/layout.md` (+ `core/sw-reference/layout.md` sync) dual-mode INDEX regions + region-disposition,
   `core/skills/living-status/SKILL.md`, `core/skills/deliver/SKILL.md` (inFlight projection),
   `core/skills/shipwright-state/SKILL.md`, `core/skills/conductor/SKILL.md`,
   `core/sw-reference/planning-unit.schema.json` + `inflight-tuple.schema.json`,
   `docs/guides/workflows.md` (planning lifecycle), `core/commands/sw-doc.md` + `core/skills/git-workflow/SKILL.md`
   + `core/rules/sw-git-conventions.mdc` (mechanical-region note: inFlight never mechanical in both modes).
   *Exit:* parity fixture green for `structural`/`inFlight`; cutover quiesce + single-source verified.
2. **Derived INDEX + redaction + budget + cache safety** (R25, R81, R82, R84, R85, R86, R93).
   *Docs:* `core/commands/sw-deliver.md` (issue-store scheduler), `docs/guides/configuration.md` +
   `core/sw-reference/config.schema.json` (+ mirror) `issue-store` backend + request-budget/cache-TTL keys,
   `core/providers/planning-store/issue-store.md` (new) + `core/providers/planning-store/CAPABILITIES.md`,
   `core/sw-reference/capability-index.json`, `core/skills/visibility/references/emission-points.md`.
   *Exit:* redaction negative fixture on the issue-query path; budget-ceiling fail-closed test.
3. **Hierarchy + recall** (R23, R91, R94, R27 via R90, R89). *Docs:* `core/skills/deliver/SKILL.md`
   (hierarchy phase updates), `core/skills/memory/SKILL.md` + `core/providers/recallium.md` (recall pointers,
   org-internal URL redaction), `core/sw-reference/capability-index.json` (hierarchy verbs),
   plus `docs/guides/workflows.md`/`commands.md`/`getting-started.md` and `README.md` issue-derived-graph notes.
   *Exit:* epic/checkbox fallback + cross-project recall negative fixture green.

## Decision Log

- **D22** — `inFlight` authority: run-state is the sole writer; the committed INDEX `inFlight` region is a
  deliver-owned **read-only projection** (the cross-clone surface PRD 032 reads), with an optional tracking
  issue as a further read-only projection — reconciling PRD 032's committed region with PRD 043 R7 (no
  authoring stub files). Earlier drafts wrote `inFlight` only to run-state; that failed PRD 032's cross-clone
  contract and is rejected.
- **D23** — Planning-graph derivation is a dependent PRD; PRD 043 ships a file/pointer-derived INDEX as the
  bounded interim (R34) until this lands. 046 supersedes R34's interim issue-derived clause with a committed
  read-only projection — not PRD 043 R7.
- **D24** — Derived views are read-only projections: 046 queries issue state/labels and PRD 045 annotations
  but never authors deliver annotations, PR linkage, gap lifecycle, or close-on-merge (PRD 045). The 046
  budget composes with, and does not replace, PRD 043 R39 and PRD 045 R74.

## Open Questions

None blocking. Resolved during `/sw-tasks`: the exact committed `inFlight` projection + tracking-issue tuple
schema (against the PRD 032 schema), the per-provider cache TTL and pagination-ceiling values (with worked
ceiling math), and the per-provider epic/sub-issue verb mapping (REST vs GraphQL per PRD 043 R50).
