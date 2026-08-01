"""Hermetic credential test fixture acceptance (PRD 084 R7)."""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from hermetic_fixture import (
    HERMETIC_RECIPE_UNSET,
    TOKEN_ENV_VARS,
    apply_hermetic_recipe,
)

_CREDENTIALS_SUITE = Path(__file__).resolve().parent
_IGNORE_SELF = f"--ignore={_CREDENTIALS_SUITE / 'test_hermetic_environment_fixture.py'}"


def _junit_outcomes(junit_path: Path) -> dict[str, str]:
    root = ET.parse(junit_path).getroot()
    outcomes: dict[str, str] = {}
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        nodeid = f"{classname}::{name}" if classname else name
        if case.find("failure") is not None or case.find("error") is not None:
            outcomes[nodeid] = "failed"
        elif case.find("skipped") is not None:
            outcomes[nodeid] = "skipped"
        else:
            outcomes[nodeid] = "passed"
    return outcomes


def _scrub_pytest_env(env: dict[str, str]) -> dict[str, str]:
    cleaned = dict(env)
    for key in list(cleaned):
        if key.startswith("PYTEST_") or key in {"PYTEST_ADDOPTS", "COVERAGE_FILE"}:
            cleaned.pop(key, None)
    return cleaned


def _prepare_subprocess_env(repo_root: Path, env: dict[str, str]) -> dict[str, str]:
    prepared = _scrub_pytest_env(env)
    scripts = str(repo_root / "scripts")
    existing = prepared.get("PYTHONPATH", "")
    parts = [p for p in (scripts, existing) if p]
    prepared["PYTHONPATH"] = os.pathsep.join(parts)
    return prepared


def _run_credentials_suite(repo_root: Path, env: dict[str, str], junit_path: Path) -> int:
    junit_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "test" / "run_pytest.py"),
            str(_CREDENTIALS_SUITE),
            _IGNORE_SELF,
            "-q",
            "--tb=no",
            f"--junitxml={junit_path}",
        ],
        cwd=str(repo_root),
        env=_prepare_subprocess_env(repo_root, env),
        capture_output=True,
        text=True,
        check=False,
    )
    if not junit_path.is_file():
        raise AssertionError(
            "credential suite subprocess did not emit junit output "
            f"(rc={completed.returncode}):\n{completed.stdout}\n{completed.stderr}"
        )
    return completed.returncode


def test_fixture_pins_home_and_xdg_config_home(
    hermetic_recipe_paths: tuple[Path, Path],
) -> None:
    """Probe: autouse fixture pins HOME/XDG under pytest-managed temp, not operator home."""
    home, xdg = hermetic_recipe_paths
    assert Path.home() == home
    assert os.environ.get("XDG_CONFIG_HOME") == str(xdg)
    for token_var in TOKEN_ENV_VARS:
        assert token_var not in os.environ


def test_credentials_suite_invariant_under_ambient_vs_manual_hermetic_recipe(
    repo_root: Path, tmp_path: Path
) -> None:
    """Primary acceptance: polluted ambient env vs manual hermetic recipe yield identical outcomes."""
    manual_home = tmp_path / "manual-home"
    manual_xdg = manual_home / ".config"

    ambient_env = os.environ.copy()
    for token_var in TOKEN_ENV_VARS:
        ambient_env[token_var] = "operator-pollution-sentinel-not-a-token"

    hermetic_env = apply_hermetic_recipe(
        os.environ,
        home=manual_home,
        xdg_config_home=manual_xdg,
    )

    ambient_junit = tmp_path / "ambient-junit.xml"
    hermetic_junit = tmp_path / "hermetic-junit.xml"

    ambient_rc = _run_credentials_suite(repo_root, ambient_env, ambient_junit)
    hermetic_rc = _run_credentials_suite(repo_root, hermetic_env, hermetic_junit)

    ambient_outcomes = _junit_outcomes(ambient_junit)
    hermetic_outcomes = _junit_outcomes(hermetic_junit)

    assert ambient_outcomes == hermetic_outcomes, (
        "credential suite outcomes diverged between ambient and hermetic recipe runs; "
        f"ambient_rc={ambient_rc} hermetic_rc={hermetic_rc}"
    )
    assert ambient_rc == hermetic_rc
    assert len(ambient_outcomes) >= 200, "expected full credential suite outcomes"

    # Document the operator-facing manual recipe in the failure message surface.
    assert set(HERMETIC_RECIPE_UNSET) == set(TOKEN_ENV_VARS)
