---
date: 2026-06-30
visibility: public
topic: issue-store-planning-graph
prd: docs/prds/046-issue-store-planning-graph/046-prd-issue-store-planning-graph.md
program: issue-backed-planning-store
frozen: true
frozen_at: 2026-06-30


# Tasks — PRD 046 Issue-store planning-graph derivation

Single-pass task list from the frozen PRD 046 spec union (R23, R25, R80–R94 band; decisions D22–D24).
Phases mirror the PRD Rollout Plan with a per-phase documentation-impact gate backed by
`run-planning-046-doc-impact-fixtures.sh` (PRD 043 R49). Inert for file-store users; derives read-only
views from issues when issue-store is active, building on PRD 043 (R27/R34/R43/R39/R42/R45/R28/R33/R9/R35)
and PRD 045 (R70/R22/R21).

## Tasks

### 1. Backend-pluggable discovery + region disposition + committed inFlight (L)

Single shared discovery path, issue-derived region disposition, committed cross-clone `inFlight` projection, and a gated single-authority cutover.

- [ ] 1.1 Backend-pluggable `discover_units` (R83)
  - **File:** `scripts/planning_graph.py`, `scripts/planning_index_gen.py`
  - **Expected:** `discover_units` selects `file`|`issue`; single shared source for `planning_index_gen`, `inflight_signal`, `authoring_guard`, PRD 033 reconciler/scheduler; issue source feeds the same visibility-resolution path before any issue-mode behavior is enabled
  - **R-IDs:** R83
- [ ] 1.2 Region disposition + committed `inFlight` read-only projection (R80, D22, D23)
  - **File:** `scripts/planning_graph.py`, `core/skills/deliver/SKILL.md`, `core/sw-reference/inflight-tuple.schema.json`
  - **Expected:** `structural`/`derived` rows issue-derived read-only; deliver writes `inFlight` to run-state (sole writer) and projects it read-only into committed INDEX `inFlight` region so PRD 032 cross-clone CAS/lease holds; optional tracking issue is a further read-only projection; divergence doctor fails closed on run-state↔projection↔issue skew; no stub files (PRD 043 R7); `inFlight` never mechanically edited
  - **R-IDs:** R80
- [ ] 1.3 Serialized concurrent INDEX regeneration (R88)
  - **File:** `scripts/planning_index_gen.py`
  - **Expected:** regeneration serialized by single-writer lock or monotonic generation token (PRD 035 both-region pattern); readers reject non-monotonic generation so a torn projection is never consumed
  - **R-IDs:** R88
- [ ] 1.4 Single-authority gated cutover (R87)
  - **File:** `scripts/planning_graph.py`, `core/skills/conductor/SKILL.md`
  - **Expected:** exactly one `discover_units` source per run (run-pinned, PRD 043 R33); per-region mutual exclusion in R80 matrix; explicit quiesce coordinated with PRD 044; dual-source doctor; legacy `INDEX.md` cutover disposition defined
  - **R-IDs:** R87
- [ ] 1.5 Semantic parity fixture (R92)
  - **File:** `scripts/tests/run-planning-046-parity-fixtures.sh`
  - **Expected:** issue-derived INDEX/living-status semantically matches file-store output (not byte-compare); reconciler divergence doctor fails closed beyond tolerance
  - **R-IDs:** R92
- [ ] 1.7 Region-marker newline invariant (R100, TR-A4-1)
  - **File:** `scripts/planning_index_gen.py`
  - **Expected:** `replace_region_inner` matches `render_region` newline contract for `structural`/`derived`/`inFlight`; no glued `<!-- planning-index:* begin -->` markers after generate or reconcile splice
  - **R-IDs:** R100
- [ ] 1.8 gap-020 closure fixtures + glued-marker guard (R101–R103, TR-A4-2–TR-A4-4)
  - **File:** `scripts/test/run_planning_index_fixtures.py`, `scripts/index-region-guard.py`, `core/sw-reference/pr-test-plan.manifest.json`, `docs/prds/gap/gap-020-planning-index-gen-replace-region-inner-omits-n/`
  - **Expected:** `planning-index-region-marker-newline-valid` and `index-region-guard-glued-marker-refuse` registered and green; gap-020 `status: resolved` only after fixtures green
  - **R-IDs:** R101, R102, R103
