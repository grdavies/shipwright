"""PRD 338 phase 11 — distribution bundle acceptance (R23–R31)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_PKG = "scripts/unit_tests/w4"
_HARNESS = "harness_prd338_bundle_acceptance.py"
_PHASE_MODULES = (
    "scripts/unit_tests/w4/test_prd338_dist_version.py",
    "scripts/unit_tests/install/test_prd338_claude_installer.py",
    "scripts/unit_tests/init/test_prd338_profile_seeds.py",
    "scripts/unit_tests/test_prd325_docs_currency_consumer.py",
    "scripts/unit_tests/graph/test_packages_trust.py",
    "scripts/unit_tests/w4/test_portability_boundary.py",
    "scripts/unit_tests/w4/test_portability_closure.py",
)


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_prd338_bundle_acceptance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prd338_bundle_acceptance_harness(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """M — bundle harness covers install-root docs, redirects, version, trust, installer, currency."""
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root)
    assert int(mod.main()) == 0


def test_prd338_bundle_acceptance_harness_present(repo_root: Path) -> None:
    """R16 — harness module must exist (fail-closed if port regresses)."""
    assert (repo_root / _PKG / _HARNESS).is_file()


@pytest.mark.parametrize("module_path", _PHASE_MODULES)
def test_prd338_bundle_phase_modules_collect(repo_root: Path, module_path: str) -> None:
    """S — phase-owned acceptance modules remain importable for bundle closeout."""
    path = repo_root / module_path
    assert path.is_file(), f"missing bundle module {module_path}"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(path)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
