#!/usr/bin/env python3
"""verify.test bundle executed via Python runner (R27)."""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SUITES = ['run_gate_fixtures.py', 'run_pr_test_plan_manifest.py', 'run_pr_test_plan_fixtures.py', 'run_doc_link_fixtures.py', 'run_impl_fixtures.py', 'run_debug_fixtures.py', 'run_feedback_fixtures.py', 'run_improvement_fixtures.py', 'run_memory_provider_fixtures.py', 'run_memory_sot_fixtures.py', 'run_memory_prework_fixtures.py', 'run_code_review_fixtures.py', 'run_persona_selection_fixtures.py', 'run_onboarding_ux_fixtures.py', 'run_deliver_fixtures.py', 'run_status_integrity_fixtures.py', 'run_deliver_loop_fixtures.py', 'run_deliver_concurrency_fixtures.py', 'run_orchestrator_fixtures.py', 'run_branch_guard_fixtures.py', 'run_state_fixtures.py', 'run_secret_scan_fixtures.py', 'run_ship_phase_fixtures.py', 'run_tasks_currency_fixtures.py', 'run_merge_queue_fixtures.py', 'run_compound_completion_fixtures.py', 'run_stabilize_merge_fixtures.py', 'run_007_docs_fixtures.py', 'run_007_fixtures.py', 'run_living_doc_fixtures.py', 'run_model_binding_fixtures.py', 'run_dispatch_foundation_fixtures.py', 'run_delegation_fixtures.py', 'run_retrospective_fixtures.py', 'run_portability_setup_fixtures.py', 'run_portability_boundary_fixtures.py', 'run_base_resolution_fixtures.py', 'run_portability_closure_fixtures.py', 'run_emitter_fixtures.py', 'run_capability_lint_fixtures.py', 'run_capability_select_fixtures.py', 'run_migration_parity_fixtures.py', 'run_kernel_classification_fixtures.py', 'run_guidelines_floor_fixtures.py', 'run_plan_validate_fixtures.py', 'run_plan_persist_fixtures.py', 'run_plan_killswitch_fixtures.py', 'run_plan_proposed_parity_fixtures.py', 'run_pilot_fixtures.py', 'run_host_fixtures.py', 'run_parity_fixtures.py', 'run_planning_035_deliver_conductor_fixtures.py']

def _run(path: Path) -> int:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return int(mod.main()) if hasattr(mod, 'main') else 1

def main() -> int:
    failures = 0
    for name in SUITES:
        path = SCRIPT_DIR / name
        if not path.is_file():
            print(f"FAIL missing suite {name}")
            failures += 1
            continue
        print(f"==> verify/{name}")
        if _run(path) != 0:
            failures += 1
    return 1 if failures else 0

if __name__ == '__main__':
    raise SystemExit(main())