- [ ] 1.6 Phase-1 documentation exit-gate (PRD 043 R49)
  - **File:** `.sw/layout.md`, `core/skills/shipwright-state/SKILL.md`
  - **Expected:** `run-planning-046-doc-impact-fixtures.sh` asserts dual-mode INDEX/region-disposition + mechanical-region note updated before phase ship
  - **R-IDs:** R80

### 2. Derived INDEX + redaction + budget + cache safety (L)

Read-only issue-derived INDEX and scheduler within a fail-closed request budget and a redaction-safe cache.

- [ ] 2.1 Issue-derived INDEX/living-status + scheduler (R25, D24)
  - **File:** `scripts/planning_index_gen.py`, `core/commands/sw-deliver.md`
  - **Expected:** status/tier/priority labels drive `/sw-deliver next`; INDEX/living-status is a read-only derived view per PRD 043 R34/R43; derives from issue state/labels + PRD 045 R22 annotations, never authors them
  - **R-IDs:** R25
- [ ] 2.2 Request-budget model + shared ledger (R81)
  - **File:** `scripts/planning_graph.py`, `core/sw-reference/config.schema.json`
  - **Expected:** per-operation call counts, max pagination depth, content-hash-keyed cache TTL documented per provider; composes with (not replaces) PRD 043 R39 + PRD 045 R74 via a shared accounting ledger; scheduler-critical budget reserved from bulk refresh
  - **R-IDs:** R81
- [ ] 2.3 Derived-INDEX redaction at ingest (R82)
  - **File:** `scripts/planning_index_gen.py`, `core/skills/visibility/references/emission-points.md`
  - **Expected:** rows resolve visibility via PRD 043 R43 + PRD 034 R4 at ingest; `private`/`memory` emit opaque titles (`{id}: [private]`) + id/status/edges only; edge metadata redacted per PRD 043 R29
  - **R-IDs:** R82
- [ ] 2.4 Redaction-safe namespaced query cache (R84)
  - **File:** `scripts/planning_graph.py`
  - **Expected:** cache stores only post-redaction projections; secret-scan (PRD 043 R45) on issue-derived ingest before redaction and before any cache write; key `projectKey + queryFingerprint + generationEpoch`, distinct from artifact canonical-hash namespace
  - **R-IDs:** R84
- [ ] 2.5 Poll-on-reconcile cache invalidation (R85)
  - **File:** `scripts/planning_graph.py`
  - **Expected:** cache hit at deliver run-start and `/sw-deliver next` revalidates live open/closed + labels against lightweight search metadata; scheduler never schedules a frozen/closed unit from stale entry; TTL floor + forced-refresh triggers bound staleness
  - **R-IDs:** R85
- [ ] 2.6 Fail-closed partial derivation (R86)
  - **File:** `scripts/planning_index_gen.py`
  - **Expected:** pagination ceiling with `hasNextPage` marks refresh `index-incomplete`; scheduler/reconciler refuse partial INDEX without operator-acknowledged degraded mode (PRD 043 R39 halt semantics); budget exhaustion is fail-closed, never silent truncation
  - **R-IDs:** R86
- [ ] 2.7 Operator-observable budget (R93)
  - **File:** `scripts/planning_graph.py`
  - **Expected:** counts-only logging (no bodies/tokens), alert threshold before ceiling breach, documented throttle/halt surface so a shared high-churn store degrades visibly
  - **R-IDs:** R93
- [ ] 2.8 Phase-2 documentation exit-gate (PRD 043 R49)
  - **File:** `docs/guides/configuration.md`, `core/providers/planning-store/issue-store.md`
  - **Expected:** doc-impact fixture asserts scheduler + request-budget/cache-TTL + redaction docs updated before phase ship
  - **R-IDs:** R25

### 3. Hierarchy + cross-project recall (L)

Epic/sub-issue hierarchy with portable fallback, aggregate parent status, redacted cross-project recall, and inFlight tracking-issue safety.

- [ ] 3.1 Epic + sub-issue hierarchy with checkbox fallback (R23)
  - **File:** `core/skills/deliver/SKILL.md`, `scripts/planning_graph.py`
  - **Expected:** task lists map to provider epic + sub-issue-per-phase where supported (PRD 043 R30/R31), degrading to checkbox/body-encoded phase list where not; deliver updates sub-issue/checkbox state as phases merge under PRD 043 R39 + PRD 045 R70 budget
  - **R-IDs:** R23
