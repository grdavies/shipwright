"""Endpoint downgrade refusal tests (PRD 080 3.3 / R3)."""

from __future__ import annotations

import pytest

from credentials.endpoint_guard import EndpointGuardError, normalize_allowed_hosts, validate_destination
from credentials.endpoint_guard import validate_redirect_destination


class TestEndpointGuardAllowlist:
    def test_empty_allowlist_refuses_every_host(self) -> None:
        allowlist = normalize_allowed_hosts([])
        with pytest.raises(EndpointGuardError, match="not allowlisted"):
            validate_destination("https://api.github.com/user", allowlist)

    def test_one_allowed_host_permits_https_destination(self) -> None:
        allowlist = normalize_allowed_hosts(["api.github.com"])
        parsed = validate_destination("https://api.github.com/repos", allowlist)
        assert parsed.hostname == "api.github.com"


class TestEndpointGuardDowngradeRefusal:
    def test_http_destination_is_refused(self) -> None:
        allowlist = normalize_allowed_hosts(["api.github.com"])
        with pytest.raises(EndpointGuardError, match="only https"):
            validate_destination("http://api.github.com/user", allowlist)

    def test_userinfo_bearing_url_is_refused(self) -> None:
        allowlist = normalize_allowed_hosts(["api.github.com"])
        userinfo_url = "https://" + "secret" + "@api.github.com/user"
        with pytest.raises(EndpointGuardError, match="userinfo"):
            validate_destination(userinfo_url, allowlist)

    def test_off_allowlist_host_is_refused(self) -> None:
        allowlist = normalize_allowed_hosts(["api.github.com"])
        with pytest.raises(EndpointGuardError, match="not allowlisted"):
            validate_destination("https://evil.example.com/user", allowlist)


class TestEndpointGuardRedirectBoundary:
    def test_redirect_leaving_allowlist_is_refused(self) -> None:
        allowlist = normalize_allowed_hosts(["api.github.com"])
        with pytest.raises(EndpointGuardError, match="not allowlisted"):
            validate_redirect_destination(
                original_url="https://api.github.com/start",
                redirect_url="https://evil.example.com/continue",
                allowed_hosts=allowlist,
            )

    def test_redirect_staying_on_allowlist_is_permitted(self) -> None:
        allowlist = normalize_allowed_hosts(["api.github.com"])
        parsed = validate_redirect_destination(
            original_url="https://api.github.com/start",
            redirect_url="https://api.github.com/continue",
            allowed_hosts=allowlist,
        )
        assert parsed.hostname == "api.github.com"
