"""PRD 274 R8/R9/R15 — dist freshness detect (side-effect-free, regen in errors)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

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
            [sys.executable, str(_SCRIPTS / "dist_freshness.py"), "detect"],
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
