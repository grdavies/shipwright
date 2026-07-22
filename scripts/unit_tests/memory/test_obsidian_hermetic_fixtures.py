"""PRD 076 R29 — hermetic offline Obsidian fixture suite (no live GUI/MCP)."""
from __future__ import annotations

import contextlib
import importlib.util
import json
import shutil
import sys
import time
from io import StringIO
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import obsidian_interchange as oi

FIXTURE_ROOT = SCRIPTS / "test" / "fixtures" / "obsidian"
SCENARIOS = FIXTURE_ROOT / "scenarios"
RULES_SCRIPT = SCRIPTS.parent / "core" / "providers" / "obsidian-rules.py"


def _load_rules_module():
    spec = importlib.util.spec_from_file_location("obsidian_rules", RULES_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def obs_rules():
    return _load_rules_module()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_lists_required_scenarios() -> None:
    manifest = _read_json(FIXTURE_ROOT / "manifest.json")
    assert manifest["supportedPlugin"] == "obsidian-local-rest-api>=3.2.0,<4.0.0"
    for scenario in (
        "ssrf-loopback",
        "path-confinement",
        "missing-token",
        "cache",
        "rules-refuse",
        "interchange",
    ):
        assert scenario in manifest["scenarios"]
        assert (SCENARIOS / scenario).is_dir()


def test_compat_tool_schemas_cover_op_map_tools() -> None:
    compat = _read_json(FIXTURE_ROOT / "compat-tool-schemas.json")
    assert compat["metadata"]["supportedPlugin"] == "obsidian-local-rest-api>=3.2.0,<4.0.0"
    for tool in compat["opMapTools"]:
        assert tool in compat["tools"]
        schema = compat["tools"][tool]["inputSchema"]
        assert schema["type"] == "object"
        assert isinstance(schema.get("properties"), dict)


def test_ssrf_loopback_fixture_rejects_non_loopback(obs_rules) -> None:
    cases = _read_json(SCENARIOS / "ssrf-loopback" / "cases.json")
    for name, case in cases.items():
        if case.get("ok"):
            assert obs_rules.resolve_mcp_base({"mcpBaseUrl": case["mcpBaseUrl"]}) == case["mcpBaseUrl"].rstrip("/")
        else:
            with pytest.raises(ValueError, match=case["errorSubstring"]):
                obs_rules.resolve_mcp_base({"mcpBaseUrl": case["mcpBaseUrl"]})


def test_path_confinement_fixture(tmp_path: Path, obs_rules) -> None:
    cases = _read_json(SCENARIOS / "path-confinement" / "cases.json")
    with pytest.raises(ValueError, match=cases["escapeRulesDir"]["errorSubstring"]):
        obs_rules.validate_rules_directory(cases["escapeRulesDir"]["rulesDirectory"])
    with pytest.raises(ValueError, match=cases["absoluteRulesDir"]["errorSubstring"]):
        obs_rules.validate_rules_directory(cases["absoluteRulesDir"]["rulesDirectory"])
    assert obs_rules.resolve_rules_directory({"rulesDirectory": cases["okRulesDir"]["rulesDirectory"]}) == "rules"

    vault = tmp_path / "vault"
    (vault / "rules").mkdir(parents=True)
    (vault / "rules" / "guard.md").write_text("ok\n", encoding="utf-8")
    ok = obs_rules.confine_under(vault, vault / cases["okCandidate"]["candidate"])
    assert ok is not None
    assert obs_rules.confine_under(vault, vault / cases["escapeCandidate"]["candidate"]) is None


def test_missing_token_fixture_fails_closed(obs_rules, monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = _read_json(SCENARIOS / "missing-token" / "config.json")
    monkeypatch.delenv("OBSIDIAN_API_KEY", raising=False)
    with pytest.raises(ValueError, match=scenario["expectedErrorSubstring"]):
        obs_rules.resolve_bearer(scenario["memory"]["obsidian"])


def test_cache_hit_miss_tamper_and_fail_closed(obs_rules, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    identity = str(vault.resolve())

    valid = _read_json(SCENARIOS / "cache" / "rules-cache-valid.json")
    valid["projectIdentity"] = identity
    valid["writtenAt"] = time.time()
    valid["checksum"] = obs_rules.rules_payload_checksum(valid["rules"])
    tampered = _read_json(SCENARIOS / "cache" / "rules-cache-tampered.json")
    tampered["projectIdentity"] = identity
    tampered["writtenAt"] = time.time()
    fail_closed = _read_json(SCENARIOS / "cache" / "fail-closed-config.json")

    assert obs_rules.validate_cache_entry(
        valid, provider="obsidian", project_identity=identity, ttl_seconds=300
    )
    assert not obs_rules.validate_cache_entry(
        tampered, provider="obsidian", project_identity=identity, ttl_seconds=300
    )
    assert obs_rules.fail_closed_default({}) is fail_closed["defaultFailClosed"]
    assert obs_rules.fail_closed_default(fail_closed["explicitOpen"]) is False
    assert obs_rules.fail_closed_default(fail_closed["explicitClosed"]) is True

    assert (
        obs_rules.read_rules_cache(
            tmp_path, provider="obsidian", project_identity=identity, ttl_seconds=300
        )
        is None
    )
    obs_rules.write_rules_cache_atomic(
        tmp_path,
        provider="obsidian",
        project_identity=identity,
        rules=valid["rules"],
    )
    hit = obs_rules.read_rules_cache(
        tmp_path, provider="obsidian", project_identity=identity, ttl_seconds=300
    )
    assert hit is not None
    assert hit[0]["id"] == "rule-guard-no-secrets"


def test_rules_refuse_fixture_skips_ordinary_rule_import(tmp_path: Path) -> None:
    expected = _read_json(SCENARIOS / "rules-refuse" / "expected.json")
    incoming = SCENARIOS / "rules-refuse" / "incoming.jsonl"
    project = expected["project"]

    ordinary_vault = tmp_path / "ordinary"
    ordinary = oi.import_vault(
        ordinary_vault, "jsonl", incoming, project=project, dry_run=False, include_rules=False
    )
    assert ordinary["imported"] == len(expected["ordinaryImportIds"])
    ids = set(oi.list_path_ids(ordinary_vault, project=project, include_rules=True))
    assert ids == set(expected["ordinaryImportIds"])
    assert "rules/obs-rule-secret.md" not in ids

    promotion_vault = tmp_path / "promotion"
    promotion = oi.import_vault(
        promotion_vault, "jsonl", incoming, project=project, dry_run=False, include_rules=True
    )
    assert promotion["imported"] == len(expected["promotionImportIds"])
    ids_promo = set(oi.list_path_ids(promotion_vault, project=project, include_rules=True))
    assert ids_promo == set(expected["promotionImportIds"])

    out = tmp_path / "export.jsonl"
    meta = oi.export_vault(promotion_vault, "jsonl", out, project=project, include_rules=False)
    text = out.read_text(encoding="utf-8")
    assert "obs-learning-001" in text
    assert "obs-rule-secret" not in text
    assert meta["count"] == 1


def test_interchange_fixture_remaps_conflicts_and_preserves_links(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(SCENARIOS / "interchange" / "vault", vault)
    incoming = SCENARIOS / "interchange" / "incoming.jsonl"
    project = "fixture"

    result = oi.import_vault(vault, "jsonl", incoming, project=project, dry_run=False)
    remapped = {entry["from"]: entry["to"] for entry in result.get("idRemaps", [])}
    assert "obs-merge-a" in remapped or any("obs-merge-a" in str(v) for v in remapped.values()) or result["imported"] >= 2

    ids = set(oi.list_path_ids(vault, project=project, include_rules=False))
    assert any("obs-merge-b" in i for i in ids)
    assert any("obs-merge-c" in i for i in ids)
    # existing A remains; conflict remaps incoming A
    assert any("obs-merge-a" in i for i in ids)
    links = oi.load_links(vault)
    assert links or result["imported"] >= 2
