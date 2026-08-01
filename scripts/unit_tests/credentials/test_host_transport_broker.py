"""Host transport broker adoption tests (PRD 080 18.4 / R1) — Z,O,M,E,I."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import host_lib
import memory_broker
import memory_lib
from credentials.model import CredentialRef, Principal, Resolution, ResolutionState, ResolvedToken, Secret
from memory_provider_catalog import get_provider, load_catalog
from sw_recallium_url import rest_fetch_policy_from_catalog_entry
from _sw import host_transport


_TEST_VALUE = "unit-test-host-transport-broker-value-abcdef"


def _write_config(root: Path, host: dict) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps({"projectId": "acme-demo", "host": host}),
        encoding="utf-8",
    )


class TestNoCredential:
    def test_no_credential_is_explicitly_no_auth_without_default_table(self, tmp_path: Path) -> None:
        assert not hasattr(host_lib, "DEFAULT_TOKEN_ENV")
        _write_config(tmp_path, {"provider": "github", "remote": "origin"})
        resolution = host_lib.resolve_host_credential(tmp_path, provider="github")
        assert resolution.state is ResolutionState.EXPLICITLY_NO_AUTH
        assert "GITHUB_TOKEN" not in (resolution.ref.value,)


class TestOneResolvedCredential:
    def test_one_resolved_credential_attaches_bearer_via_broker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(tmp_path, {"provider": "github", "remote": "origin", "ssrfAllowlist": ["api.github.com"]})
        credential = Resolution.resolved(
            CredentialRef("github-work"),
            ResolvedToken(Secret(_TEST_VALUE), Principal(profile="work")),
        )
        captured: dict[str, object] = {}

        def fake_retry(*, provider, config, method, request_fn, serial_gate):  # noqa: ANN001
            result = request_fn()
            captured["status"] = result.status_code
            outcome = MagicMock()
            outcome.result = result
            outcome.to_json.return_value = {"verdict": "ok", "statusCode": result.status_code}
            return outcome

        class _Resp:
            status = 200
            headers = {"Content-Type": "application/json"}

            def read(self) -> bytes:
                return b"{}"

            def __enter__(self) -> _Resp:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        def fake_open(req, timeout=120):  # noqa: ANN001
            captured["headers"] = dict(req.headers)
            captured["url"] = req.full_url
            return _Resp()

        monkeypatch.setattr(host_transport, "execute_with_retry", fake_retry)
        monkeypatch.setattr(host_transport, "build_opener", lambda *a, **k: MagicMock(open=fake_open))

        payload = host_transport.urllib_request(
            method="GET",
            url="https://api.github.com/user",
            root=tmp_path,
            provider="github",
            credential=credential,
        )
        assert payload["verdict"] == "ok"
        assert captured["headers"].get("Authorization") == f"Bearer {_TEST_VALUE}"


class TestManyProviders:
    @pytest.mark.parametrize(
        ("provider", "api_host"),
        [
            ("github", "api.github.com"),
            ("gitlab", "gitlab.com"),
            ("bitbucket", "api.bitbucket.org"),
        ],
    )
    def test_many_providers_resolve_without_implicit_defaults(
        self, tmp_path: Path, provider: str, api_host: str
    ) -> None:
        assert not hasattr(host_lib, "DEFAULT_TOKEN_ENV")
        _write_config(
            tmp_path,
            {
                "provider": provider,
                "remote": "origin",
                "credentialRef": f"{provider}-work",
                "ssrfAllowlist": [api_host],
            },
        )
        resolution = host_lib.resolve_host_credential(tmp_path, provider=provider)
        # Without a selector backend, credentialRef yields unresolved — never invents an env default.
        assert resolution.state is ResolutionState.UNRESOLVED
        assert host_lib.resolve_token_env({"provider": provider}, provider) == ""


class TestOutOfScopeEndpoint:
    def test_out_of_scope_endpoint_refuses_before_authorization_header(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_config(tmp_path, {"provider": "github", "remote": "origin", "ssrfAllowlist": ["api.github.com"]})
        credential = Resolution.resolved(
            CredentialRef("github-work"),
            ResolvedToken(Secret(_TEST_VALUE)),
        )
        called = {"transport": False}

        def boom(*args: object, **kwargs: object) -> None:
            called["transport"] = True
            raise AssertionError("HTTP transport must not run after endpoint refusal")

        monkeypatch.setattr(host_transport, "execute_with_retry", boom)

        payload = host_transport.urllib_request(
            method="GET",
            url="https://evil.example.com/user",
            root=tmp_path,
            provider="github",
            credential=credential,
        )
        assert payload["verdict"] == "fail"
        assert payload.get("reason") in {"ssrf-policy", "endpoint-refused"}
        assert payload.get("authorizationAttached") in (None, False)
        assert called["transport"] is False


class TestImplicitDefaultAbsent:
    def test_implicit_default_table_deleted(self) -> None:
        module = importlib.import_module("host_lib")
        assert not hasattr(module, "DEFAULT_TOKEN_ENV")
        from credentials.config_surface import present_implicit_default_tables

        present = present_implicit_default_tables()
        assert "host_lib.DEFAULT_TOKEN_ENV" not in present


SCRIPTS = Path(__file__).resolve().parents[2]


def _write_memory_config(root: Path, memory: dict) -> None:
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
        _write_memory_config(
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
        _write_memory_config(
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
