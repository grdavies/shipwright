"""PRD 274 R7 — purge preserves allowlist and non-operator-local content."""

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
sys.modules["core_content_sync_purge_preserve"] = core_content_sync
_SPEC.loader.exec_module(core_content_sync)


@pytest.fixture
def mini_root(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "core" / "sw-reference").mkdir(parents=True)
    manifest = {
        "coreAuthoredAllowlist": ["templates/", "pinned-manifest.json"],
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
    templates = tmp_path / "core" / "sw-reference" / "templates"
    templates.mkdir(parents=True)
    (templates / "pr-body.md").write_text("# template\n", encoding="utf-8")
    (tmp_path / "core" / "sw-reference" / "pinned-manifest.json").write_text("{}\n", encoding="utf-8")
    for d in ("commands", "skills", "rules", "agents", "providers", "scripts"):
        (tmp_path / d).mkdir()
    return tmp_path


def test_purge_preserves_core_authored_allowlist(mini_root: Path) -> None:
    core_content_sync.sync(mini_root)
    templates = mini_root / "core" / "sw-reference" / "templates" / "pr-body.md"
    pinned = mini_root / "core" / "sw-reference" / "pinned-manifest.json"
    assert templates.is_file()
    assert pinned.is_file()
    assert templates.read_text(encoding="utf-8") == "# template\n"
