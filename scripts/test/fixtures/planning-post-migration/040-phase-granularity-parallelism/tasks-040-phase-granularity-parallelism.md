---
prd: docs/prds/040-phase-granularity-parallelism/040-prd-phase-granularity-parallelism.md
date: 2026-06-30
topic: phase-granularity-parallelism
visibility: public
frozen: true
frozen_at: 2026-06-30
---
# Tasks — PRD 040 Phase Granularity & Parallelism

Generated from the frozen PRD (effective spec union R15–R19, R30, R31). Phases mirror the PRD Rollout Plan.
No implementation starts until the `doc.afterTasks` boundary.

## Tasks

### 1. Corpus calibration (read-only) — baseline thresholds

- [x] 1.1 Audit frozen task-list corpus; set sizing defaults
  - **File:** `scripts/test/fixtures/phase-sizing/` (corpus snapshot), `docs/guides/configuration.md`
  - **Expected:** baseline distribution of per-phase file-count / traceability scenarios / realized wave width across existing frozen task lists; `tasks.sizing.*` defaults derived from it (no thresholds shipped without calibration).
  - **R-IDs:** R15

### 2. Sizing scorer + schema (read-only)

- [x] 2.1 Deterministic sizing scorer + schema + config
  - **File:** `scripts/phase-sizing.sh`, `core/sw-reference/phase-sizing.schema.json`, `core/sw-reference/config.schema.json` (`tasks.sizing.*`), `workflow.config.example.json`
  - **Expected:** parses draft via `doc_format.py`; emits per-phase JSON `{ phase, filesTouched, distinctDirs, subTaskCount, traceabilityScenarios|null, depFanOut, size, overThreshold, belowFloor, separableSets }`; deterministic (identical input → byte-identical output); `traceabilityScenarios=null` + notice when `## Traceability` absent.
  - **R-IDs:** R15
- [x] 2.2 Declared-scope cross-check (anti-gaming)
  - **File:** `scripts/phase-sizing.sh`, deliver `contentionFeedback` reconcile hook
  - **Expected:** reconciles `**File:**` vs `## Relevant Files` + sub-task prose; emits `scopeUnderDeclared` advisory; declared-vs-post-phase-diff reconciliation reuses existing `contentionFeedback` (parity with `tasks-suggest`).
  - **R-IDs:** R15

### 3. Split suggestion + contention integrity (advisory)

- [x] 3.1 Separability + split via wave_deliver contention primitives
  - **File:** `scripts/phase-sizing.sh` (imports from `scripts/wave_deliver.py`)
  - **Expected:** `separableSets` = connected components of intra-phase contention graph via `inject_contention_edges`/`paths_contend` + `expand_generator_contention_paths` + `contention_serialized_defaults`; split proposes smaller units with transitive fan-in/fan-out edge preservation; full pairwise simulation injects mandatory serializing edges; split rejected if contention closure differs from parent.
  - **R-IDs:** R16
- [x] 3.2 Advisory block + frozen hygiene
  - **File:** `scripts/phase-sizing.sh` (`--check-frozen`), `scripts/check-frozen.py`, `core/skills/spec-rigor/SKILL.md`, `core/sw-reference/layout.md`, `.sw/layout.md`
  - **Expected:** `## Sizing & Split Suggestions` rendered into draft only (with cost estimate); `--check-frozen` print-only/fail-closed on `frozen: true`; `/sw-freeze` strips/flags a stray advisory block from a frozen artifact; layout docs register the block + sizing JSON.
  - **R-IDs:** R16, R30

### 4. Parallelism objective + preflight validation

- [x] 4.1 Greedy split scorer + wave_deliver dry-run preflight
  - **File:** `scripts/phase-sizing.sh`, `core/commands/sw-deliver.md` (`--sizing-report`)
  - **Expected:** simulate `deps_to_edges → apply_contention → assign_waves` via imported helpers + `wave_deliver` dry-run preflight; keep decomposition only if it raises independent-phase count within `worktree.parallelCeiling`; fail-closed with notice on cycle or width-1 collapse; `--sizing-report` is operator-visibility only (no scheduling input).
  - **R-IDs:** R17
