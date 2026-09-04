# Unit 1 exit evidence (PRD 342)

Recorded at the Unit 1 exit checkpoint (phase 4: migration safety, memory allowlist, layout relocate).

## Exit criteria

| Criterion | Evidence |
| --- | --- |
| Suite green on relocated layout | `scripts/unit_tests/memory/test_state_root_allowlist_failclosed.py` + phase 1–3 state-root suites |
| Enumerated test-edit list | See below |
| Demonstrated rollback (completed migration reverse) | Abort path restores legacy layout (`test_interrupted_migrate_abort_restores_layout`) |
| Demonstrated abort of interrupted migration | Same abort test after simulated mid-flight interrupt |
| SC3 cloned-path baseline | See below |

## Enumerated test-edit list (Unit 1)

Paths touched so the suite remains meaningful after state-root relocation:

1. `scripts/unit_tests/config/test_state_root_inventory.py` (phase 1)
2. `scripts/unit_tests/guardrails/test_path_literal_guard.py` (phase 2)
3. `scripts/unit_tests/guardrails/test_state_root_zero_shell.py` (phase 2)
4. `scripts/unit_tests/guardrails/test_program_unit_graph.py` (phase 2)
5. `scripts/unit_tests/config/test_state_root_migration_gate.py` (phase 3)
6. `scripts/unit_tests/memory/test_state_root_allowlist_failclosed.py` (phase 4)
7. `scripts/unit_tests/memory/test_hermetic_non_in_repo_rules.py` (allowlist fail-closed follow-through)

## Demonstrated resume / abort (R15)

- Resume: interrupt after first journaled move → `--resume` completes; semantic digests of run state, memory rules, and allowlist match pre-move digests.
- Abort: interrupt after first move → `--abort` restores legacy layout and releases the quiesce fence without manual file surgery.

## SC3 cloned-path baseline

Metric: distinct operator actions from a clean machine to a first feature branch (cloned contributor path).

Measured baseline at Unit 1 exit:

1. Clone the repository
2. Install the plugin (`python3 scripts/install.py`) and reload the editor
3. Open a project repo and run `/sw-init`
4. Start a feature via `/sw-start` (or equivalent worktree start)

**SC3 cloned-path baseline = 4 operator actions.**

The packaged path at Unit 2 exit must be no higher than this baseline.

## Layout contract

Authoritative file: `.shipwright/layout.md` (documents both trees for the redirect window).
Legacy stub: `.sw/layout.md`. Mirror: `core/sw-reference/layout.md`.
