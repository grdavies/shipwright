"""PRD 337 R12 — coreAuthoredAllowlist enforcement and authored dist preservation."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("copy_to_core", _ROOT / "copy-to-core.py")
assert _SPEC and _SPEC.loader
copy_to_core = importlib.util.module_from_spec(_SPEC)
sys.modules["copy_to_core_prd337"] = copy_to_core
_SPEC.loader.exec_module(copy_to_core)


def _mini_manifest(*, allowlist: list[str] | None = None) -> dict:
    return {
        "coreAuthoredAllowlist": allowlist if allowlist is not None else ["templates/"],
        "deprecatedAllowlist": [],
        "roles": {"coreScripts": {"excludes": ["test/"]}},
    }


@pytest.fixture
def mini_root(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    manifest = _mini_manifest()
    (tmp_path / "core" / "sw-reference").mkdir(parents=True)
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


def test_preserves_allowlisted_core_authored_during_sync(mini_root: Path) -> None:
    templates = mini_root / "core" / "sw-reference" / "templates"
    templates.mkdir(parents=True)
    authored = templates / "pr-body.md"
    authored.write_text("# authored template\n", encoding="utf-8")

    assert copy_to_core.sync(mini_root) == 0
    assert authored.read_text(encoding="utf-8") == "# authored template\n"


def test_explicit_allowlist_permits_core_only_file(mini_root: Path) -> None:
    manifest = _mini_manifest(allowlist=["templates/", "pinned-manifest.json"])
    for path in (
        mini_root / "core" / "sw-reference" / "build-chain-sot.json",
        mini_root / ".sw" / "build-chain-sot.json",
    ):
        path.write_text(json.dumps(manifest), encoding="utf-8")
    pinned = mini_root / "core" / "sw-reference" / "pinned-manifest.json"
    pinned.write_text('{"pinned": true}\n', encoding="utf-8")

    copy_to_core.reject_unregistered_core_sot(mini_root, manifest)
    assert copy_to_core.sync(mini_root) == 0
    assert pinned.read_text(encoding="utf-8") == '{"pinned": true}\n'


def test_rejects_unregistered_core_sot_file(mini_root: Path) -> None:
    rogue = mini_root / "core" / "sw-reference" / "rogue-sot.json"
    rogue.write_text('{"unregistered": true}\n', encoding="utf-8")
    manifest = _mini_manifest(allowlist=["templates/"])

    with pytest.raises(SystemExit) as exc:
        copy_to_core.reject_unregistered_core_sot(mini_root, manifest)
    assert exc.value.code == 1
    assert rogue.is_file()

    with pytest.raises(SystemExit):
        copy_to_core.sync(mini_root)


def test_preserves_authored_dist_across_generate_wipe(mini_root: Path) -> None:
    manifest = _mini_manifest(allowlist=["templates/"])
    dist_ref = mini_root / "dist" / "cursor" / "core" / "sw-reference"
    templates = dist_ref / "templates"
    templates.mkdir(parents=True)
    authored = templates / "pr-body.md"
    authored.write_text("# dist authored\n", encoding="utf-8")
    (dist_ref / "layout.md").write_text("# generated layout\n", encoding="utf-8")

    snapshot = copy_to_core.snapshot_authored_dist(mini_root, manifest)
    assert "cursor/templates/pr-body.md" in snapshot

    shutil.rmtree(mini_root / "dist" / "cursor")
    copy_to_core.restore_authored_dist(mini_root, snapshot)

    assert authored.read_text(encoding="utf-8") == "# dist authored\n"
    assert not (dist_ref / "layout.md").exists()