- [ ] 3.2 Aggregate parent status, fail-closed on conflict (R91)
  - **File:** `scripts/planning_graph.py`
  - **Expected:** epic/parent status is aggregate of children via read-time label reconciliation; fails closed when children contradict parent tier/status; body-encoded `sw-edges` (PRD 043 R47) authoritative on conflict, native links reconciled on read
  - **R-IDs:** R91
- [ ] 3.3 Hierarchy capability matrix + budget + fallback (R94)
  - **File:** `core/sw-reference/capability-index.json`, `core/providers/issues/CAPABILITIES.md`
  - **Expected:** epic/sub-issue projection bound to PRD 043 R31 matrix with per-provider verb table (REST vs capability-gated GraphQL per R50), per-phase API budget (R81), mandatory checkbox/body fallback (incl. GitHub-only); absent capability degrades with operator notice, deliver continues
  - **R-IDs:** R94
- [ ] 3.4 Cross-project recall, redacted (R90)
  - **File:** `core/skills/memory/SKILL.md`, `core/providers/recallium.md`
  - **Expected:** implements PRD 043 R27; recall scoped by source `projectKey` + caller authorization; pointer dereference through `memory-redact` so project B cannot read project A private rationale/raw excerpts; deterministic ranking/tie-break; no deliverable duplication into memory
  - **R-IDs:** R90
- [ ] 3.5 inFlight tracking-issue redaction/refusal (R89)
  - **File:** `scripts/planning_graph.py`, `core/skills/deliver/SKILL.md`
  - **Expected:** tracking issue routes through PRD 034 `redact_inflight_tuple` + resolver: opaque title/body for `private`/`memory`, confidential type where supported, refusal to create on public/shared store for private/`memory` (PRD 043 R28 fail-closed)
  - **R-IDs:** R89
- [ ] 3.6 Phase-3 documentation exit-gate (PRD 043 R49)
  - **File:** `docs/guides/workflows.md`, `README.md`
  - **Expected:** doc-impact fixture asserts hierarchy + recall + getting-started notes updated before phase ship
  - **R-IDs:** R23

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |

## Traceability

| R-ID | Task ref | Named test scenario |
|------|----------|---------------------|
| R83 | 1.1 | `discover_units` switches file|issue; one shared discovery + visibility path |
| R80 | 1.2 | committed `inFlight` projection readable from a second clone; PRD 032 CAS holds; divergence doctor fails closed; no stub files |
| R88 | 1.3 | concurrent regeneration serialized by generation token; non-monotonic read rejected |
| R87 | 1.4 | cutover leaves single authoritative `discover_units` source; dual-source doctor flags |
| R92 | 1.5 | issue-derived INDEX semantically matches file-store parity fixture |
| R25 | 2.1 | `/sw-deliver next` schedules from issue labels; INDEX is read-only derived view |
| R81 | 2.2 | full refresh within per-provider ceiling; budget composes with R39/R74 ledger |
| R82 | 2.3 | private unit opaque (`{id}: [private]`) in derived INDEX; edge metadata redacted |
| R84 | 2.4 | cache never stores/serves raw private title/body; secret on ingest caught before cache write |
| R85 | 2.5 | stale cache hit revalidated; closed/frozen unit not scheduled |
| R86 | 2.6 | pagination ceiling + `hasNextPage` → `index-incomplete`; partial INDEX refused |
| R93 | 2.7 | budget alert fires before breach; counts-only logging, no bodies/tokens |
| R23 | 3.1 | epic/sub-issue on supporting provider; checkbox fallback on non-supporting |
| R91 | 3.2 | parent status aggregates children; fails closed on contradiction |
| R94 | 3.3 | hierarchy verb matrix per provider; absent capability degrades with notice, deliver continues |
| R90 | 3.4 | cross-project rationale discoverable via redacted pointers; project B cannot read project A private rationale |
| R89 | 3.5 | private/`memory` tracking issue opaque or refused on public/shared store |
| D22 | 1.2 | `inFlight` run-state sole writer + committed read-only projection (cross-clone surface) |
| D23 | 1.2 | committed read-only projection supersedes R34 interim, preserves PRD 043 R7 no-stub-files |
| R100 | 1.7 | `replace_region_inner` preserves marker newline; generate does not glue structural begin to table header |
| R101 | 1.8 | `planning-index-region-marker-newline-valid` passes |
| R102 | 1.8 | `index-region-guard-glued-marker-refuse` fails closed on glued seam |
| R103 | 1.8 | gap-020 resolved after R100–R102 green |
| D24 | 2.1 | derived views read-only (never author annotations/linkage/close); budget composes with R39/R74 |
