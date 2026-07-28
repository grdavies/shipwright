"""Host transport broker adoption tests (PRD 080 18.4 / R1) — Z,O,M,E,I."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import host_lib
from credentials.model import CredentialRef, Principal, Resolution, ResolutionState, ResolvedToken, Secret
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
