"""PRD 075 R32 — hermetic offline basic-memory fixture suite (no live cloud/MCP)."""
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

import basic_memory_interchange as bmi

FIXTURE_ROOT = SCRIPTS / "test" / "fixtures" / "basic-memory"
SCENARIOS = FIXTURE_ROOT / "scenarios"
RULES_SCRIPT = SCRIPTS.parent / "core" / "providers" / "basic-memory-rules.py"


def _load_rules_module():
    spec = importlib.util.spec_from_file_location("basic_memory_rules", RULES_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bm_rules():
    return _load_rules_module()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_lists_required_scenarios() -> None:
    manifest = _read_json(FIXTURE_ROOT / "manifest.json")
    assert manifest["supportedPackage"] == "basic-memory>=0.22.0,<1.0.0"
    for scenario in (
        "ssrf-local-cloud",
        "missing-token",
        "cache",
        "rules-refuse",
        "interchange",
    ):
        assert scenario in manifest["scenarios"]
        assert (SCENARIOS / scenario).is_dir()


def test_compat_tool_schemas_cover_op_map_tools() -> None:
    compat = _read_json(FIXTURE_ROOT / "compat-tool-schemas.json")
    assert compat["metadata"]["supportedPackage"] == "basic-memory>=0.22.0,<1.0.0"
    for tool in compat["opMapTools"]:
        assert tool in compat["tools"]
        schema = compat["tools"][tool]["inputSchema"]
        assert schema["type"] == "object"
        assert isinstance(schema.get("properties"), dict)


def test_ssrf_local_cloud_fixture_rejects_unsafe_hosts(bm_rules) -> None:
    cases = _read_json(SCENARIOS / "ssrf-local-cloud" / "cases.json")

    local_cloud = cases["localWithCloudApiBase"]["memory"]["basicMemory"]
    with pytest.raises(ValueError, match="must not open cloud"):
        bm_rules.assert_local_no_cloud(local_cloud)

    with pytest.raises(ValueError, match="filesystem"):
        bm_rules.canonicalize_project_path(
            cases["localRemoteProjectPath"]["memory"]["basicMemory"]["projectPath"],
            Path("/tmp"),
        )

    with pytest.raises(ValueError, match="allowlisted"):
        bm_rules.resolve_api_base(cases["cloudEvilHost"]["memory"]["basicMemory"])

    allowlisted = bm_rules.resolve_api_base(
        cases["cloudAllowlistedHost"]["memory"]["basicMemory"]
    )
    assert allowlisted == cases["cloudAllowlistedHost"]["expectedApiBase"]


def test_missing_token_fixture_fails_closed(
    tmp_path: Path, bm_rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = _read_json(SCENARIOS / "missing-token" / "config.json")
    monkeypatch.delenv("BASIC_MEMORY_API_KEY", raising=False)
    with pytest.raises(ValueError, match="BASIC_MEMORY_API_KEY"):
        bm_rules.resolve_api_key(scenario["memory"]["basicMemory"])

    # Script path also fails closed without opening the network.
    cursor = tmp_path / ".cursor"
    cursor.mkdir(parents=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps({"memory": scenario["memory"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SW_WORKSPACE_ROOT", str(tmp_path))
    buf = StringIO()
    with contextlib.redirect_stdout(buf):
        code = bm_rules.main()
    payload = json.loads(buf.getvalue() or "{}")
    assert code == 1
    assert payload["ok"] is False
    assert "BASIC_MEMORY_API_KEY" in payload["error"]


def test_cache_hit_miss_tamper_mode_mismatch_and_fail_closed(bm_rules, tmp_path: Path) -> None:
    project = tmp_path / "bm-project"
    project.mkdir()
    identity = str(project.resolve())

    valid = _read_json(SCENARIOS / "cache" / "rules-cache-valid.json")
    valid["projectIdentity"] = identity
    valid["writtenAt"] = time.time()
    tampered = _read_json(SCENARIOS / "cache" / "rules-cache-tampered.json")
    tampered["projectIdentity"] = identity
    tampered["writtenAt"] = time.time()
    mode_mismatch = _read_json(SCENARIOS / "cache" / "rules-cache-mode-mismatch.json")
    mode_mismatch["writtenAt"] = time.time()
    fail_closed = _read_json(SCENARIOS / "cache" / "fail-closed-config.json")
    allowlist = _read_json(SCENARIOS / "cache" / "allowlist-executables.json")

    assert bm_rules.validate_cache_entry(
        valid,
        provider="basic-memory",
        mode="local",
        project_identity=identity,
        ttl_seconds=300,
    )
    assert not bm_rules.validate_cache_entry(
        tampered,
        provider="basic-memory",
        mode="local",
        project_identity=identity,
        ttl_seconds=300,
    )
    # Cloud-bound entry must not validate under local mode (mode partition).
    assert not bm_rules.validate_cache_entry(
        mode_mismatch,
        provider="basic-memory",
        mode="local",
        project_identity=identity,
        ttl_seconds=300,
    )

    assert bm_rules.fail_closed_default({}) is fail_closed["defaultFailClosed"]
    assert bm_rules.fail_closed_default(fail_closed["explicitOpen"]) is False
    assert bm_rules.fail_closed_default(fail_closed["explicitClosed"]) is True

    for basename in allowlist["allowedBasenames"]:
        assert basename in bm_rules._ALLOWED_EXECUTABLE_BASENAMES
    for rejected in allowlist["rejectedExamples"]:
        with pytest.raises(ValueError):
            bm_rules.parse_rule_fetch_command(rejected)

    # Miss then hit via atomic write — no network.
    assert (
        bm_rules.read_rules_cache(
            tmp_path,
            provider="basic-memory",
            mode="local",
            project_identity=identity,
            ttl_seconds=300,
        )
        is None
    )
    bm_rules.write_rules_cache_atomic(
        tmp_path,
        provider="basic-memory",
        mode="local",
        project_identity=identity,
        rules=valid["rules"],
    )
    hit = bm_rules.read_rules_cache(
        tmp_path,
        provider="basic-memory",
        mode="local",
        project_identity=identity,
        ttl_seconds=300,
    )
    assert hit is not None
    assert hit[0]["id"] == "rule-guard-no-secrets"


def test_rules_refuse_fixture_skips_ordinary_rule_import(tmp_path: Path) -> None:
    expected = _read_json(SCENARIOS / "rules-refuse" / "expected.json")
    incoming = SCENARIOS / "rules-refuse" / "incoming.jsonl"

    ordinary_project = tmp_path / "ordinary"
    ordinary = bmi.import_project(
        ordinary_project, "jsonl", incoming, dry_run=False, include_rules=False
    )
    assert ordinary["imported"] == len(expected["ordinaryImportIds"])
    ids = set(bmi.list_permalinks(ordinary_project, include_rules=True))
    assert ids == set(expected["ordinaryImportIds"])
    assert "bm-rule-secret" not in ids

    promotion_project = tmp_path / "promotion"
    promotion = bmi.import_project(
        promotion_project, "jsonl", incoming, dry_run=False, include_rules=True
    )
    assert promotion["imported"] == len(expected["promotionImportIds"])
    ids_promo = set(bmi.list_permalinks(promotion_project, include_rules=True))
    assert ids_promo == set(expected["promotionImportIds"])

    out = tmp_path / "export.jsonl"
    meta = bmi.export_project(promotion_project, "jsonl", out, include_rules=False)
    text = out.read_text(encoding="utf-8")
    assert "bm-learning-001" in text
    assert "bm-rule-secret" not in text
    assert meta["count"] == 1


def test_interchange_fixture_remaps_conflicts_and_preserves_links(tmp_path: Path) -> None:
    project = tmp_path / "bm-project"
    shutil.copytree(SCENARIOS / "interchange" / "project", project)
    incoming = SCENARIOS / "interchange" / "incoming.jsonl"

    result = bmi.import_project(project, "jsonl", incoming, dry_run=False)
    remapped = {entry["from"]: entry["to"] for entry in result["idRemaps"]}
    assert "bm-merge-a" in remapped

    links = bmi.load_links(project)
    new_a = remapped["bm-merge-a"]
    assert any(
        link["source"] == new_a and link["target"] == "bm-merge-b" for link in links
    )
    assert "bm-merge-c" in set(bmi.list_permalinks(project))
    assert bmi.load_note(project, "bm-merge-a") is not None
    assert bmi.load_note(project, "bm-merge-b") is not None
