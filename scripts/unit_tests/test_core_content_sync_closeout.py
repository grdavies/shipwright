"""PRD 274 R4 — sync must not mirror operator-local deliver-closeout into core."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("core_content_sync", _ROOT / "core_content_sync.py")
assert _SPEC and _SPEC.loader
core_content_sync = importlib.util.module_from_spec(_SPEC)
sys.modules["core_content_sync"] = core_content_sync
_SPEC.loader.exec_module(core_content_sync)


@pytest.fixture
def mini_root(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "core" / "sw-reference").mkdir(parents=True)
    manifest = {
        "coreAuthoredAllowlist": [],
        "deprecatedAllowlist": [],
        "roles": {"coreScripts": {"excludes": ["test/"]}},
    }
    (tmp_path / "core" / "sw-reference" / "build-chain-sot.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (tmp_path / ".sw").mkdir()
    (tmp_path / ".sw" / "build-chain-sot.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / ".sw" / "layout.md").write_text("# layout\n", encoding="utf-8")
    closeout = tmp_path / ".sw" / "deliver-closeout" / "closure-manifests"
    closeout.mkdir(parents=True)
    (closeout / "prd-test-unit.json").write_text("{}", encoding="utf-8")
    for d in ("commands", "skills", "rules", "agents", "providers", "scripts"):
        (tmp_path / d).mkdir()
    return tmp_path


def test_operator_local_excludes_deliver_closeout(mini_root: Path) -> None:
    assert "deliver-closeout/" in core_content_sync.OPERATOR_LOCAL_SW_FILES


def test_sync_does_not_recreate_closeout_mirror(mini_root: Path) -> None:
    core_content_sync.sync(mini_root)
    leaked = mini_root / "core" / "sw-reference" / "deliver-closeout"
    assert not leaked.exists(), "sync must not mirror .sw/deliver-closeout/ into core/sw-reference/"
