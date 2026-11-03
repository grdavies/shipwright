"""PRD 274 R8/R9/R15 — dist freshness detect (side-effect-free, regen in errors)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from unit_tests._harness_runtime import isolated_source_fixture, isolated_git_environment


@pytest.fixture(autouse=True)
def _isolate_git_environment(monkeypatch):
    # Imported helpers also spawn Git, so isolate the whole test process.
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    for key, value in isolated_git_environment({}).items():
        monkeypatch.setenv(key, value)


@pytest.fixture(scope="session")
def repo_root():
    """Own all source, generation, and index mutations used by distribution tests."""
    source = Path(__file__).resolve().parents[2]
    with isolated_source_fixture(source, extra_inputs=("sw", "platforms", "dist")) as root:
        yield root

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from dist_freshness import (
    CANONICAL_REGEN_COMMAND,
    detect_drift,
    detect_is_side_effect_free,
    format_drift_message,
)


def test_detect_stale_dist_when_scripts_change(repo_root: Path) -> None:
    """R8 — drift detected when a registered script changes without dist refresh."""
    target = repo_root / "scripts/planning_refusal_ledger.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\n# dist-freshness probe\n", encoding="utf-8")
    try:
        drift = detect_drift(repo_root)
        assert drift
        assert any(row.get("kind") in {"mirror-stale", "zipapp-stale"} for row in drift)
    finally:
        target.write_text(original, encoding="utf-8")
        subprocess.run(
            [sys.executable, "-m", "sw", "generate", "--all"],
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )


def test_error_includes_canonical_regen_command(repo_root: Path) -> None:
    """R9 — operator error surfaces exact canonical regen command."""
    target = repo_root / "scripts/planning_refusal_ledger.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\n# regen-command probe\n", encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(repo_root / "scripts/dist_freshness.py"), "detect"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0
        assert CANONICAL_REGEN_COMMAND in proc.stderr
        assert CANONICAL_REGEN_COMMAND in format_drift_message(detect_drift(repo_root))
    finally:
        target.write_text(original, encoding="utf-8")
        subprocess.run(
            [sys.executable, "-m", "sw", "generate", "--all"],
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )


def test_local_detect_is_side_effect_free(repo_root: Path) -> None:
    """R15 — detect path does not mutate dist working tree state."""
    assert detect_is_side_effect_free(repo_root)


def test_detect_passes_on_synced_repo(repo_root: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "sw", "generate", "--all"],
        cwd=str(repo_root),
        capture_output=True,
        check=False,
    )
    assert detect_drift(repo_root) == []
