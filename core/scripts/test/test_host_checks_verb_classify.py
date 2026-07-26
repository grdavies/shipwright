"""Unit tests for checks verb classify-before-map (PRD 079 R1, R16)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_CORE_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CORE_SCRIPTS))

from _sw.host import bitbucket, github, gitlab  # noqa: E402
from _sw.host._common import (  # noqa: E402
    _transport_envelope_from_fixture,
    checks_from_transport,
    checks_from_transport_fallback,
    fixture_dir,
    map_bitbucket_checks,
    map_github_checks,
    map_gitlab_checks,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHA = "abc123"


def _transport_from_fixture(fixture_name: str, url: str) -> dict[str, Any]:
    map_file = fixture_dir(_REPO_ROOT) / f"transport-{fixture_name}.json"
    mapping = json.loads(map_file.read_text(encoding="utf-8"))
    for pattern, body in mapping.items():
        if pattern.startswith("_"):
            continue
        if pattern in url or url.endswith(pattern):
            return _transport_envelope_from_fixture(body)
    raise KeyError(f"no transport mapping in transport-{fixture_name}.json for {url}")


def _patch_http_for_fixture(monkeypatch: pytest.MonkeyPatch, fixture_name: str, module: Any) -> None:
    def fake_http_request(**kwargs: Any) -> dict[str, Any]:
        return _transport_from_fixture(fixture_name, kwargs["url"])

    monkeypatch.setattr(module.common, "http_request", fake_http_request)


def _github_ctx() -> dict[str, Any]:
    return {
        "owner": "owner",
        "repo": "repo",
        "apiBase": "https://api.github.com",
        "tokenEnv": "GITHUB_TOKEN",
    }


def _gitlab_ctx() -> dict[str, Any]:
    return {
        "project": "owner%2Frepo",
        "apiBase": "https://gitlab.com/api/v4",
        "tokenEnv": "GITLAB_TOKEN",
    }


def _bitbucket_ctx() -> dict[str, Any]:
    return {
        "repoPath": "repositories/owner/repo",
        "apiBase": "https://api.bitbucket.org/2.0",
        "tokenEnv": "BITBUCKET_TOKEN",
    }


def test_gap182_auth_error_body_maps_to_empty_without_classifier() -> None:
    """Pre-fix mapper would collapse auth denial into an empty check set (gap-182)."""
    body = '{"message":"Bad credentials"}'
    assert map_github_checks(body) == []


@pytest.mark.parametrize(
    ("transport_class", "transport", "expected_reason", "expected_exit"),
    [
        (
            "auth-denied",
            {"verdict": "ok", "statusCode": 401, "body": '{"message":"Bad credentials"}'},
            "auth-denied",
            30,
        ),
        (
            "not-found",
            {"verdict": "ok", "statusCode": 404, "body": '{"message":"Not Found"}'},
            "auth-denied",
            30,
        ),
        (
            "rate-limited",
            {
                "verdict": "ok",
                "statusCode": 403,
                "headers": {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"},
                "body": '{"message":"API rate limit exceeded"}',
            },
            "rate-limited",
            37,
        ),
        (
            "inconclusive",
            {"verdict": "ok", "statusCode": 402, "body": '{"message":"Payment Required"}'},
            "inconclusive",
            30,
        ),
    ],
)
def test_checks_from_transport_non_ok_never_emits_empty_ok(
    transport_class: str,
    transport: dict[str, Any],
    expected_reason: str,
    expected_exit: int,
) -> None:
    payload, code = checks_from_transport(
        provider="github",
        transport=transport,
        map_checks=map_github_checks,
    )
    assert payload["verdict"] == "fail"
    assert payload["transportClass"] == transport_class
    assert payload["reason"] == expected_reason
    assert code == expected_exit
    assert payload.get("data") != []


def test_checks_from_transport_ok_maps_checks() -> None:
    transport = {
        "verdict": "ok",
        "statusCode": 200,
        "body": '{"check_runs":[{"name":"ci","status":"completed","conclusion":"success"}]}',
    }
    payload, code = checks_from_transport(
        provider="github",
        transport=transport,
        map_checks=map_github_checks,
    )
    assert payload["verdict"] == "ok"
    assert code == 0
    assert len(payload["data"]) == 1
    assert payload["data"][0]["name"] == "ci"


def test_checks_from_transport_fallback_gitlab_aborts_on_auth_denied() -> None:
    transports = [
        {"verdict": "ok", "statusCode": 403, "body": '{"message":"403 Forbidden"}'},
        {
            "verdict": "ok",
            "statusCode": 200,
            "body": '[{"name":"ci","status":"success"}]',
        },
    ]
    payload, code = checks_from_transport_fallback(
        provider="gitlab",
        transports=transports,
        map_checks=map_gitlab_checks,
    )
    assert payload["verdict"] == "fail"
    assert payload["transportClass"] == "auth-denied"
    assert code == 30


def test_checks_from_transport_fallback_gitlab_uses_second_on_inconclusive() -> None:
    transports = [
        {"verdict": "ok", "statusCode": 500, "body": '{"message":"error"}'},
        {
            "verdict": "ok",
            "statusCode": 200,
            "body": '[{"name":"ci","status":"success"}]',
        },
    ]
    payload, code = checks_from_transport_fallback(
        provider="gitlab",
        transports=transports,
        map_checks=map_gitlab_checks,
    )
    assert payload["verdict"] == "ok"
    assert code == 0
    assert payload["data"][0]["name"] == "ci"


@pytest.mark.parametrize(
    ("provider", "fixture_suffix", "ctx_factory", "module"),
    [
        ("github", "github-checks", _github_ctx, github),
        ("gitlab", "gitlab-checks", _gitlab_ctx, gitlab),
        ("bitbucket", "bitbucket-checks", _bitbucket_ctx, bitbucket),
    ],
)
@pytest.mark.parametrize(
    ("outcome", "expect_ok"),
    [
        ("auth-denied", False),
        ("not-found", False),
        ("rate-limited", False),
        ("inconclusive", False),
        ("ok", True),
    ],
)
def test_gap182_per_provider_classifier_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    fixture_suffix: str,
    ctx_factory: Any,
    module: Any,
    outcome: str,
    expect_ok: bool,
) -> None:
    _patch_http_for_fixture(monkeypatch, f"{fixture_suffix}-{outcome}", module)
    payload, code = module._checks(_REPO_ROOT, ctx_factory(), ["--sha", _SHA])
    if expect_ok:
        assert payload["verdict"] == "ok"
        assert code == 0
        assert isinstance(payload.get("data"), list)
        assert payload["data"]
    else:
        assert payload["verdict"] == "fail"
        assert not (payload["verdict"] == "ok" and payload.get("data") == [])
        assert payload["transportClass"] == outcome
        if outcome == "rate-limited":
            assert code == 37
            assert payload.get("retryable") is True
        elif outcome in ("auth-denied", "not-found"):
            assert code == 30
            assert payload.get("reason") == "auth-denied"
            assert payload.get("retryable") is False
        else:
            assert code == 30
            assert payload.get("reason") == "inconclusive"


def test_github_checks_auth_denied_never_calls_mapper(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http_for_fixture(monkeypatch, "github-checks-auth-denied", github)
    with patch.object(
        github.common,
        "map_github_checks",
        side_effect=AssertionError("mapper must not run"),
    ) as mocked:
        payload, _code = github._checks(_REPO_ROOT, _github_ctx(), ["--sha", _SHA])
        mocked.assert_not_called()
    assert payload["verdict"] == "fail"
    assert payload["transportClass"] == "auth-denied"
