"""Broker send-path enforcement tests (PRD 080 3.4 / R3)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from credentials.send_path import authorization_header, broker_send


_TEST_VALUE = "unit-test-broker-send-value-abcdef"


@dataclass
class _StubResponse:
    redirect_url: str | None = None


class TestBrokerSendPathRefusal:
    def test_off_allowlist_api_base_refuses_before_auth(self) -> None:
        result = broker_send(
            api_base="https://evil.example.com",
            allowed_hosts=["api.github.com"],
            bearer_token=_TEST_VALUE,
        )
        assert result.refused
        assert authorization_header(result) is None

    def test_allowed_api_base_constructs_bearer_header(self) -> None:
        result = broker_send(
            api_base="https://api.github.com",
            allowed_hosts=["api.github.com"],
            bearer_token=_TEST_VALUE,
            path="/user",
        )
        assert not result.refused
        assert authorization_header(result) == f"Bearer {_TEST_VALUE}"

    def test_repository_redirect_off_allowlist_refuses_before_follow(self) -> None:
        def transport(url: str, *, method: str, headers: dict[str, str]) -> _StubResponse:
            assert url == "https://api.github.com/start"
            assert headers.get("Authorization") == f"Bearer {_TEST_VALUE}"
            return _StubResponse(redirect_url="https://evil.example.com/next")

        result = broker_send(
            api_base="https://api.github.com/start",
            allowed_hosts=["api.github.com"],
            bearer_token=_TEST_VALUE,
            transport=transport,
        )
        assert result.refused
        assert "not allowlisted" in (result.reason or "")
        assert authorization_header(result) is None

    def test_many_redirects_on_allowlist_complete_successfully(self) -> None:
        calls: list[str] = []

        def transport(url: str, *, method: str, headers: dict[str, str]) -> _StubResponse:
            calls.append(url)
            if url.endswith("/start"):
                return _StubResponse(redirect_url="/middle")
            if url.endswith("/middle"):
                return _StubResponse(redirect_url="/done")
            return _StubResponse()

        result = broker_send(
            api_base="https://api.github.com/start",
            allowed_hosts=["api.github.com"],
            bearer_token=_TEST_VALUE,
            transport=transport,
        )
        assert not result.refused
        assert len(calls) == 3
        assert authorization_header(result) == f"Bearer {_TEST_VALUE}"

    def test_http_api_base_is_refused_without_bearer(self) -> None:
        result = broker_send(
            api_base="http://api.github.com",
            allowed_hosts=["api.github.com"],
            bearer_token=_TEST_VALUE,
        )
        assert result.refused
        assert authorization_header(result) is None

    @pytest.mark.parametrize(
        "api_base",
        [
            "https://" + "secret" + "@api.github.com",
            "https://api.github.com:443@" + "other.example.com",
        ],
    )
    def test_userinfo_api_base_is_refused(self, api_base: str) -> None:
        result = broker_send(
            api_base=api_base,
            allowed_hosts=["api.github.com"],
            bearer_token=_TEST_VALUE,
        )
        assert result.refused
        assert authorization_header(result) is None
