"""PRD 274 R10/R11/R14 — ship auto-regen, staging bounds, stale-dist regression."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from dist_freshness import CANONICAL_REGEN_COMMAND, detect_drift
from dist_freshness_ship import capture_preexisting_dist_changes, ship_auto_regen


def _restore_ledger_and_dist(repo_root: Path, target: Path, original: str) -> None:
    target.write_text(original, encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "sw", "generate", "--all"],
        cwd=str(repo_root),
        capture_output=True,
        check=False,
    )
    subprocess.run(["git", "-C", str(repo_root), "reset", "HEAD", "--", "dist/"], check=False)


def _touch_script(repo_root: Path) -> tuple[Path, str]:
    subprocess.run(["git", "-C", str(repo_root), "checkout", "--", "dist/"], check=False)
    subprocess.run(
        [sys.executable, "-m", "sw", "generate", "--all"],
        cwd=str(repo_root),
        capture_output=True,
        check=False,
    )
    target = repo_root / "scripts/planning_refusal_ledger.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\n# ship-regen probe\n", encoding="utf-8")
    return target, original


def test_ship_auto_regen_and_stage_or_fail_closed(repo_root: Path) -> None:
    """R10 — stale dist from script edit is auto-regenerated and staged."""
    target, original = _touch_script(repo_root)
    try:
        assert detect_drift(repo_root)
        result = ship_auto_regen(repo_root)
        assert result["verdict"] == "pass"
        assert result.get("action") == "regen"
        assert detect_drift(repo_root) == []
        staged = result.get("staged") or []
        assert staged
        assert result.get("changed")
    finally:
        _restore_ledger_and_dist(repo_root, target, original)


def test_ship_regen_refuses_overlapping_preexisting(repo_root: Path) -> None:
    """R14 — preexisting dist edits overlapping regen output fail closed."""
    target, original = _touch_script(repo_root)
    dist_mirror = repo_root / "dist/cursor/scripts/planning_refusal_ledger.py"
    if not dist_mirror.is_file():
        pytest.skip("dist mirror layout unavailable for overlap probe")
    dist_original = dist_mirror.read_bytes()
    dist_mirror.write_bytes(dist_original + b"\n# manual preexisting\n")
    try:
        pre = capture_preexisting_dist_changes(repo_root)
        assert pre
        result = ship_auto_regen(repo_root)
        assert result["verdict"] == "fail"
        assert result.get("cause") == "overlapping-preexisting"
        assert result.get("overlap")
    finally:
        dist_mirror.write_bytes(dist_original)
        _restore_ledger_and_dist(repo_root, target, original)


def test_scripts_only_edit_stale_dist_gate(repo_root: Path) -> None:
    """R11 — scripts-only edit triggers detect failure or successful ship regen."""
    target, original = _touch_script(repo_root)
    try:
        detect_proc = subprocess.run(
            [sys.executable, str(_SCRIPTS / "dist_freshness.py"), "detect"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert detect_proc.returncode != 0
        assert CANONICAL_REGEN_COMMAND in detect_proc.stderr

        ship_proc = subprocess.run(
            [sys.executable, str(_SCRIPTS / "dist_freshness_ship.py"), "regen"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert ship_proc.returncode == 0, ship_proc.stderr
        payload = json.loads(ship_proc.stdout)
        assert payload["verdict"] == "pass"
        assert detect_drift(repo_root) == []
    finally:
        _restore_ledger_and_dist(repo_root, target, original)
