"""PRD 352 R27 — final smoke covering AS1–AS6 via phase smoke entry points."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name: str):
    path = HERE / name
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_p2 = _load("test_prd352_phase2_smoke.py")
_p3 = _load("test_prd352_phase3_smoke.py")
_p4 = _load("test_prd352_phase4_smoke.py")
_p5 = _load("test_prd352_phase5_smoke.py")


def test_prd352_final_as1_packaged_handoff_self_test() -> None:
    """AS1 — packaged handoff_bundle --self-test."""
    _p2.test_prd352_phase2_packaged_handoff_self_test()


def test_prd352_final_as2_installer_preserves_native_skill(tmp_path: Path) -> None:
    """AS2 — installer preserves native skill body."""
    _p3.test_prd352_phase3_installer_preserves_native_skill(tmp_path)


def test_prd352_final_as3_as4_capture_identity_and_wall_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AS3/AS4 — distinct same-second discovery IDs; wall-clock milestone stamp."""
    _p3.test_prd352_phase3_capture_same_second_and_milestone(tmp_path, monkeypatch)


def test_prd352_final_as5_hook_deny_shape() -> None:
    """AS5 — PreToolUse deny nests permissionDecision."""
    _p4.test_prd352_phase4_hook_conformance_shapes()


def test_prd352_final_as6_fresh_process_advisory(tmp_path: Path) -> None:
    """AS6 — durable advisory hydrates in a fresh process."""
    _p5.test_prd352_phase5_fresh_process_advisory_lookup(tmp_path)
