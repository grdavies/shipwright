"""PRD 069 wave-a-gate-ergonomics unit and harness coverage (R3)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PKG = "scripts/unit_tests/deliver"
_HARNESS = "harness_wave_a_gate_ergonomics.py"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_wave_a_gate_ergonomics", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_remediation_for_forgery(repo_root: Path) -> None:
    from status_integrity import remediation_for_status_cause

    assert remediation_for_status_cause("phase-status:forged-provenance")


@pytest.mark.integration
@pytest.mark.git
def test_wave_a_gate_ergonomics_harness(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    assert int(_load_harness(repo_root).main()) == 0


def test_wave_a_gate_ergonomics_harness_present(repo_root: Path) -> None:
    assert (repo_root / _PKG / _HARNESS).is_file()
