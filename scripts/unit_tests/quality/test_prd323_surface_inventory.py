"""PRD 326 phase 1 / R1 — read-only inventory of PRD 323 surfaces.

Probe asserts required scripts + resilience package modules import cleanly and expose
documented entry points. Emits ``{"verdict","present","missing"}`` and exits ``20`` when
any surface is missing. Performs no writes and no rebuild.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

REQUIRED_SCRIPT_MODULES: dict[str, tuple[str, ...]] = {
    "debug_repro_gate": ("evaluate_gate", "emit", "exit_code_for_verdict"),
    "merge_provenance": ("build_index", "emit"),
    "merge_intent_resolve": ("attempt_intent_resolve", "build_proposal", "build_resume_command"),
}

RESILIENCE_MODULES: dict[str, tuple[str, ...]] = {
    "unit_tests.resilience.harness": ("ResilienceHarness", "InjectionBoundary", "HermeticFixture"),
    "unit_tests.resilience.property_model": (),
    "unit_tests.resilience.fuzz_transitions": (),
    "unit_tests.resilience.test_injection_ports": (),
    "unit_tests.resilience.test_issue_store_freeze_compat": (),
    "unit_tests.resilience.test_operator_surface": (),
    "unit_tests.resilience.test_property_assurance": (),
    "unit_tests.resilience.test_property_cache_identity": (),
    "unit_tests.resilience.test_property_cancel_fence": (),
    "unit_tests.resilience.test_property_finalize_checkpoint": (),
    "unit_tests.resilience.test_property_generation_fence": (),
    "unit_tests.resilience.test_property_merge_conflict": (),
}

RESILIENCE_FILES = (
    "scripts/unit_tests/resilience/harness.py",
    "scripts/unit_tests/resilience/property_model.py",
    "scripts/unit_tests/resilience/fuzz_transitions.py",
    "scripts/unit_tests/resilience/test_injection_ports.py",
    "scripts/unit_tests/resilience/test_issue_store_freeze_compat.py",
    "scripts/unit_tests/resilience/test_operator_surface.py",
    "scripts/unit_tests/resilience/test_property_assurance.py",
    "scripts/unit_tests/resilience/test_property_cache_identity.py",
    "scripts/unit_tests/resilience/test_property_cancel_fence.py",
    "scripts/unit_tests/resilience/test_property_finalize_checkpoint.py",
    "scripts/unit_tests/resilience/test_property_generation_fence.py",
    "scripts/unit_tests/resilience/test_property_merge_conflict.py",
)


def _probe(root: Path) -> dict[str, Any]:
    present: list[str] = []
    missing: list[str] = []

    for rel in (
        "scripts/debug_repro_gate.py",
        "scripts/merge_provenance.py",
        "scripts/merge_intent_resolve.py",
        *RESILIENCE_FILES,
    ):
        path = root / rel
        if path.is_file():
            present.append(rel)
        else:
            missing.append(rel)

    for mod_name, attrs in {**REQUIRED_SCRIPT_MODULES, **RESILIENCE_MODULES}.items():
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001 — inventory must name every failure
            missing.append(f"import:{mod_name}:{type(exc).__name__}")
            continue
        present.append(f"import:{mod_name}")
        for attr in attrs:
            if hasattr(mod, attr):
                present.append(f"attr:{mod_name}.{attr}")
            else:
                missing.append(f"attr:{mod_name}.{attr}")

    verdict = "pass" if not missing else "fail"
    return {"verdict": verdict, "present": present, "missing": missing}


def main(argv: list[str] | None = None) -> int:
    root = Path.cwd()
    if argv and len(argv) >= 1 and not str(argv[0]).startswith("-"):
        root = Path(argv[0])
    payload = _probe(root)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["verdict"] == "pass" else 20


def test_prd323_surface_inventory(repo_root: Path) -> None:
    """Read-only inventory of PRD 323 surfaces must be complete."""
    payload = _probe(repo_root)
    assert payload["verdict"] == "pass", payload["missing"]
    assert not payload["missing"], payload["missing"]
    assert "scripts/debug_repro_gate.py" in payload["present"]
    assert "import:debug_repro_gate" in payload["present"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
