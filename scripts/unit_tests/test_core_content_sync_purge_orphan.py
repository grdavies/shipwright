"""PRD 274 R13 — operator-local purge bypasses orphan refusal."""

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
sys.modules["core_content_sync_purge_orphan"] = core_content_sync
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
    (tmp_path / "core" / "sw-reference" / "layout.md").write_text("# layout\n", encoding="utf-8")
    for d in ("commands", "skills", "rules", "agents", "providers", "scripts"):
        (tmp_path / d).mkdir()
    return tmp_path


def test_operator_purge_bypasses_orphan_refusal(mini_root: Path) -> None:
    leaked = mini_root / "core" / "sw-reference" / "build-chain-last-synced.json"
    leaked.write_text('{"version": 1}\n', encoding="utf-8")
    assert core_content_sync.sync(mini_root) == 0
    assert not leaked.exists()


def test_non_operator_orphan_still_fail_closed(mini_root: Path) -> None:
    orphan = mini_root / "core" / "sw-reference" / "orphan-only.json"
    orphan.write_text('{"orphan": true}\n', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        core_content_sync.sync(mini_root)
    assert exc.value.code == 1
    assert orphan.is_file()
