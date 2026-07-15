"""PRD 069 R10 — greenfield init posture snapshot tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from init_posture_defaults import GREENFIELD_POSTURE_LEAF_KEYS, greenfield_posture_patch, leaf_get


def test_greenfield_posture_patch_shape() -> None:
    patch = greenfield_posture_patch()
    assert patch["orchestration"]["planPolicy"] == "proposed"
    assert patch["delegation"]["mode"] == "heuristic"
    assert patch["planning"]["autonomy"] == "full-conductor"
    assert patch["deliver"]["loop"]["drainMechanical"] is True
    assert patch["inefficiency"]["enabled"] is True
    assert patch["execute"]["enabled"] is True
    assert len(GREENFIELD_POSTURE_LEAF_KEYS) == 7


def test_write_draft_seeds_posture(repo_root: Path) -> None:
    out = subprocess.check_output(
        [sys.executable, str(repo_root / "scripts/sw-configure.py"), "write-draft", "--accept-defaults"],
        cwd=str(repo_root),
        text=True,
    )
    payload = json.loads(out)
    assert payload.get("verdict") == "pass"
    draft_path = Path(payload["path"])
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    for path, expected in GREENFIELD_POSTURE_LEAF_KEYS:
        assert leaf_get(draft, path) == expected


def test_schema_defaults_match_posture(repo_root: Path) -> None:
    schema = json.loads((repo_root / "core/sw-reference/config.schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]

    def default_at(*keys: str):
        node = props
        for key in keys[:-1]:
            node = node[key]["properties"]
        return node[keys[-1]].get("default")

    assert default_at("orchestration", "planPolicy") == "proposed"
    assert default_at("delegation", "mode") == "heuristic"
    assert default_at("planning", "autonomy") == "full-conductor"
    assert default_at("deliver", "loop", "drainMechanical") is True
    assert default_at("inefficiency", "enabled") is True
    assert default_at("execute", "enabled") is True
    assert default_at("deliver", "autonomy", "mode") == "autonomous"


def test_configuration_docs_mention_posture(repo_root: Path) -> None:
    text = (repo_root / "docs/guides/configuration.md").read_text(encoding="utf-8")
    for token in (
        "Greenfield init posture",
        "orchestration.planPolicy",
        "delegation.mode",
        "planning.autonomy",
        "inefficiency.enabled",
    ):
        assert token in text


def test_workflows_docs_ship_run_and_gap_check(repo_root: Path) -> None:
    text = (repo_root / "docs/guides/workflows.md").read_text(encoding="utf-8")
    assert "Terminal ship-run chain" in text
    assert "watch-ci" in text
    assert "gap-check-gate.py write" in text
