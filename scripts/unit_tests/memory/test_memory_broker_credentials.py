"""Memory REST adapter broker adoption tests (PRD 080 21.3 / R1) — Z,O,M,E,I."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from credentials.config_surface import present_implicit_default_tables
from credentials.model import CredentialRef, Principal, Resolution, ResolutionState, ResolvedToken, Secret
import memory_broker
import memory_lib
from memory_provider_catalog import get_provider, load_catalog
from sw_recallium_url import (
    RestFetchPolicyError,
    rest_fetch_policy_from_catalog_entry,
    validate_memory_base_before_auth,
)


_TEST_VALUE = "unit-test-memory-broker-value-abcdef"
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


class TestNoCredential:
    def test_no_credential_is_explicitly_no_auth_without_default_table(self, tmp_path: Path) -> None:
        assert not hasattr(memory_lib, "DEFAULT_TOKEN_ENV")
        _write_config(tmp_path, {"connection": {"restBaseUrl": "http://localhost:8001"}})
        resolution = memory_lib.resolve_memory_credential(tmp_path, memory_provider="recallium")
        assert resolution.state is ResolutionState.EXPLICITLY_NO_AUTH
        assert "RECALLIUM_API_KEY" not in (resolution.ref.value,)


class TestOneResolvedCredential:
    def test_one_adapter_attaches_bearer_via_broker(self, repo_root: Path, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            {
                "credentialRef": "memory-work",
                "connection": {"restBaseUrl": "http://localhost:8001"},
            },
        )
        credential = Resolution.resolved(
            CredentialRef("memory-work"),
            ResolvedToken(Secret(_TEST_VALUE), Principal(profile="work")),
        )
        policy = _recallium_policy(repo_root)
        url = "http://localhost:8001/api/projects/hook-test/memories?memory_type=rule&limit=25"
        headers = memory_broker.prepare_bound_headers(url=url, policy=policy, credential=credential)
        assert headers.get("Authorization") == f"Bearer {_TEST_VALUE}"


class TestManyProviders:
    @pytest.mark.parametrize(
        ("provider", "base_url"),
        [
            ("recallium", "http://localhost:8001"),
            ("basic-memory", "http://127.0.0.1:8001"),
            ("obsidian", "http://127.0.0.1:27123"),
        ],
    )
    def test_many_providers_resolve_without_implicit_defaults(
        self, tmp_path: Path, provider: str, base_url: str
    ) -> None:
        assert not hasattr(memory_lib, "DEFAULT_TOKEN_ENV")
        _write_config(
            tmp_path,
            {
                "provider": provider,
                "credentialRef": f"{provider}-work",
                "connection": {"restBaseUrl": base_url},
            },
        )
        resolution = memory_lib.resolve_memory_credential(tmp_path, memory_provider=provider)
        assert resolution.state is ResolutionState.UNRESOLVED
        cfg = json.loads((tmp_path / ".cursor" / "workflow.config.json").read_text(encoding="utf-8"))
        assert memory_lib.resolve_memory_token_env(cfg, provider) == ""


class TestOutOfScopeEndpoint:
    def test_off_allowlist_base_url_refuses_before_authorization_header(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        policy = _recallium_policy(repo_root)
        with pytest.raises(RestFetchPolicyError):
            validate_memory_base_before_auth("http://evil.example.com:8001", policy)

        credential = Resolution.resolved(
            CredentialRef("memory-work"),
            ResolvedToken(Secret(_TEST_VALUE)),
        )
        with pytest.raises(memory_broker.MemoryBrokerError) as exc:
            memory_broker.prepare_bound_headers(
                url="http://evil.example.com:8001/api/projects/hook-test/memories",
                policy=policy,
                credential=credential,
            )
        assert exc.value.code == "endpoint-refused"

    def test_prepare_bound_headers_refuses_metadata_before_auth(self, repo_root: Path) -> None:
        policy = _recallium_policy(repo_root)
        credential = Resolution.resolved(
            CredentialRef("memory-work"),
            ResolvedToken(Secret(_TEST_VALUE)),
        )
        with pytest.raises(memory_broker.MemoryBrokerError) as exc:
            memory_broker.prepare_bound_headers(
                url="http://169.254.169.254/latest/meta-data/",
                policy=policy,
                credential=credential,
            )
        assert exc.value.code == "endpoint-refused"


class TestImplicitDefaultAbsent:
    def test_implicit_memory_default_table_deleted(self) -> None:
        module = importlib.import_module("memory_lib")
        assert not hasattr(module, "DEFAULT_TOKEN_ENV")
        present = present_implicit_default_tables()
        assert "memory_lib.DEFAULT_TOKEN_ENV" not in present


class TestRecalliumRulesAdapter:
    def test_recallium_rules_uses_broker_not_ambient_env(
        self, repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(
            tmp_path,
            {
                "credentialRef": "memory-work",
                "connection": {"restBaseUrl": "http://localhost:8001"},
            },
        )
        credential = Resolution.resolved(
            CredentialRef("memory-work"),
            ResolvedToken(Secret(_TEST_VALUE)),
        )
        captured: dict[str, object] = {}

        monkeypatch.setenv("SW_WORKSPACE_ROOT", str(tmp_path))
        monkeypatch.setattr(memory_lib, "resolve_memory_credential", lambda *a, **k: credential)

        real_prepare = memory_broker.prepare_bound_headers

        def capture_prepare(*, url, policy, credential=None, **kwargs):  # noqa: ANN001
            headers = real_prepare(url=url, policy=policy, credential=credential, **kwargs)
            captured["headers"] = headers
            captured["url"] = url
            return headers

        monkeypatch.setattr(memory_broker, "prepare_bound_headers", capture_prepare)

        class _Resp:
            def read(self) -> bytes:
                return json.dumps({"data": [{"id": "r1", "summary": "rule one"}]}).encode()

            def __enter__(self) -> _Resp:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        def fake_guarded(url, policy, *, timeout=3, method="GET", headers=None):  # noqa: ANN001
            captured["fetch_headers"] = dict(headers or {})
            return _Resp()

        import sw_recallium_url

        monkeypatch.setattr(sw_recallium_url, "guarded_urlopen", fake_guarded)
        monkeypatch.setattr(
            sw_recallium_url,
            "load_catalog_rest_policy",
            lambda root, provider_id: _recallium_policy(repo_root),
        )

        script = repo_root / "core" / "providers" / "recallium-rules.py"
        spec = importlib.util.spec_from_file_location("recallium_rules_under_test", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        spec.loader.exec_module(module)
        assert module.main() == 0
        assert captured["fetch_headers"].get("Authorization") == f"Bearer {_TEST_VALUE}"
