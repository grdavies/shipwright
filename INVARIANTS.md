# Shipwright workflow invariants (PRD 272 R26)

Four cross-cutting invariants with enforcement paths. Generated and maintained alongside
`core/sw-reference/capability-registry.json` — regenerate capability docs via
`python3 scripts/capability_docs.py generate`.

## 1. Required-capability nonskip

**Invariant:** Profile, budget, cache, demotion, and package control paths cannot skip or downgrade
required auth/security capabilities once admitted.

**Enforcement:**

- `scripts/graph/dynamic_proposal.py` — `assert_auth_capabilities_nonskippable`
- `scripts/graph/workflow_library.py` — `assert_control_path_preserves_auth`
- `scripts/graph/profiles.py` — `preserve_required_capabilities`, `apply_workflow_profile_capabilities`

## 2. Monotone re-detect at barriers

**Invariant:** Realized-diff re-detect at merge barriers is add-only; unmet new requirements fail closed.

**Enforcement:**

- `scripts/graph/detectors/` — detector registry + re-detect helpers
- `scripts/graph/scheduler.py` — barrier hooks consult `evaluate_redetect_gate`
- `scripts/unit_tests/graph/test_requirement_reduction.py` — docs-only→migration fixture

## 3. Reduction authorization (R7)

**Invariant:** Requirement reductions occur only via mechanical detector no-fire or recorded human waiver —
model narrative alone cannot reduce tier or capability depth.

**Enforcement:**

- `scripts/graph/detectors/` — `authorize_reduction`, `record_human_waiver`, `mechanical_no_fire_for_paths`
- `scripts/triage_lib.py` — `merge_tier_monotonic` requires `reduction_path` for downward tier moves
- `scripts/unit_tests/graph/test_requirement_reduction.py`

## 4. Absolute floor independent of profile

**Invariant:** Risk-class absolute floors evaluate after profile+inject; optimization profiles cannot lower
the floor; promotion anti-ratchet ceilings bound cumulative weakening.

**Enforcement:**

- `scripts/graph/absolute_floor.py` — `enforce_absolute_floor`, `assert_anti_ratchet_ceiling`
- `core/sw-reference/risk-class-floors.json` — floor table
- `scripts/graph/workflow_library.py` — `apply_profile_to_required_capabilities`,
  `assert_promotion_anti_ratchet`
- `scripts/graph/profiles.py` — rejects kernel immutables on `workflowProfile`; budget halt → non-ready

## Operator surfaces

| Surface | Role |
| --- | --- |
| `/sw-status` graph-progress + explain | TraceRef/CoverageEdge evidence predicates (R24) |
| `/sw-triage` | Monotonic tier merge via `scripts/triage_lib.py` (R25) |
| `workflow.config.json` `graphExecution.workflowProfile` | Optimization + budgets (R23) |
| `CAPABILITIES.md` | Registry-derived capability discovery (R26) |
