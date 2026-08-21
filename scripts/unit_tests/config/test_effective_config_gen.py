"""PRD 279 phase 3 — effective-config generator fixtures (R13–R15)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from effective_config_gen import (
    build_effective_config,
    build_upgrade_manifest,
    check_drift,
    diff_settings,
    render_markdown_fragment,
)


def test_build_effective_config_includes_greenfield_overrides(repo_root: Path) -> None:
    doc = build_effective_config(repo_root)
    settings = doc["settings"]
    assert "orchestration.planPolicy" in settings
    assert settings["orchestration.planPolicy"]["greenfieldDefault"] == "proposed"
    assert settings["inefficiency.enabled"]["greenfieldDefault"] is True
    for key, row in settings.items():
        assert set(row) == {
            "schemaDefault",
            "greenfieldDefault",
            "migrationDefault",
            "runtimeFallback",
            "deprecatedSince",
            "removedIn",
        }


def test_upgrade_manifest_detects_new_settings() -> None:
    previous = {"shipwrightVersion": "2.2.0", "settings": {"a": {"schemaDefault": 1}}}
    current = {
        "shipwrightVersion": "2.3.0",
        "settings": {
            "a": {"schemaDefault": 1},
            "b": {"schemaDefault": 2},
        },
    }
    diff = diff_settings(previous, current)
    assert diff["newSettings"] == ["b"]
    assert diff["changedDefaults"] == []


def test_upgrade_manifest_detects_changed_defaults() -> None:
    previous = {"settings": {"x": {"schemaDefault": "old", "greenfieldDefault": "old"}}}
    current = {"settings": {"x": {"schemaDefault": "new", "greenfieldDefault": "new"}}}
    diff = diff_settings(previous, current)
    assert diff["changedDefaults"][0]["setting"] == "x"
    assert diff["changedDefaults"][0]["to"] == "new"


def test_render_markdown_fragment_contains_table(repo_root: Path) -> None:
    doc = build_effective_config(repo_root)
    md = render_markdown_fragment(doc)
    assert "## Effective configuration (generated)" in md
    assert "| Setting | Schema default |" in md
    assert "orchestration.planPolicy" in md


def test_check_drift_passes_after_generate(repo_root: Path, tmp_path: Path) -> None:
    mini = tmp_path / "repo"
    mini.mkdir()
    for rel in (
        "core/sw-reference/config.schema.json",
        "docs/guides/configuration.md",
        "version.txt",
    ):
        src = repo_root / rel
        dst = mini / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    (mini / "scripts").mkdir()
    sys.path.insert(0, str(repo_root / "scripts"))
    from effective_config_gen import cmd_all

    assert cmd_all(mini, write=True) == 0
    assert check_drift(mini) == []


def test_build_upgrade_manifest_has_version(repo_root: Path) -> None:
    manifest = build_upgrade_manifest(repo_root)
    assert manifest["version"]
    assert "newSettings" in manifest