- [x] 4.2 Min-floor + maxPhaseCount + cost estimate
  - **File:** `scripts/phase-sizing.sh`, `core/sw-reference/config.schema.json` (`tasks.sizing.{minPhaseFiles,minPhaseScenarios,maxPhaseCount}`)
  - **Expected:** splitting below the minimum-viable-phase floor is not rewarded; `maxPhaseCount` bounds total phases; advisory block prints projected waves × merge gates (granularity-DoS guard).
  - **R-IDs:** R18

### 5. Authoring guidance + fallback reconciliation

- [x] 5.1 Small-phase design-constraint + prefer-many-small guidance
  - **File:** `core/skills/tasks/SKILL.md`, `core/commands/sw-tasks.md`, `core/skills/parallelism/SKILL.md`
  - **Expected:** replace informal S/M/L with heuristic `small|medium|large` + research-referenced small-phase design constraint + floor; prefer-many-small directive; split suggestions cite parallelism contention families.
  - **R-IDs:** R18, R19
- [x] 5.2 PRD 013 fallback-ladder doc reconciliation
  - **File:** `core/skills/tasks/SKILL.md`, `core/skills/deliver/SKILL.md`, `core/commands/sw-deliver.md`
  - **Expected:** `/sw-tasks` requires `## Phase Dependencies` at freeze; deliver docs authoritatively describe the PRD 013 ladder (declared → file-set inference → sequential+notice); no regression to `wave_deliver` behavior.
  - **R-IDs:** R19
- [x] 5.3 Redaction of persisted sizing summaries
  - **File:** `scripts/phase-sizing.sh` (persist path), `scripts/memory-redact.py` integration
  - **Expected:** any persisted sizing/split summary routes through `scripts/memory-redact.py` (fail-closed) before write; `sw-` naming + model-tier floor obeyed.
  - **R-IDs:** R31

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 3 |
| 5 | 2 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R15 | 2.1 | `run-phase-sizing-fixtures.sh` — sizing determinism + threshold/floor classification (files, scenarios, dep fan-out, sub-task, distinct-dir) |
| R16 | 3.1 | `run-phase-sizing-fixtures.sh` — split edge preservation + contention integrity (no dropped serializing family; mandatory edges injected) |
| R17 | 4.1 | `run-phase-sizing-fixtures.sh` — parallelism objective raises independent-phase count; dry-run preflight rejects cycle / width-1 collapse |
| R18 | 4.2 | `run-phase-sizing-fixtures.sh` — over-split DoS bound (`maxPhaseCount` / min-floor) + cost estimate; authoring-guidance conformance snapshot |
| R19 | 5.2 | `run-phase-sizing-fixtures.sh` — missing `## Phase Dependencies` → PRD 013 ladder (file-set inference → sequential+notice), no regression |
| R30 | 3.2 | `run-phase-sizing-fixtures.sh` — frozen print-only (`--check-frozen`) + `/sw-freeze` strips advisory block |
| R31 | 5.3 | `run-phase-sizing-fixtures.sh` — redaction fail-closed on persisted sizing summary |

## Relevant Files

- `scripts/phase-sizing.sh` — deterministic scorer + split suggester (Phases 1–4).
- `scripts/wave_deliver.py` — imported (read-only) for contention primitives + dry-run preflight.
- `core/sw-reference/{phase-sizing.schema.json,config.schema.json,layout.md}`, `.sw/layout.md` — contracts.
- `core/skills/{tasks,deliver,parallelism}/SKILL.md`, `core/commands/{sw-tasks,sw-deliver}.md` — guidance.

## Notes

- Backward compatible: with sizing unconfigured the scorer reports defaults and changes no task-list content;
  the PRD 013 deliver fallback ladder is unchanged.
- Contention integrity (R16/R17) MUST reuse `wave_deliver` primitives — do not re-enumerate families; the
  generator-output / golden-manifest expansion is part of the closure compared against the parent phase.
- Thresholds + min-floor (R15/R18) are set from the Phase-0 corpus calibration before Phase 1 freeze.
