"""recallium-rules.py broker refusal code propagation (PRD 084 phase 4 / R4)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import memory_broker
import memory_lib
from memory_provider_catalog import get_provider, load_catalog
from sw_recallium_url import rest_fetch_policy_from_catalog_entry

SCRIPTS = Path(__file__).resolve().parents[2]


def _write_config(root: Path, memory: dict) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps(
            {
                "projectId": "acme-demo",
                "memory": {
                    "provider": "recallium",
                    "project": "hook-test",
                    **memory,
                },
            }
        ),
        encoding="utf-8",
    )


def _recallium_policy(repo_root: Path) -> dict:
    catalog = load_catalog(repo_root)
    return rest_fetch_policy_from_catalog_entry(get_provider(catalog, "recallium"))


def _load_recallium_rules_module(repo_root: Path):
    script = repo_root / "core" / "providers" / "recallium-rules.py"
    spec = importlib.util.spec_from_file_location("recallium_rules_broker_codes_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


class TestRecalliumRulesBrokerCodes:
    def test_memory_broker_error_propagates_code_and_message(
        self, repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_config(
            tmp_path,
            {
                "credentialRef": "memory-work",
                "connection": {"restBaseUrl": "http://localhost:8001"},
            },
        )
        monkeypatch.setenv("SW_WORKSPACE_ROOT", str(tmp_path))

        def raise_provider_mismatch(**kwargs):  # noqa: ANN003
            raise memory_broker.MemoryBrokerError(
                "credential provider does not match memory surface",
                code="resolver-provider-mismatch",
            )

        monkeypatch.setattr(memory_broker, "prepare_bound_headers", raise_provider_mismatch)
        monkeypatch.setattr(
            memory_lib,
            "resolve_memory_credential",
            lambda *a, **k: object(),
        )

        import sw_recallium_url

        monkeypatch.setattr(
            sw_recallium_url,
            "load_catalog_rest_policy",
            lambda root, provider_id: _recallium_policy(repo_root),
        )

        module = _load_recallium_rules_module(repo_root)
        assert module.main() == 1

        captured = capsys.readouterr()
        payload = json.loads(captured.out.strip())
        assert payload["ok"] is False
        assert payload["code"] == "resolver-provider-mismatch"
        assert "restBaseUrl must be localhost-only" not in payload["error"]
        assert payload["rules"] == []

    def test_non_localhost_rest_base_url_keeps_localhost_only_message(
        self, repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_config(
            tmp_path,
            {"connection": {"restBaseUrl": "https://api.recallium.example"}},
        )
        monkeypatch.setenv("SW_WORKSPACE_ROOT", str(tmp_path))

        import sw_recallium_url

        monkeypatch.setattr(
            sw_recallium_url,
            "load_catalog_rest_policy",
            lambda root, provider_id: _recallium_policy(repo_root),
        )

        module = _load_recallium_rules_module(repo_root)
        assert module.main() == 1

        captured = capsys.readouterr()
        payload = json.loads(captured.out.strip())
        assert payload["ok"] is False
        assert payload["error"] == "restBaseUrl must be localhost-only"
        assert "code" not in payload
        assert payload["rules"] == []
