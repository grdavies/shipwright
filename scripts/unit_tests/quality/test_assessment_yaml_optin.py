"""PRD 326 R14 — assessment YAML schema + opt-in default inertness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import architecture_assessment as aa

VALID_ASSESSMENT = """\
doctrineVersion: 1
assessments:
  - id: AD-1
    verdict: pass
    evidence: zero-shell-guard green
"""


def test_absent_config_mode_is_off(repo_root: Path, tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".cursor"
    cfg_dir.mkdir()
    (cfg_dir / "workflow.config.json").write_text("{}", encoding="utf-8")
    result = aa.evaluate(tmp_path)
    assert result["verdict"] == "skip"
    assert result["mode"] == "off"


def test_one_assessment_entry_validates() -> None:
    from yaml_structured import safe_load

    document = safe_load(VALID_ASSESSMENT)
    errors = aa.validate_assessment_document(document)
    assert errors == []


def test_all_verdict_kinds_validate() -> None:
    from yaml_structured import safe_load

    yaml_text = """\
doctrineVersion: 1
assessments:
  - id: AD-1
    verdict: pass
  - id: AD-2
    verdict: fail
  - id: AD-3
    verdict: manual
  - id: AD-4
    verdict: waived
    waiver:
      actor: human@example.com
      reason: temporary exception
      expires: 2099-12-31
"""
    errors = aa.validate_assessment_document(safe_load(yaml_text))
    assert errors == []


@pytest.mark.parametrize("mode", ["off", "advisory", "blocking"])
def test_mode_enum_values(tmp_path: Path, mode: str) -> None:
    cfg_dir = tmp_path / ".cursor"
    cfg_dir.mkdir()
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps({"architecture": {"assessment": {"mode": mode}}}),
        encoding="utf-8",
    )
    assert aa.assessment_mode(tmp_path) == mode


def test_schema_rejects_unknown_top_level_key() -> None:
    errors = aa.validate_assessment_document({"doctrineVersion": 1, "assessments": [], "extra": True})
    assert any("unknown top-level key" in err for err in errors)


def test_waived_without_waiver_fields_fails() -> None:
    errors = aa.validate_assessment_document(
        {"doctrineVersion": 1, "assessments": [{"id": "AD-1", "verdict": "waived"}]}
    )
    assert errors


def test_configuration_guide_documents_defaults_and_waiver(repo_root: Path) -> None:
    text = (repo_root / "docs/guides/configuration.md").read_text(encoding="utf-8")
    assert "architecture.assessment.mode" in text
    assert "`off`" in text
    assert "waiver.{actor,reason,expires}" in text
    assert "| `architecture.assessment.mode` | `off`" in text


def test_assessment_yaml_round_trip_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "assessment.yaml"
    path.write_text(VALID_ASSESSMENT, encoding="utf-8")
    loaded = aa.load_assessment_yaml(tmp_path, path=path)
    assert loaded["verdict"] == "pass"
    document = loaded["document"]
    assert document["doctrineVersion"] == 1
    assert document["assessments"][0]["id"] == "AD-1"
