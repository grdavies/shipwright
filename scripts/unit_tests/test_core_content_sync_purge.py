"""PRD 274 R5/R6/R12 — operator-local purge on core-content-sync."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from _sw import mirror

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("core_content_sync", _ROOT / "core_content_sync.py")
assert _SPEC and _SPEC.loader
core_content_sync = importlib.util.module_from_spec(_SPEC)
sys.modules["core_content_sync_purge"] = core_content_sync
_SPEC.loader.exec_module(core_content_sync)


@pytest.fixture
def mini_root(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "core" / "sw-reference").mkdir(parents=True)
    manifest = {
        "coreAuthoredAllowlist": ["templates/"],
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


def test_copy_exclude_separate_from_purge_targets() -> None:
    manifest = {"coreAuthoredAllowlist": ["templates/"]}
    copy_excludes = list(manifest["coreAuthoredAllowlist"])
    copy_excludes.extend(core_content_sync.OPERATOR_LOCAL_SW_FILES)
    purge_targets = list(core_content_sync.OPERATOR_LOCAL_PURGE_TARGETS)
    assert "templates/" in copy_excludes
    assert "templates/" not in purge_targets
    assert set(purge_targets).issubset(set(copy_excludes))
    assert set(copy_excludes) != set(purge_targets)


def test_purge_excludes_removes_operator_local_dest(mini_root: Path) -> None:
    leaked = mini_root / "core" / "sw-reference" / "credential-ci-selector.json"
    leaked.write_text('{"leak": true}\n', encoding="utf-8")
    core_content_sync.sync(mini_root)
    assert not leaked.exists()


def test_planted_leak_removed_in_one_sync(mini_root: Path) -> None:
    leak = mini_root / "core" / "sw-reference" / "deliver-closeout" / "closure-manifests"
    leak.mkdir(parents=True)
    (leak / "prd-planted.json").write_text("{}", encoding="utf-8")
    core_content_sync.sync(mini_root)
    assert not (mini_root / "core" / "sw-reference" / "deliver-closeout").exists()


def test_mirror_purge_targets_diverge_from_copy_excludes(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "keep.txt").write_text("ok\n", encoding="utf-8")
    (dst / "keep.txt").write_text("ok\n", encoding="utf-8")
    planted = dst / "operator-local"
    planted.mkdir()
    (planted / "leak.txt").write_text("leak\n", encoding="utf-8")
    mirror.mirror(
        src,
        dst,
        excludes=["templates/"],
        purge_targets=["operator-local/"],
        delete=False,
        purge_excludes=True,
    )
    assert planted.exists() is False
    assert (dst / "keep.txt").exists()
