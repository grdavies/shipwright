"""PRD 076 R22–R26 — obsidian hook rules script transport + vault-partitioned cache."""
from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
import time
from io import StringIO
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "core" / "providers" / "obsidian-rules.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("obsidian_rules", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["obsidian_rules"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def obs_rules():
    return _load_module()


def _write_config(workspace: Path, provider: str, **obsidian: object) -> None:
    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    payload = {
        "memory": {
            "provider": provider,
            "project": "hook-test",
            "obsidian": obsidian,
        }
    }
    (cursor / "workflow.config.json").write_text(json.dumps(payload), encoding="utf-8")


def _run_main_inprocess(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    obs_rules,
) -> tuple[int, dict]:
    monkeypatch.setenv("SW_WORKSPACE_ROOT", str(workspace))
    buf = StringIO()
    with contextlib.redirect_stdout(buf):
        code = obs_rules.main()
    payload = json.loads(buf.getvalue() or "{}")
    return code, payload


def _seed_vault(workspace: Path) -> Path:
    vault = workspace / "vault"
    rules = vault / "rules"
    rules.mkdir(parents=True)
    (rules / "guard.md").write_text(
        "---\ncategory: rule\n---\nDo not invent providers.\n",
        encoding="utf-8",
    )
    return vault


def test_non_applicable_for_wrong_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, obs_rules
) -> None:
    _write_config(tmp_path, "recallium", vaultPath=str(tmp_path / "vault"))
    code, payload = _run_main_inprocess(tmp_path, monkeypatch, obs_rules)
    assert code == 0
    assert payload["applicable"] is False
    assert payload["rules"] == []
    assert payload["ok"] is True


def test_disk_reads_rules_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, obs_rules
) -> None:
    vault = _seed_vault(tmp_path)
    _write_config(
        tmp_path,
        "obsidian",
        vaultPath=str(vault),
        rulesDirectory="rules",
    )
    code, payload = _run_main_inprocess(tmp_path, monkeypatch, obs_rules)
    assert code == 0
    assert payload["ok"] is True
    assert payload["applicable"] is True
    assert payload["cache"] == "miss"
    assert payload["transport"] == "disk"
    assert len(payload["rules"]) == 1
    assert payload["rules"][0]["id"] == "rules/guard.md"
    assert "invent" in payload["rules"][0]["summary"]


def test_cache_miss_then_hit_skips_fetch(
    tmp_path: Path, obs_rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _seed_vault(tmp_path)
    _write_config(
        tmp_path,
        "obsidian",
        vaultPath=str(vault),
        ruleCacheTtlSec=300,
    )

    fetch_calls = {"count": 0}
    real_fetch = obs_rules.fetch_rules

    def counting_fetch(cfg):
        fetch_calls["count"] += 1
        return real_fetch(cfg)

    monkeypatch.setattr(obs_rules, "fetch_rules", counting_fetch)

    code1, payload1 = _run_main_inprocess(tmp_path, monkeypatch, obs_rules)
    assert code1 == 0
    assert payload1["cache"] == "miss"
    assert fetch_calls["count"] == 1

    code2, payload2 = _run_main_inprocess(tmp_path, monkeypatch, obs_rules)
    assert code2 == 0
    assert payload2["cache"] == "hit"
    assert payload2["rules"][0]["id"] == "rules/guard.md"
    assert fetch_calls["count"] == 1


def test_tampered_cache_is_miss(
    tmp_path: Path, obs_rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _seed_vault(tmp_path)
    identity = str(vault.resolve())
    _write_config(tmp_path, "obsidian", vaultPath=str(vault))
    obs_rules.write_rules_cache_atomic(
        tmp_path,
        provider="obsidian",
        project_identity=identity,
        rules=[{"id": "r1", "summary": "alpha"}],
    )
    cache_file = obs_rules.cache_path(tmp_path)
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["rules"] = [{"id": "r1", "summary": "tampered"}]
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    code, out = _run_main_inprocess(tmp_path, monkeypatch, obs_rules)
    assert code == 0
    assert out["cache"] == "miss"
    assert out["rules"][0]["id"] == "rules/guard.md"


def test_foreign_vault_cache_binding_is_miss(tmp_path: Path, obs_rules) -> None:
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    vault_a.mkdir()
    vault_b.mkdir()
    obs_rules.write_rules_cache_atomic(
        tmp_path,
        provider="obsidian",
        project_identity=str(vault_b.resolve()),
        rules=[{"id": "r1", "summary": "foreign"}],
    )
    assert (
        obs_rules.read_rules_cache(
            tmp_path,
            provider="obsidian",
            project_identity=str(vault_a.resolve()),
            ttl_seconds=300,
        )
        is None
    )


def test_cache_ttl_expiry_is_miss(tmp_path: Path, obs_rules) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    identity = str(vault.resolve())
    obs_rules.write_rules_cache_atomic(
        tmp_path,
        provider="obsidian",
        project_identity=identity,
        rules=[{"id": "r1", "summary": "alpha"}],
    )
    cache_file = obs_rules.cache_path(tmp_path)
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["writtenAt"] = time.time() - 600
    cache_file.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        obs_rules.read_rules_cache(
            tmp_path,
            provider="obsidian",
            project_identity=identity,
            ttl_seconds=300,
        )
        is None
    )


def test_fail_closed_default_true(obs_rules) -> None:
    assert obs_rules.fail_closed_default({}) is True
    assert obs_rules.fail_closed_default({"failClosed": False}) is False
