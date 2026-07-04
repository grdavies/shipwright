# Phase guidelines (single source of record)

**Owner:** `core/sw-reference/guidelines.json` (`guidelineVersion`).

Per-phase-type latitude for plan proposals (PRD 022 R30). The proposer may select only within the declared
candidate/required/optional sets and allowed reorderings; forbidden deviations are rejected by the
plan-validation gate.

## Artifact types

Guidelines and the PRD-021 capability manifest are **separate artifact types** sharing the author-time
validation harness (`scripts/capability-manifest-lint.py` → `capability_manifest_lint.py`). Guidelines bound
step shape per phase type; the manifest selects capabilities by signal.

## Phase-type coverage (022 slice)

| Phase type | Scope |
| --- | --- |
| `ship` | `/sw-ship` canonical chain latitude |
| `deliver` | `/sw-deliver` phase dispatch + `sw-ship` delegation |

Debug/doc/feedback guideline packs land with PRD-024 adoption.

## Floor refs

`floorRuleRefs` point at rules in `kernel-classification.json` → `floorMatrix.rules` (R33). Floor triggers use
immutable task-list `**File:**` paths, path globs, and persisted `signal_context` — not triage tags alone.
