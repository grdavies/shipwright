---
absorbs: [gap-001-gap-capture-must-not-write-local-gap-backlog-whe, gap-028-planning-visibility-profile-names-conflate-redac, gap-029-issue-store-gates-must-use-store-host-privacy-fo, gap-030-issue-store-should-use-provider-labels-instead-o, gap-031-shared-planning-repos-need-product-source-tags-a, gap-032-deliver-terminal-should-auto-capture-unaddressed, gap-034-terminal-pr-and-release-please-changelog-titles-, gap-035-init-should-auto-configure-gitignore-and-cutover, gap-036-audit-sw-deliver-chain-for-planning-store-artifa, gap-039-gitlab-issues-provider-marked-shipped-without-a-, gap-040-spec-seed-must-not-regenerate-tracked-local-inde, gap-041-living-reconcile-must-not-write-local-derived-pl, gap-042-gap-resolution-must-update-gap-issues-not-local-, gap-043-issue-query-cache-must-detect-new-remote-units-b, gap-044-issue-store-put-must-rewrite-chunk-manifest-with, gap-045-issue-store-put-must-use-provider-aware-chunking, gap-046-doctor-must-validate-privacy-ack-recording-and-k, gap-047-dispatch-preflight-must-resolve-a-concrete-model, gap-048-scheduler-next-must-skip-units-without-runnable-, gap-049-planning-graph-must-reconcile-stale-schedule-hin, gap-050-memory-backend-must-round-trip-planning-bodies-t]
amends: []
brainstorm: docs/brainstorms/2026-07-06-planning-store-hardening-requirements.md
date: 2026-07-06
updated: 2026-07-06
revision: 2
depends: [056-prd-issue-store-deliver-progress-native-links, 046-prd-issue-store-planning-graph, 043-prd-issue-backed-planning-store]
topic: planning-store-hardening
visibility: public
---
# PRD 057 — Planning store hardening

## Overview

Shipwright can store planning artifacts (brainstorms, PRDs, task lists, gap units, amendments) in an
issue-backed remote store instead of tracked files in the local repository. PRD 056 established the
authoring→store path, native provider links, deliver progress sync, and doctor fail-closed behavior on
local planning writes. This unit hardens that foundation by closing **21 open, unabsorbed gaps** across
six concern clusters (A–F) plus four cross-cutting invariants.

The goal is to make the remote planning store a first-class, vendor-neutral option that (a) keeps the
local repository free of tracked planning artifacts and gitignored-state CI false failures, (b) keeps
inter-artifact edges (brainstorm↔PRD↔tasks↔gaps↔amendments) accurate as work moves from idea to
implementation by writing through to the authoritative store, and (c) returns the operator to a clean,
correct working state fastest by sequencing correctness and pollution blockers ahead of polish.

