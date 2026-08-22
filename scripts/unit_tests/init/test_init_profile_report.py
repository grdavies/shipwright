"""Profile report classification and schema coverage tests (PRD 324 phase 12 / R9, R10, R12, R14)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from doctor import profile_completeness_report, profile_refresh  # noqa: E402
from init_profile_report import (  # noqa: E402
    EXAMPLE_CONFIG_REL,
    classify_entry,
    classify_profile,
    curated_entries,
    profile_entries,
    validate_profile_schema_paths,
)


def test_every_curated_profile_key_resolves_in_schema(repo_root: Path) -> None:
    missing = validate_profile_schema_paths(repo_root)
    assert missing == []
    report = classify_profile(repo_root)
    assert report["verdict"] == "pass"
    assert report["missingSchemaPaths"] == []


def test_example_config_link_present(repo_root: Path) -> None:
    report = classify_profile(repo_root)
    assert report["exampleConfigPath"] == EXAMPLE_CONFIG_REL.as_posix()
    assert report["exampleConfigExists"] is True
    assert (repo_root / EXAMPLE_CONFIG_REL).is_file()


def test_classification_statuses_against_fixtures(repo_root: Path) -> None:
    schema = json.loads((repo_root / "core/sw-reference/config.schema.json").read_text(encoding="utf-8"))
    present_cfg = {
        "orchestration": {"planPolicy": "canonical"},
        "review": {"provider": "coderabbit"},
    }
    for entry in curated_entries():
        row = classify_entry(entry, present_cfg, schema)
        if entry.path == ("orchestration", "planPolicy"):
            assert row["status"] == "present"
        if entry.path == ("review", "provider"):
            assert row["status"] == "present"

    empty_cfg: dict = {}
    unset_paths = {
        row["path"]
        for entry in curated_entries()
        for row in [classify_entry(entry, empty_cfg, schema)]
        if row["status"] in ("unset", "defaulted")
    }
    assert "projectId" in unset_paths
    assert len(profile_entries()) >= len(curated_entries())


def test_consent_gated_completeness_refresh_leaves_config_without_confirm(
    repo_root: Path, tmp_path: Path
) -> None:
    config_dir = tmp_path / ".cursor"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "workflow.config.json"
    original = {
        "orchestration": {"planPolicy": "operator-locked"},
        "review": {"provider": "none"},
    }
    config_path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

    report = profile_completeness_report(tmp_path)
    assert report["verdict"] in ("warn", "pass")
    refresh = profile_refresh(tmp_path, confirm=False)
    assert refresh["verdict"] == "confirm-required"
    assert json.loads(config_path.read_text(encoding="utf-8")) == original

    if report.get("refreshablePaths"):
        confirmed = profile_refresh(tmp_path, confirm=True)
        assert confirmed["verdict"] == "pass"
        updated = json.loads(config_path.read_text(encoding="utf-8"))
        assert updated["orchestration"]["planPolicy"] == "operator-locked"
        for path in confirmed.get("applied", []):
            assert path != "orchestration.planPolicy"
