"""Config preserve on packaged reinstall/upgrade (PRD 356 R5/R6)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from shipwright_paths import (
    WORKFLOW_CONFIG_LEGACY_RELS,
    WORKFLOW_CONFIG_PREFERRED_REL,
)

D5_CONFIG_CANDIDATE_RELS = (
    WORKFLOW_CONFIG_PREFERRED_REL,
    *WORKFLOW_CONFIG_LEGACY_RELS,
)


def _load_sw_configure():
    path = SCRIPT_DIR / "sw-configure.py"
    spec = importlib.util.spec_from_file_location("sw_configure_preserve", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sw_configure():
    return _load_sw_configure()


def _seed_schema(consumer: Path, sw_configure) -> None:
    schema_rel = Path(sw_configure.SCHEMA_REL)
    schema_dest = consumer / schema_rel.parent
    schema_dest.mkdir(parents=True)
    schema_dest.joinpath(schema_rel.name).write_text(
        (REPO_ROOT / schema_rel).read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _operator_config(*, memory_provider: str = "recallium", planning_provider: str = "linear") -> dict:
    return {
        "memory": {"provider": memory_provider},
        "planning": {
            "store": {"provider": planning_provider},
            "host": {"credentialRef": "github/work"},
        },
        "configuredWith": {
            "shipwrightVersion": "9.9.9-operator",
            "schemaVersion": "1.0.0-operator",
        },
    }


@pytest.mark.parametrize("config_rel", D5_CONFIG_CANDIDATE_RELS)
def test_reinstall_preserves_existing_operator_config(
    tmp_path: Path, sw_configure, config_rel: str
) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _seed_schema(consumer, sw_configure)

    config_path = consumer / config_rel
    config_path.parent.mkdir(parents=True, exist_ok=True)
    operator_cfg = _operator_config()
    config_path.write_text(json.dumps(operator_cfg, indent=2) + "\n", encoding="utf-8")
    before = config_path.read_text(encoding="utf-8")

    result = sw_configure.apply_packaged_configure(consumer, accept_ci_stub=False)
    assert result["verdict"] == "pass", result
    assert result.get("preserved") is True
    assert result.get("written") == []
    assert config_path.read_text(encoding="utf-8") == before
    assert json.loads(before)["memory"]["provider"] == "recallium"
    assert json.loads(before)["planning"]["store"]["provider"] == "linear"


def test_greenfield_init_writes_scaffold_once(tmp_path: Path, sw_configure) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _seed_schema(consumer, sw_configure)

    result = sw_configure.apply_packaged_configure(consumer, accept_ci_stub=False)
    assert result["verdict"] == "pass", result
    assert result.get("preserved") is False
    assert result.get("written")
    config_path = Path(result["configPath"])
    assert config_path.is_file()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload.get("configuredWith")


def test_reinstall_retains_credential_ref_without_writing_secrets(
    tmp_path: Path, sw_configure
) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _seed_schema(consumer, sw_configure)

    config_path = consumer / WORKFLOW_CONFIG_PREFERRED_REL
    config_path.parent.mkdir(parents=True, exist_ok=True)
    operator_cfg = _operator_config()
    config_path.write_text(json.dumps(operator_cfg, indent=2) + "\n", encoding="utf-8")

    result = sw_configure.apply_packaged_configure(consumer, accept_ci_stub=False)
    assert result.get("preserved") is True
    after = json.loads(config_path.read_text(encoding="utf-8"))
    assert after["planning"]["host"]["credentialRef"] == "github/work"
    assert "token" not in json.dumps(after).lower()
    assert "secret" not in json.dumps(after).lower()


def test_config_preserve_doctor_notice_is_keys_only_and_redacted(
    tmp_path: Path, sw_configure
) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _seed_schema(consumer, sw_configure)

    config_path = consumer / WORKFLOW_CONFIG_PREFERRED_REL
    config_path.parent.mkdir(parents=True, exist_ok=True)
    operator_cfg = _operator_config()
    config_path.write_text(json.dumps(operator_cfg, indent=2) + "\n", encoding="utf-8")

    result = sw_configure.apply_packaged_configure(consumer, accept_ci_stub=False)
    notice = result.get("doctorNotice") or {}
    assert notice.get("id") == sw_configure.CONFIG_PRESERVE_NOTICE_ID
    assert notice.get("configPath") == WORKFLOW_CONFIG_PREFERRED_REL
    assert "memory" in (notice.get("topLevelKeys") or [])
    assert "planning" in (notice.get("topLevelKeys") or [])
    notice_blob = json.dumps(notice)
    assert "github/work" not in notice_blob
    assert "recallium" not in notice_blob
    assert str(consumer) not in notice_blob

    stored = sw_configure.config_preserve_upgrade_notice(consumer)
    assert stored is not None
    assert stored.get("id") == sw_configure.CONFIG_PRESERVE_NOTICE_ID
    assert stored.get("configPath") == WORKFLOW_CONFIG_PREFERRED_REL