Requirements trace to brainstorm **R1–R24** and are carried forward verbatim in intent below, then
extended by hardening requirements **R25–R32** synthesized from the review panel (multi-writer
concurrency, store-write integrity, operability/rollback, and documentation currency). This unit
**depends on and extends the PRD 056 union R1–R20** (core R1–R10; A1–A2 R11–R16; A3 R17–R20, issue #223)
and does not restate PRD 056 requirements (see R22). Delivery order assumes PRD 056 lands first.

PRD 056 is authoritative in the issue store (`grdavies/planning`, issue #218) and is **not materialized
as a tracked file** under `docs/prds/`; local traceability and non-duplication checks (R22) load the 056
union from the store rather than from the repo tree. A frozen local copy that ends at R16 is a stale
projection — the authoritative union is R1–R20 per the derivation above and MUST NOT be shrunk to match
that stale copy.

## Goals

- Stop local-repo pollution: no tracked `GAP-BACKLOG.md`, `INDEX.md`, `INDEX-archive.md`, `SUPERSEDED.md`,
  or legacy projections written when the effective backend is an issue-store in `separate-project` mode
  (in `same-repo` mode the local repo *is* the store, so local derived writes are retained).
- Keep currency: gap resolution and reconciliation update the authoritative store (issue close + labels),
  not just local frontmatter, with defined partial-failure handling.
- Harden robustness across writers and vendors: correct chunk-manifest reassembly, provider-aware Jira
  chunking, query-cache detection of new remote units before TTL expiry, atomic multi-writer gap-number
  allocation, and integrity of concurrent and partial store writes.
- Restore normal operation by clearing the live blockers: the scheduler frontier stall on legacy units
  without runnable task lists (R16), `gitlab-issues` advertised as shipped without a live adapter (R7), and
  the dispatch-preflight `binding:no-model` failure that forces inline authoring (R18).
- Unblock migration early: model privacy and configuration correctly as three orthogonal axes, probe
  store-host privacy for every shipped provider, validate privacy-ack recording, and land these migration
  gates in an early wave so adopters can cut over rather than staying on the polluted local path.
- Add provider-native polish (labels-as-metadata, human-readable titles, product source tags) and
  workflow/DX polish (terminal gap auto-capture, feature-named PR/changelog titles, memory round-trip).
- Make delivery operable and reversible: deterministic CI degraded mode when no store token is present,
  per-wave rollback with a no-data-loss guarantee, and documentation that ships in the same wave as the
  behavior it describes.
- Preserve file-store byte-identical behavior when the effective backend is not an issue-store (R23).

## Non-Goals

- Re-implementing or restating the PRD 056 union R1–R20; this unit depends on and extends them (see R22).
- Delivering PRD 056-owned territory: native provider-link adapter wiring (gap-037), in-loop deliver
  progress sync (gap-033), doc-command store routing and the `separate-project` docs-worktree skip
  (gap-002 / gap-003), and deliver-entry materialization (PRD 056 R16). This unit depends on those and only
  adds local-write guards plus the gap-specific hardening enumerated here.
- Implementing a live GitLab Issues adapter: per D1 this unit delivers demotion / fail-closed only; the
  live `planning_gitlab_client.py` adapter is deferred to a follow-up unit.
- Remediating PRD 056-owned findings surfaced by the R6 audit: the deliver-chain audit MAY catalog
  056-owned findings (progress sync, native links, freeze/distill) but fixing them is out of 057 scope and
  tracked under PRD 056 / follow-up gaps; R6 produces the matrix and CI fixture only.
- Changing file-store (non-issue-store) behavior in any observable way (see R23).
- Changing freeze, PRD drafting, task generation, commit/push, or the orchestrator store-put sequencing;
  those surfaces are out of scope and handled by downstream commands and the orchestrator (brainstorm
  Scope Boundaries).
- The PRD 046 deliver-retro issues (merge-enqueue stalls, gap-check status not written by subagents,
  post-merge verify hangs) except where they directly intersect planning-store writes.
- Introducing a new memory provider or a new issue provider beyond GitHub Issues and Jira (shipped) and
  GitLab Issues (deferred / fail-closed per R7 / D1).
- Polish beyond the enumerated gaps (for example richer native-link rendering or additional
  provider-native projections) unless raised as a new gap and absorbed explicitly.

## Requirements

Requirements are grouped by cluster and carry their originating gap id for absorbs-edge traceability.
Wave assignments are in the Rollout Plan and honor the sequencing invariant R24.

### Cluster A — local pollution & currency

- **R1** Gap capture SHALL write through to the authoritative issue-store and SHALL NOT write or update the local `GAP-BACKLOG.md` projection when the effective backend is an issue-store in `separate-project` mode; `refresh_gap_backlog_projection` SHALL skip local writes under that backend, an optional `--projection` flag SHALL retain the legacy local projection for backward compatibility only, and the projection SHALL be reduced to a documented sunset state when no open gaps remain. In `same-repo` mode local projection writes are retained. *Acceptance:* under issue-store `separate-project`, a capture produces the store issue and no `GAP-BACKLOG.md` mutation; with `--projection` the legacy row is also written; `same-repo` output is unchanged (gap-001).
- **R2** `wave_spec_seed.py` SHALL NOT regenerate or write the tracked local `docs/prds/INDEX.md` when the effective backend is an issue-store in `separate-project` mode; the currently unconditional index writes (`ensure_redacted_index` and the seed-time write) SHALL be guarded by the effective backend (gap-040).
- **R3** `planning_reconcile.py reconcile_core` SHALL NOT write tracked local derived planning artifacts (`INDEX.md`, `INDEX-archive.md`, `SUPERSEDED.md`, or the legacy projection) when the effective backend is an issue-store in `separate-project` mode; reconciliation SHALL instead update the authoritative store (per PRD 056 R8) and MAY route derived artifacts through a gitignored cache when cutover regions are issue-authoritative — never a tracked local write. In `same-repo` mode local derived writes are retained (gap-041).
- **R4** Gap resolution SHALL update the corresponding gap issue in the store — closing it and applying the resolution label — rather than editing local frontmatter only, when the effective backend is an issue-store in `separate-project` mode; `reconcile_lib.set_index_status` and `gap_backlog.resolve_for_prd` SHALL perform the issue close and label operations idempotently, and a partial failure (close without label, or label without close) SHALL surface a `resolution-partial` verdict with doctor reconciliation of the open-issue-plus-resolved-label mismatch. In `same-repo` mode local frontmatter and row edits are retained (gap-042).
- **R5** `/sw-init` SHALL auto-configure `.gitignore` for planning-store operation via `gitignore-generate`, and the cutover gate signal SHALL be recorded in a committed form that CI can derive so that the gitignored state file (`.cursor/hooks/state/planning-cutover-gate.json`) no longer produces CI false failures (gap-035).
- **R6** The full `/sw-deliver` chain SHALL be audited for planning-store artifact emission parity, producing a published command×artifact×backend matrix, and a CI fixture SHALL assert that no file-store-only write path executes when the effective backend is issue-store authoritative (gap-036).

### Cluster B — vendor neutrality & robustness

- **R7 (BLOCKER)** `gitlab-issues` SHALL either be implemented at parity with a live adapter (`scripts/planning_gitlab_client.py` wired into `issues_lib._live_backend`) or be removed from `SHIPPED_ISSUES_PROVIDERS` and demoted to a deferred, fail-closed state; the current advertised-but-unimplemented condition at `planning_store.py:43` SHALL NOT persist (gap-039).
- **R8** Issue-store `put` SHALL rewrite the chunk manifest with the provider-assigned comment ids after posting overflow comments so that `planning_canonical.py` reassembly never selects stale comments after repeated large updates; the synthetic ids used during composition SHALL be replaced with the real provider ids returned by the client (gap-044).
- **R9** Issue-store `put` SHALL use provider-aware chunking for Jira in the standard write path, matching the Jira payload-size limits already special-cased in the migration path, so that oversized bodies are chunked before the Jira client rejects them (gap-045).
- **R10** The issue query cache SHALL detect new remote units created by other writers before the TTL expires: revalidation SHALL invalidate the cache when the live unit-id set differs from the cached set (symmetric set diff), not only when a known cached unit changes, and `planning_discover.discover_units_issue` SHALL revalidate before returning cached projections (not only `planning_scheduler`), so that multi-writer stores and gap-number allocation observe newly created units without waiting for cache expiry or a manual force-refresh (gap-043).
- **R11** The issue-store SHALL use provider-native labels to carry planning metadata instead of embedding YAML frontmatter in issue bodies, SHALL render human-readable issue titles without the `[planning] type:unit-id` prefix, and SHALL treat the provider-assigned id as a storage pointer only — the planning `unit-id` remains authoritative for edges and gap sequence, and `gap-NNN` SHALL NOT be derived from a provider issue number. Read and discover paths SHALL project unit metadata from labels with body fallback; R11 SHALL land write-side before the read cutover with a one-release dual-read (labels + frontmatter) window and a backfill for existing issues; and multi-value edges (`depends` / `absorbs`) SHALL be encoded within provider label-cardinality limits (gap-030).
- **R12** Shared planning repositories SHALL support product source tags of the form `sw:source:<owner>/<repo>` with filterable scoping applied in discovery, scheduler, and gap-capture; the default scope SHALL include untagged legacy units and surface a `sw:source-missing` doctor warning rather than silently hiding them, and the differences between Jira and GitHub scoping semantics SHALL be documented (gap-031).

### Cluster C — privacy & config gates

- **R13** Visibility configuration SHALL model three orthogonal axes — visibility (redaction) tier, `storeLocation`, and store-host privacy — with a tier-first rename that keeps one release of back-compat for existing profile names, and `probe_remote_visibility` SHALL NOT be the sole migration gate (gap-028).
- **R14** Issue-store gates SHALL evaluate store-host privacy via `probe_store_host_privacy` for every shipped provider with no placeholder always-false branches, and the `SW_STORE_HOST_PRIVACY` override SHALL be honored only in CI contexts (gap-029).
- **R15** The doctor SHALL validate privacy-ack recording and key naming — flagging a live config with `privacyAck.required: true` and `recordedAt: null`, reconciling the notice-doc `ackedAt` wording against the `recordedAt` key that `planning_visibility.py` writes, and emitting the exact remediation command in each finding (gap-046).

### Cluster D — scheduler & graph

- **R16 (BLOCKER)** The scheduler `next` operation SHALL skip units that have no runnable (frozen) task list — emitting skip-with-reasons — instead of failing the whole frontier, and SHALL provide a park/defer mechanism so that legacy migrated units (for example `003-prd-pr-agent-review-provider`) no longer block scheduling. This SHALL be implemented in both `next` paths: the file-path-based `planning_deliver_gate.cmd_next` (which `planning-graph.py next` delegates to via `wave_deliver.py`) gains skip-with-reasons, and the issue-store `planning_scheduler` frontier honors the `sw:parked` label and unrunnable filtering (gap-048).
- **R17** The planning graph SHALL reconcile stale schedule hints by validating each unit's `schedule:` hint (or `sw:gap-schedule:*` label) against its actual `absorbs` edges, and SHALL surface a `sw:schedule-stale` signal when a hint targets one unit (for example a unit whose `schedule:` still points at `056-prd-issue-store-deliver-progress-native-links`) while its `absorbs` edges now resolve elsewhere (gap-049).

### Cluster E — workflow & DX

- **R18** Dispatch preflight SHALL resolve a concrete model for unmapped agents running under an `inherit` orchestrator — falling back to `models.roles` or emitting an actionable remediation — so that `wave_preflight cmd_dispatch` no longer fails with `binding:no-model` (for example `--agent explore --command sw-doc`) and no longer forces inline authoring (gap-047).
- **R19** The `/sw-deliver` terminal SHALL scan the run log and loop-health at termination and auto-capture unaddressed planning-store pain as gap units via `planning_gap_capture` with deduplication against open gap titles (not only signal ids), requiring human confirmation before capturing substantial items; capture SHALL be suppressed when the deliver verdict is fail or aborted, SHALL cap the number of captures per run, and SHALL apply a defined substantial-vs-noise heuristic so a broken wave does not flood the shared planning repo (gap-032).
- **R20** Terminal PR titles and release-please changelog titles SHALL name the landed feature — derived from the PRD title or task-list slug — instead of always emitting `feat(prd-<n>): deliver wave` from `commitlint_safe_title` (gap-034).
- **R21** The memory backend planning-body path SHALL be corrected in two stages: (21a, near-term) the local-only `.cursor/sw-memory/planning-bodies/` behavior SHALL be renamed and documented so its local-only, gitignored nature is explicit and no longer presents as a provider round-trip, removing the CI false-failure and misleading-durability surface; and (21b, later) the backend SHALL implement a true provider round-trip through the memory adapter with a local cache. 21a lands in an early wave; 21b lands with the workflow-polish wave (gap-050).

### Cluster F — concurrency, integrity & operability (hardening)

- **R25** Gap-number allocation SHALL be atomic under multi-writer conditions: gap capture SHALL claim a gap id by create (treating a provider create-conflict or duplicate `unit-id` as a collision) or retry-on-collision by invalidating the query cache, re-reading the live unit set, and re-allocating, so two concurrent writers never persist duplicate gap ids or split `absorbs` edges. *Acceptance:* a multi-writer fixture driving two concurrent `next_gap_number`+create sequences against one store yields two distinct gap ids with no duplicate, and allocation invalidates the query cache before reading (gap-043; adversarial P0).
- **R26** Issue-store `put` SHALL record a partial-write journal (unit-id, step, provider ids) enabling idempotent resume, and SHALL surface orphaned or incomplete puts — an orphan issue after a create failure, synthetic manifest ids after a failed rewrite, or missing labels/links after a body write — via `planning-doctor` as a `put-partial` finding with the exact remediation command; a failed manifest rewrite SHALL fail closed (issue left at prior etag or marked `sw:put-incomplete`), never leaving durable synthetic ids silently. *Acceptance:* a fixture injecting a failure after `issue_create` but before manifest rewrite leaves a resumable journal entry and a `put-partial` doctor finding, and a retry converges to one consistent issue with no duplicate (gap-044; adversarial P0).
- **R27** Concurrent chunked puts SHALL preserve manifest and comment consistency under last-writer-wins semantics: `put` SHALL apply body plus overflow-comment updates such that reassembly never interleaves chunks from two writers (a version token spanning the comment set, or delete-and-replace of the overflow comment batch under the body etag). *Acceptance:* a fixture interleaving two concurrent large puts reassembles to exactly one writer's body (no hybrid), and doctor flags any manifest/comment cardinality mismatch (gap-044; adversarial P0).
- **R28** The `sw:parked` mechanism SHALL define governance and exhaustion semantics: a parked unit SHALL carry a park reason (label or body annotation) and SHALL be parkable only by an actor authorized via a local config allowlist; when the eligible frontier is empty after skip/park filtering, the scheduler SHALL emit an explicit `scheduler-exhausted` halt (distinct from failure) naming the parked/unrunnable units and the unpark remediation, rather than returning silent empty output. *Acceptance:* a fixture with all frontier candidates parked or unrunnable produces a `scheduler-exhausted` halt with reasons, an unauthorized park attempt is refused, and doctor surfaces an over-parked-frontier drift finding (gap-048; adversarial P1).
- **R29** The tier-first visibility rename (R13) SHALL define a deterministic old→new precedence table for the one-release back-compat window: new keys SHALL win over deprecated aliases when both are present, a deprecated profile name SHALL emit a doctor deprecation warning, and a mixed old/new `workflow.config.json` SHALL never weaken the redaction default. *Acceptance:* a fixture seeding both deprecated and new keys resolves to the new-key value with a deprecation warning, and a fixture with only the deprecated key resolves identically to pre-rename behavior (gap-028; adversarial P1).
- **R30** Issue-store fixtures and guards SHALL behave deterministically when no store token (`planning.store.issues.tokenEnv`) is present in CI: file-store parity fixtures SHALL always run; issue-store integration fixtures SHALL gate on token presence as skip-with-advisory (never fail closed); and `planning-doctor` SHALL distinguish `store-token-absent` (advisory) from `probe-failed` (fail closed). *Acceptance:* a fixture run with the token env unset reports issue-store integration fixtures as skipped-with-advisory (green), runs all file-store parity fixtures, and doctor emits `store-token-absent` rather than `probe-failed` (gap-029; adversarial P1).
- **R31** Each delivery wave SHALL define a revert path and a no-data-loss statement: a wave's requirements SHALL be revertable by reverting the wave's code without loss of authoritative store data, an `effective-backend` kill-switch SHALL allow falling back to the prior behavior, and `planning-doctor` SHALL emit a `wave-regression` finding if a reverted wave leaves inconsistent local/store state. *Acceptance:* every wave entry in the Rollout Plan names its revert path and no-data-loss statement, and a fixture proves that reverting Wave N code with the kill-switch set restores prior behavior and re-materializes local projections from the store on demand (adversarial P1).

### Cross-cutting invariants

- **R22** This unit SHALL NOT duplicate the PRD 056 union R1–R20 (core R1–R10; A1–A2 R11–R16; A3 R17–R20, issue #223); where it relies on PRD 056 behavior it SHALL reference the PRD 056 requirement id rather than restating it, and a traceability check SHALL confirm that no restated PRD 056 requirement text appears as a new requirement. The check SHALL load the 056 union from the authoritative issue store (issue #218), not from any stale local projection (dependency invariant).
- **R23** For every guard, skip, or write-through added by this unit, the file-store code path SHALL remain equivalent to current behavior when the effective backend is not an issue-store, verified by per-command golden-output fixtures (gap capture, reconcile, spec-seed) with an explicit artifact list; byte-identity is required where practical and structural equivalence is permitted where only incidental formatting differs (parity invariant).
- **R24** This PRD SHALL organize requirements into delivery waves such that the blocker requirements (R7 / gap-039, R16 / gap-048) and the live workflow-blocker (R18 / gap-047) land in the earliest wave, and the Cluster A pollution stoppers (R1–R5), the freshness fix (R10), and the migration gates (R13–R15) land in the next wave, ahead of the polish requirements (R19 / gap-032, R20 / gap-034, R21b / gap-050). **R6 (full parity-audit closure) is exempted from the earliest-waves invariant** and lands in the final wave (D6 / D8) because its end-to-end matrix can only assert full parity after all guard waves land; to prevent late detection, **each wave SHALL ship incremental parity fixtures** covering the artifacts it guards, so pollution regressions are caught wave-by-wave rather than only at Wave 5 (sequencing invariant).
- **R32** Documentation SHALL ship in the same wave as the behavior change it describes: for each requirement, the operator-facing doc surfaces enumerated in the Documentation Impact section SHALL be updated in the wave that lands the behavior, verified by a `planning-057-doc-impact` fixture that fails when a behavior change merges without its paired doc update. *Acceptance:* the doc-impact fixture maps each requirement to its doc paths and asserts co-landing per wave (documentation-currency invariant).

## Technical Requirements

Pollution/currency guards (R1–R4) are conditioned on the **effective** backend **and**
`storeLocation.mode`, via a shared `issue_store_separate_project(root)` helper (built on
`resolve_store_location(...).mode`); `issue_store_effective` alone is insufficient because it does not check
mode (D9). When the effective backend is not an issue-store, every changed path MUST produce output
equivalent to today (R23: byte-identical where practical, structural equivalence where only incidental
formatting differs). Verified grounding line references reflect the code read during authoring and are
indicative anchors, not frozen contracts.

### Cluster A — local pollution & currency (gap-001, gap-040, gap-041, gap-042, gap-035, gap-036)

| Component | Change | Requirement |
| --- | --- | --- |
| shared predicate `issue_store_separate_project(root)` (new; via `planning_store.resolve_store_location(...).mode`) | Add and use across R1–R4 pollution/currency guards; `issue_store_effective` (`planning_migrate_issue_store.py:248`) alone is insufficient because it does not check `storeLocation.mode` | R1, R2, R3, R4 |
| `scripts/planning_migrate_issue_store.py` — `refresh_gap_backlog_projection` (~403–423) | Return skip when issue-store + `separate-project`; write-through gap changes to the store; add optional `--projection` legacy flag; sunset the projection to a documented stub when no open gaps remain. `planning_gap_capture.py` is the caller only (imports the function) | R1 |
| `scripts/gap_backlog.py` (~329–367) | Route gap row updates to store records under issue-store `separate-project`; keep file writes for file-store and `same-repo` | R1, R4 |
| `scripts/wave_spec_seed.py` — `ensure_redacted_index` (~278–286) and seed write (~431–433) | Guard the `docs/prds/INDEX.md` writes behind the effective backend; skip under issue-store `separate-project` | R2 |
| `scripts/planning_reconcile.py` — `reconcile_core` (~391–442) | Guard INDEX / INDEX-archive / SUPERSEDED / legacy `project_all` writes behind the effective backend; project derived status to the store (per PRD 056 R8), or a gitignored cache when cutover regions are issue-authoritative — never a tracked local write | R3 |
| `scripts/reconcile_lib.py` — `set_index_status` (~245–294; local INDEX write at ~269–284) | On issue-store `separate-project`, call a shared `close_gap_issue(root, unit_id)` (issue close + resolution label) instead of the local INDEX/frontmatter edit; surface `resolution-partial` on partial failure | R4 |
| `scripts/gap_backlog.py` — `resolve_for_prd` (~370–381) | On issue-store `separate-project`, close the gap issue and apply the resolution label idempotently (factor the shared `close_gap_issue` reusing `planning_migrate_issue_store._apply_gap_labels` / `GAP_LABEL_RESOLVED` + `issues_lib.issue_update(..., state="closed")`) | R4 |
| `scripts/planning-doctor.py`, `gitignore-generate`, `/sw-init` | `/sw-init` runs `gitignore-generate --write` for planning-store paths; derive the cutover-gate signal from committed state | R5 |
| cutover-gate signal source (`planning_cutover.load_cutover_gate` (~36–47) and its consumers `planning_discover`, `planning_region_disposition`, ship harnesses) | Derive from `workflow.config.json` backend + structural markers (no new tracked file); stop reading `.cursor/hooks/state/planning-cutover-gate.json` as an authority in CI; update all `load_cutover_gate` call sites | R5 |
| new CI fixture `planning-deliver-parity-fixtures` + per-wave incremental parity fixtures | Assert no file-store-only write executes under issue-store authoritative backend; publish command×artifact×backend matrix; each wave ships incremental parity fixtures for the artifacts it guards | R6, R24 |

### Cluster B — vendor neutrality & robustness (gap-039, gap-044, gap-045, gap-043, gap-030, gap-031)

| Component | Change | Requirement |
| --- | --- | --- |
| `scripts/planning_store.py:43` `SHIPPED_ISSUES_PROVIDERS` | Remove `gitlab-issues` and demote to `DEFERRED`/fail-closed now (D1); follow-up unit adds the live adapter | R7 |
| `scripts/issues_lib.py` — `_live_backend` (~420–437) | Keep the fail-closed raise for unimplemented providers; ensure demotion surfaces a clear operator message | R7 |
| `scripts/planning_store.py` — `IssueStoreBackend.put` (~1272–1313) | Port the `planning_migrate_issue_store` post-pass (`rewrite_chunk_manifest`) into the standard put: after posting overflow comments and `issue_get`, rewrite the chunk manifest with real provider comment ids before persisting | R8 |
| `scripts/planning_canonical.py` — `reassemble_body` (~382–415) | Consume the rewritten manifest ids; never select stale comments after repeated large updates | R8 |
| `scripts/planning_canonical.py` — `chunk_body_if_needed` (~297–313), `scripts/planning_store.py` Jira put path | Apply provider-aware chunking for Jira in the standard write path (port `chunk_body_for_jira_cloud` from the migration path), matching migration-path payload limits | R9 |
| `scripts/planning_query_cache.py` — `revalidate_live_metadata` (~97–117), `scripts/planning_discover.py` — `discover_units_issue` (~291–325) | Revalidate the unit *set* via symmetric diff (`live` vs `cached` unit-id set), not only known units; call revalidation from `discover_units_issue` before returning cached projections | R10 |
| `scripts/planning_store.py`, `scripts/planning_canonical.py` — `_issue_record_to_unit` read path, `planning_jira_client.py` (~218–221, 265–268), `planning_github_client.py` | Serialize planning metadata as provider-native labels (write-side first); add a labels→unit read projection with body fallback and a one-release dual-read + backfill; render human-readable titles without `[planning] type:unit-id`; treat provider id as a storage pointer only (unit-id stays authoritative) | R11 |
| `scripts/planning_discover.py`, `planning_scheduler.py`, `planning_gap_capture.py` | Support and filter `sw:source:<owner>/<repo>` tags; default scope includes untagged units with a `sw:source-missing` doctor warning; document Jira vs GitHub scoping semantics | R12 |

### Cluster C — privacy & config gates (gap-028, gap-029, gap-046)

| Component | Change | Requirement |
| --- | --- | --- |
| `scripts/planning_visibility.py` — `resolve_default_profile` (~265–280) | Split into three axes (visibility tier / `storeLocation` / store-host privacy); tier-first rename with one-release back-compat alias map + deterministic precedence (new keys win) for existing profile names | R13, R29 |
| migration gate | Stop using `probe_remote_visibility` as the sole gate; incorporate `storeLocation` and store-host privacy | R13 |
| `scripts/planning_store.py` — `probe_store_host_privacy` (~826), `_store_host_privacy_override` (~750–754) | Evaluate store-host privacy for every shipped provider; remove placeholder always-false branches; gate the `SW_STORE_HOST_PRIVACY` override behind an explicit CI-context probe so it is honored only in CI (not operator runs). (This function lives in `planning_store.py`, not `planning_visibility.py`.) | R14 |
| `scripts/planning-doctor.py`, `core/sw-reference/planning-privacy-notice.md` | Flag `privacyAck.required: true` with `recordedAt: null`; reconcile notice-doc `ackedAt` wording against the `recordedAt` key that `planning_visibility.py` writes; emit exact remediation command per finding | R15 |

### Cluster D — scheduler & graph (gap-048, gap-049)

| Component | Change | Requirement |
| --- | --- | --- |
| `scripts/planning_deliver_gate.py` — `cmd_next` (~208–216), `task_list_for_unit` (~57) | Skip units with no frozen task list, emitting skip-with-reasons, instead of `fail("no frozen task list for unit …")`; honor a park/defer signal. `planning-graph.py next` (~44–45) delegates here via `wave_deliver.py` | R16 |
| `scripts/planning_scheduler.py` — `is_schedulable` (~79–85), frontier ordering | Under issue-store, honor the `sw:parked` label and unrunnable filtering so legacy units (e.g. `003-prd-pr-agent-review-provider`) drop out of the frontier (D4); this label-aware path is distinct from the file-path `planning_deliver_gate` path | R16 |
| `scripts/planning-graph.py` reconcile | Validate each unit's `schedule:` hint against its actual `absorbs` edges; surface `sw:schedule-stale` when mismatched | R17 |

### Cluster E — workflow & DX (gap-047, gap-032, gap-034, gap-050)

| Component | Change | Requirement |
| --- | --- | --- |
| `scripts/wave_preflight.py` — `cmd_dispatch` (~283–334), `scripts/resolve-model-tier.py` (~85–87, 140–144) | For `inherit` orchestrators with unmapped agents (e.g. `--agent explore --command sw-doc`), resolve in order: explicit agent map → `models.roles` secondary fallback → actionable remediation; stop failing with `binding:no-model` and stop forcing inline authoring. Document the precedence when command is `inherit` and the agent is unmapped | R18 |
| `scripts/wave_terminal.py` terminal, `planning_gap_capture.py` | At termination, scan run log + loop-health and auto-capture unaddressed planning-store pain as gap units with dedup against open gap titles; suppress on fail/abort verdicts; cap captures per run; human confirmation for substantial items | R19 |
| `scripts/wave_terminal.py` — `commitlint_safe_title` (~40–47), release-please title path | Derive the PR/changelog title from the PRD title or task-list slug instead of the fixed `deliver wave` text | R20 |
| memory backend / `providers/<memory.provider>.md`, `.cursor/sw-memory/planning-bodies/` | 21a: rename+document the local-only, gitignored behavior explicitly (stop presenting it as a round-trip). 21b: round-trip planning bodies through the provider adapter with a local cache | R21 |

### Cluster F — concurrency, integrity & operability (gap-043, gap-044, gap-048, gap-028, gap-029)

| Component | Change | Requirement |
| --- | --- | --- |
| `scripts/planning_gap_capture.py` — `next_gap_number` (~76–89), `scripts/planning_query_cache.py` | Invalidate the query cache before allocation; allocate by claim-by-create or retry-on-collision (provider create-conflict / duplicate `unit-id`); add a multi-writer collision fixture | R25 |
| `scripts/planning_store.py` — `IssueStoreBackend.put` (~1272–1313), `scripts/planning-doctor.py` | Add a partial-write journal (unit-id, step, provider ids) with idempotent resume; fail closed on manifest-rewrite failure (`sw:put-incomplete` / prior etag); doctor surfaces `put-partial` with remediation | R26 |
| `scripts/planning_store.py` — `put`, `scripts/planning_canonical.py` — `reassemble_body` (~382–415) | All-or-nothing body+comment update via a version token spanning the comment set (or delete-and-replace batch under the body etag); doctor flags manifest/comment cardinality mismatch | R27 |
| `scripts/planning-graph.py` frontier, `scripts/planning_scheduler.py`, `scripts/planning-doctor.py` | Park requires local-config allowlist + park reason; empty post-filter frontier emits a `scheduler-exhausted` halt (not silent empty); doctor over-parked-frontier drift finding | R28 |
| `scripts/planning_visibility.py` — alias map, `scripts/planning-doctor.py` | Deterministic old→new precedence (new keys win); deprecation warning for legacy names; mixed-config fixture proves the redaction default is never weakened | R29 |
| test harness gating (`scripts/test/…`), `scripts/planning-doctor.py` | File-store parity fixtures always run; issue-store integration fixtures skip-with-advisory when the token env is absent; doctor distinguishes `store-token-absent` (advisory) from `probe-failed` (fail closed) | R30 |
| `effective-backend` kill-switch (config/env), `scripts/planning-doctor.py`, materialize-from-store | Per-wave revert path; kill-switch restores prior behavior and re-materializes local projections from the store; doctor emits `wave-regression` on inconsistent local/store state | R31 |
| new fixture `planning-057-doc-impact` | Map each requirement to its Documentation Impact paths; fail when a behavior change merges without its paired doc update | R32 |

## Security & Compliance

- All issue/label/link operations use `planning.store.issues.tokenEnv` only; no new secrets in issue bodies,
  labels, titles, or comments.
- Provider-native labels (R11) and source tags (R12) MUST pass the existing secret-scan chokepoint
  (`_guard_write_secrets`) before any label or body is written.
- Store-host privacy (R14) MUST fail closed: an unprobeable or private-unknown host blocks migration; the
  `SW_STORE_HOST_PRIVACY` override is honored only in CI contexts, never in operator runs.
- Privacy-ack (R15) MUST be recorded (`recordedAt`) before a public-origin remote is used as a planning
  store; the doctor emits the exact remediation command when the ack is missing.
- Redaction tier decisions (R13) remain independent from placement decisions; separating the axes MUST NOT
  weaken any existing redaction default (public-origin remote continues to default to the most private tier),
  including during the mixed old/new config back-compat window (R29).
- Store-write integrity (R25–R27) MUST fail closed on partial writes: no duplicate gap ids, no orphan
  issues left unsurfaced, and no hybrid reassembled bodies from concurrent writers. Doctor is the surfacing
  channel (`put-partial`, cardinality-mismatch, over-parked-frontier, `wave-regression`).
- CI degraded mode (R30): a missing store token is an advisory (`store-token-absent`), never a silent pass
  and never a fail-closed `probe-failed`; the `SW_STORE_HOST_PRIVACY` override is honored only under an
  explicit CI-context probe (R14), never in operator runs.

## Testing Strategy

| Suite | Proves | Requirements |
| --- | --- | --- |
| `planning-deliver-parity-fixtures` (new) | Under issue-store authoritative backend, a full brainstorm→PRD→tasks→deliver cycle writes no tracked local planning artifact; publishes command×artifact×backend matrix | R1–R6, R23 |
| `planning-file-store-parity-fixtures` (new) | Per-command golden output (gap capture, reconcile, spec-seed) equivalent before/after every guard when backend ≠ issue-store; byte-identical where practical, structural equivalence where only formatting differs | R23 |
| `planning-gitlab-demotion-fixtures` (new) | `gitlab-issues` absent from shipped set; selecting it fails closed with a clear message | R7 |
| `planning-chunk-reassembly-fixtures` (extend) | Repeated large updates reassemble correctly using rewritten provider comment ids; no stale comments | R8 |
| `planning-jira-chunking-fixtures` (extend) | Oversized Jira bodies chunk in the standard write path before client rejection | R9 |
| `planning-query-cache-fixtures` (extend) | New remote units by other writers are visible before TTL expiry | R10 |
| `planning-native-labels-fixtures` (new) | Metadata serialized as labels; titles human-readable; provider id canonical where supplied | R11 |
| `planning-source-tag-fixtures` (new) | `sw:source:<owner>/<repo>` scoping filters discovery/scheduler/gap-capture | R12 |
| `planning-visibility-axes-fixtures` (new) | Three axes modeled and named distinctly; one-release back-compat alias resolves | R13, R14 |
| `planning-doctor-privacy-fixtures` (extend) | Doctor flags missing `recordedAt`, reconciles `ackedAt`/`recordedAt`, emits exact remediation | R15 |
| `planning-scheduler-frontier-fixtures` (extend) | `next` skips unrunnable/parked units with reasons rather than failing the frontier | R16 |
| `planning-schedule-hint-fixtures` (new) | Stale `schedule:` hints surface `sw:schedule-stale` against actual absorbs edges | R17 |
| `dispatch-preflight-fixtures` (extend) | `inherit` orchestrator + unmapped agent resolves a concrete model or emits remediation | R18 |
| `deliver-terminal-gapcapture-fixtures` (new) | Terminal auto-captures unaddressed pain as deduped gap units with confirmation gate | R19 |
| `terminal-title-fixtures` (new) | PR/changelog titles name the landed feature, not `deliver wave` | R20 |
| `memory-roundtrip-fixtures` (new) | Planning bodies round-trip through the provider adapter (or local-only is renamed/documented) | R21 |
| `spec-traceability-check` (extend) | No restated PRD 056 union R1–R20 text appears as a new requirement; loads 056 union from the authoritative issue store (issue #218) | R22 |
| `planning-gap-alloc-multiwriter-fixtures` (new) | Two concurrent allocate+create sequences yield distinct gap ids; cache invalidated before allocation | R25 |
| `planning-put-journal-fixtures` (new) | Failure after `issue_create` leaves a resumable journal + `put-partial` doctor finding; retry converges with no duplicate | R26 |
| `planning-concurrent-chunk-fixtures` (new) | Interleaved concurrent large puts reassemble to exactly one body (no hybrid); cardinality mismatch flagged | R27 |
| `planning-parked-governance-fixtures` (new) | All-parked/unrunnable frontier emits `scheduler-exhausted`; unauthorized park refused; over-parked drift finding | R28 |
| `planning-visibility-aliases-fixtures` (extend) | Deprecated+new keys resolve to new-key value with deprecation warning; deprecated-only matches pre-rename behavior | R29 |
| `planning-ci-token-absent-fixtures` (new) | Token env unset → integration fixtures skip-with-advisory (green), file-store parity always runs; doctor `store-token-absent` not `probe-failed` | R30 |
| `planning-wave-rollback-fixtures` (new) | Reverting a wave with the kill-switch restores prior behavior and re-materializes local projections; `wave-regression` finding on drift | R31 |
| `planning-057-doc-impact` (new) | Each requirement maps to its Documentation Impact paths; fails when behavior lands without its paired doc update | R32 |
| per-wave incremental parity fixtures | Each wave asserts no file-store-only write for the artifacts it guards (Wave 2: INDEX/GAP-BACKLOG; Wave 3: chunk/cache paths; …) so regressions surface wave-by-wave | R6, R24 |

## Rollout Plan

Waves honor R24: blockers and pollution stoppers first, polish last. Each wave is independently
shippable behind the effective-backend guard, preserving file-store parity (R23) throughout.

| Wave | Scope | Requirements | Rationale, operator milestone & revert path (R31) |
| --- | --- | --- | --- |
| **Wave 1 — blockers + run-unblockers** | Scheduler frontier skip/park + governance; `gitlab-issues` demotion; dispatch-preflight model resolution; CI token-absent degraded mode; per-wave rollback discipline | R7, R16, R18, R28, R30, R31 | Three live blockers (scheduling stall, fail-closed provider, forced inline authoring) prevent normal operation and store-backed authoring; clearing them restores scheduling, provider selection, and the `/sw-doc` explore-dispatch path. R28/R30/R31 establish park governance, token-absent CI determinism, and rollback from the first wave. **Milestone:** `planning-graph.py next` returns a runnable frontier and `/sw-doc` dispatch no longer forces inline authoring. **Revert:** restore `gitlab-issues` in `SHIPPED_ISSUES_PROVIDERS` / prior `cmd_next` hard-fail / prior dispatch binding; no store data written (parked labels reversible) — no data loss |
| **Wave 2 — pollution stoppers + freshness + migration gates** | Guard gap-capture/spec-seed/reconcile writes; gitignore + committed cutover signal; query-cache unit-set revalidation + atomic gap allocation; three visibility axes + alias precedence; store-host privacy; doctor privacy-ack; memory local-only rename/document | R1, R2, R3, R4, R5, R10, R13, R14, R15, R21a, R25, R29 | Stops tracked-artifact accumulation and gitignored-state CI false failures; the freshness fix (R10) and atomic allocation (R25) co-ship with gap-capture write-through so multi-writer gap numbering is race-free; migration gates (R13–R15, R29) land here so adopters can cut over instead of staying polluted; R21a stops the misleading local-only memory surface. **Milestone:** an operator completes an issue-store `separate-project` cutover with no false migration refusal and no tracked planning writes. **Revert:** effective-backend kill-switch re-materializes local projections from the store; visibility aliases resolve to prior names — no data loss |
| **Wave 3 — store-write robustness + integrity** | Chunk-manifest id rewrite; Jira chunking; put journal + compensation; concurrent chunked-put integrity | R8, R9, R26, R27 | Correctness of large-update and multi-writer stores. **Milestone:** Jira / large-PRD / multi-writer stores are safe for production (do not run those scenarios in production before Wave 3). **Revert:** put reverts to pre-journal write; existing issues remain readable via body fallback — no data loss |
| **Wave 4 — provider-native polish + graph hygiene** | Native labels + human-readable titles (write-side first, dual-read backfill); product source tags; schedule-hint reconciliation | R11, R12, R17 | Vendor-native projections and graph hygiene build on the robust store from Wave 3. **Milestone:** metadata served from labels with body fallback; source-tag scoping active with untagged-unit warning. **Revert:** dual-read window keeps frontmatter authoritative; disabling label projection restores body-only reads — no data loss |
| **Wave 5 — workflow polish + audit closure** | Terminal gap auto-capture; feature-named titles; memory provider round-trip; deliver-chain parity audit | R19, R20, R21b, R6 | Lowest-urgency DX polish plus audit closure; the deliver-chain parity audit (R6) closes last because it verifies the cumulative result of Waves 1–4 against the per-wave incremental parity fixtures. **Milestone:** published command×artifact×backend matrix green end-to-end. **Revert:** disable auto-capture / restore fixed titles / memory falls back to the R21a local cache — no data loss |

Cross-cutting invariants R22 (no PRD 056 duplication), R23 (file-store parity), and R32 (docs ship in the
same wave as behavior) are enforced in **every** wave via the traceability, parity, and doc-impact fixtures,
not scheduled as a separate wave. R30 (CI token-absent determinism) and R31 (per-wave rollback) are
established in Wave 1 and honored in every subsequent wave.

Per-wave incremental parity fixtures (R6/R24) run in every wave so pollution regressions surface
wave-by-wave rather than only at the Wave 5 full-matrix audit.

Dependency-driven adjustment: R6 (full parity audit) is intentionally deferred to Wave 5 because its audit
fixture can only assert full parity once the guards in Waves 2–4 exist; R24 is amended to exempt R6 from the
earliest-waves invariant and to require the per-wave incremental fixtures. Recorded as D6; the broader
re-sequencing rationale is recorded as D8.

## Documentation Impact

The docs-currency panel flagged operator-facing surfaces that describe behavior this unit changes. Per R32
each surface SHALL be updated in the same wave as the behavior. Paths target `core/` and `.sw/` sources;
`python3 -m sw generate --all` propagates to `dist/cursor` and `dist/claude-code` (do not hand-edit `dist/`).

| Artifact | Required update | Requirement | Wave |
| --- | --- | --- | --- |
| `core/skills/feedback/SKILL.md` (L94–96, L124–127) | Under issue-store `separate-project`, gap capture is store-only (no `GAP-BACKLOG.md` write-through); document the sunset stub; retain file-store/cutover-window behavior verbatim | R1 | 2 |
| `core/skills/living-status/SKILL.md` (L49, L58–67) | Separate issue-store `separate-project` authority (store close + labels, no local derived writes) from the file-store byte-identical path for GAP-BACKLOG / INDEX reconcile / `resolve_for_prd` | R1, R3, R4 | 2 |
| `core/skills/deliver/SKILL.md` (L493–521) | Guard living-doc currency reconcile behind effective backend; document R4 store-side gap close on `complete`; add terminal gap auto-capture (R19) and feature-named PR/changelog titles (R20) | R3, R4, R19, R20 | 2 (R3/R4), 5 (R19/R20) |
| `docs/guides/configuration.md` (L130–137, L158) | Mark `gitlab-issues` deferred/fail-closed; replace single visibility profile with three orthogonal axes + one-release alias map; document committed cutover derivation and `privacyAck.recordedAt` | R7, R5, R13, R14, R15 | 1 (R7), 2 (rest) |
| `core/sw-reference/planning-privacy-notice.md` (L10) | Replace `privacyAck.ackedAt` with `recordedAt`; add doctor remediation echo; note one-release alias if retained | R15 | 2 |
| `core/providers/planning-store/issue-store.md` (L80–85) | Labels carry `type`/`unit-id`/`status`/edges (D5); body holds prose + authoritative `sw-edges`; human-readable titles; provider id is a storage pointer | R11 | 4 |
| `core/providers/issues/gitlab-issues.md` (L64–66) | Add deferred/fail-closed banner; document operator message and follow-up-unit pointer | R7 | 1 |
| `CAPABILITIES.md` shipped matrix | Remove `gitlab-issues` from shipped issue providers; mark deferred | R7 | 1 |
| `docs/guides/workflows.md` (L112–114, L637–644) | Qualify living-doc currency for issue-store `separate-project`; add frontier skip/park (R16), `sw:schedule-stale` (R17), `inherit` model fallback (R18), terminal gap auto-capture (R19); update the GitLab Bitbucket path | R7, R16, R17, R18, R19 | 1 (R7/R16/R18), 4 (R17), 5 (R19) |
| `.sw/layout.md` (L160, L170–172, L185–188) | Issue-store `separate-project`: no tracked INDEX/GAP-BACKLOG/SUPERSEDED writes; gap/INDEX authority is store-side; add `sw:parked`/`sw:schedule-stale` docs; cutover-gate from config (D2) | R1, R2, R3, R5, R16, R17 | 1–2 |
| `core/skills/memory/SKILL.md` (L222–229), `core/providers/planning-store/memory.md` | Document the local-only `.cursor/sw-memory/planning-bodies/` cache (21a) and the later provider round-trip contract (21b) | R21 | 2 (21a), 5 (21b) |
| `core/commands/sw-init.md` | Add: when backend is issue-store, run `gitignore-generate --write`; document committed cutover signal replacing the gitignored state file | R5 | 2 |
| `core/commands/sw-freeze.md` (L52–53), `sw-tasks.md` (L34), `sw-migrate.md` (L67–69), `sw-feedback-close.md` (L8, L25), `sw-execute.md` (L40) | Add effective-backend guard: skip/redirect INDEX/GAP-BACKLOG steps under issue-store `separate-project`; point gap close to store issue ops (R4) | R1, R2, R3, R4 | 2 |
| `core/skills/feedback-closure/SKILL.md` (L12–14, L40) | Issue-store reads gap state from provider issues/labels; guard `feedback-backlog.py` file examples to file-store/legacy cutover only | R1, R4 | 2 |
| `core/sw-reference/models-tiering.md` (L95) | Document `wave_preflight cmd_dispatch` resolution order (agent map → `models.roles` fallback → remediation); note it prevents forced inline authoring | R18 | 1 |
| `core/sw-reference/planning-deliver-parity-matrix.md` (new) | Published command×artifact×backend matrix sink for R6; linked from deliver skill + configuration guide | R6 | 5 |
| `core/skills/visibility/references/emission-points.md` (L10) | Annotate `legacy-gap-backlog` as inert/skipped under issue-store `separate-project`; store is sole emission target | R1 | 2 |
| `core/rules/sw-git-conventions.mdc` (L36–41) | Clarify two-track mechanical allowlist: under issue-store authoritative, mechanical reconcile projects to store (no local INDEX/GAP-BACKLOG writes); substantive `docs/planning/<unit-id>/` routing unchanged | R3 | 2 |
| `README.md` (L112–114) | Qualify living-doc currency: legacy projections reconcile on file-store/cutover; issue-store `separate-project` uses store authority | R1, R2, R3 | 2 |
| `core/skills/conductor/SKILL.md` (L317) | Note living-docs reconcile scope is backend-conditioned; issue-store skips local legacy projection writes per R3 | R3 | 2 |
| doctor findings surfaces (`planning-doctor.py`) | Document new findings: `put-partial`, cardinality-mismatch, `scheduler-exhausted`, `store-token-absent` vs `probe-failed`, `wave-regression` | R26, R27, R28, R30, R31 | 1–3 |

`AGENTS.md` was reviewed and requires no change (its mock-realism guidance has no planning-store dependency).

## Decision Log

| ID | Date | Decision |
| --- | --- | --- |
| **D1** | 2026-07-06 | **gitlab-issues disposition:** demote to deferred/fail-closed now (remove from `SHIPPED_ISSUES_PROVIDERS`). Code inspection confirms no `planning_gitlab_client.py` exists and `issues_lib._live_backend` only wires jira + github-issues; a live adapter is a follow-up unit, not in scope here (R7). |
| **D2** | 2026-07-06 | **Committed cutover signal form:** derive the cutover-gate signal from `workflow.config.json` backend plus structural markers; introduce no new tracked file. The gitignored `.cursor/hooks/state/planning-cutover-gate.json` stops being a CI authority (R5). |
| **D3** | 2026-07-06 | **Chunk manifest id rewrite strategy:** compose the body with placeholder ids, post overflow comments, then re-fetch (`issue_get`) and rewrite the manifest in the persisted body with the real provider comment ids before the final index/hash step, so reassembly always resolves live comments (R8). |
| **D4** | 2026-07-06 | **Scheduler park/defer mechanism:** honor a `sw:parked` label recognized by the frontier; `next` skips parked and unrunnable units with skip-with-reasons instead of failing (R16). |
| **D5** | 2026-07-06 | **Provider-label serialization scope (gap-030):** promote structural frontmatter keys (`type`, `unit-id`, `status`, `topic`, `depends`, `absorbs`, `amends`, `visibility`) to provider-native labels; keep prose/body content (Overview, Requirements, edges narrative) in the issue body. `sw-edges` in the body remains authoritative (PRD 056 D2); labels are projections (R11). |
| **D6** | 2026-07-06 | **Wave-order deviation for R6:** the deliver-chain parity audit (gap-036) lands in Wave 5 despite being Cluster A, because its CI fixture can only assert full no-file-store-write parity after the Wave 2–4 guards land. **R24 is amended** to exempt R6 from the earliest-waves invariant and to require per-wave incremental parity fixtures so pollution regressions are caught wave-by-wave rather than only at Wave 5. |
| **D7** | 2026-07-06 | **Single comprehensive unit:** all 21 gaps are absorbed by one PRD (057) in phased waves rather than split into correctness-first and polish PRDs, per operator preference for single-unit tracking (brainstorm Key Decisions). Hardening requirements R25–R32 are added to the same unit, not spun out. |
| **D8** | 2026-07-06 | **Wave re-sequencing (panel synthesis):** the live workflow blocker R18 (dispatch preflight) is promoted to Wave 1 alongside R7/R16; the migration gates R13–R15 and the cache-freshness fix R10 are promoted to Wave 2 (co-shipped with the gap-capture write-through R1/R4 they gate); R21 is split into R21a (rename/document local-only, Wave 2) and R21b (provider round-trip, Wave 5); the hardening requirements are assigned by dependency (R28/R30/R31 Wave 1; R25/R29 Wave 2; R26/R27 Wave 3; R32 cross-cutting). Rationale: return the operator to a correct, unblocked, migratable state fastest, per the panel's product / feasibility / adversarial findings. |
| **D9** | 2026-07-06 | **Guard predicate standardization:** R1–R4 all guard on effective backend = issue-store **and** `storeLocation.mode = separate-project`, via a shared `issue_store_separate_project(root)` helper (`issue_store_effective` alone does not check mode); `same-repo` mode retains local writes because the local repo is the store. R3 additionally permits gap-041's gitignored-cache alternative as an implementation option alongside authoritative store projection. |

## Open Questions

None. All product decisions were resolved during synthesis and recorded in the Decision Log (D1–D9);
requirements R1–R32 are ready for `/sw-doc-review` and downstream `/sw-tasks` phasing.