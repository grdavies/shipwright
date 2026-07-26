"""GitHub non-checks verb classifier migration tests (PRD 079 R5)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

import pytest

_CORE_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CORE_SCRIPTS))

from _sw.host import github as github_mod  # noqa: E402
from _sw.host import _common as common  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[3]

_CTX: dict[str, Any] = {
    "provider": "github",
    "tokenEnv": "GITHUB_TOKEN",
    "apiBase": "https://api.github.com",
    "owner": "acme",
    "repo": "widget",
    "nameWithOwner": "acme/widget",
    "degraded": False,
}

_AUTH_DENIED_NO_BODY = {"verdict": "fail", "statusCode": 401}
_AUTH_DENIED_WITH_BODY = {
    "verdict": "ok",
    "statusCode": 401,
    "body": '{"message":"Bad credentials"}',
}
_RATE_LIMITED = {"verdict": "rate-limited", "statusCode": 403, "retryable": True}

_NON_CHECKS_VERBS: tuple[str, ...] = tuple(
    verb for verb in github_mod.GITHUB_LEGACY_BODY_GUARD_VERBS if verb != "checks"
)


def _handler_for(verb: str) -> Callable[..., tuple[dict[str, Any], int]]:
    return {
        "repo-meta": github_mod._repo_meta,
        "pr-list": github_mod._pr_list,
        "pr-view": github_mod._pr_view,
        "pr-create": github_mod._pr_create,
        "pr-close": github_mod._pr_close,
        "merge": github_mod._merge,
        "review-threads": github_mod._review_threads,
    }[verb]


def _args_for(verb: str) -> list[str]:
    if verb == "repo-meta":
        return []
    if verb == "pr-list":
        return ["--state", "open"]
    if verb == "pr-create":
        return ["--title", "t", "--head", "feat/x", "--base", "main"]
    return ["--number", "42"]


def test_github_legacy_body_guard_baseline_count() -> None:
    assert github_mod.GITHUB_LEGACY_BODY_GUARD_BASELINE_COUNT == 8
    assert len(github_mod.GITHUB_LEGACY_BODY_GUARD_VERBS) == 8
    assert github_mod.GITHUB_LEGACY_BODY_GUARD_VERBS == tuple(
        sorted(github_mod.GITHUB_LEGACY_BODY_GUARD_VERBS)
    )


@pytest.mark.parametrize("verb", _NON_CHECKS_VERBS)
def test_non_checks_verb_auth_denied_without_body_is_classified(
    verb: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(common, "http_request", lambda **_kwargs: dict(_AUTH_DENIED_NO_BODY))
    payload, code = _handler_for(verb)(_REPO_ROOT, dict(_CTX), _args_for(verb))
    assert payload["verdict"] == "fail"
    assert payload["reason"] == "auth-denied"
    assert payload["transportClass"] == "auth-denied"
    assert code == 30


@pytest.mark.parametrize("verb", _NON_CHECKS_VERBS)
def test_non_checks_verb_auth_denied_with_body_is_classified_not_parsed(
    verb: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(common, "http_request", lambda **_kwargs: dict(_AUTH_DENIED_WITH_BODY))
    payload, code = _handler_for(verb)(_REPO_ROOT, dict(_CTX), _args_for(verb))
    assert payload["verdict"] == "fail"
    assert payload["reason"] == "auth-denied"
    assert payload["transportClass"] == "auth-denied"
    assert "data" not in payload
    assert code == 30


@pytest.mark.parametrize("verb", _NON_CHECKS_VERBS)
def test_non_checks_verb_rate_limited_is_classified(
    verb: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(common, "http_request", lambda **_kwargs: dict(_RATE_LIMITED))
    payload, code = _handler_for(verb)(_REPO_ROOT, dict(_CTX), _args_for(verb))
    assert payload["verdict"] == "fail"
    assert payload["reason"] == "rate-limited"
    assert payload["transportClass"] == "rate-limited"
    assert payload.get("retryable") is True
    assert code == 37


def test_remote_ref_exists_uses_classifier_helper() -> None:
    payload, code = common.remote_ref_exists_from_transport(
        verb="remote-ref-exists",
        provider="github",
        branch="feat/x",
        transport={"verdict": "fail", "statusCode": 401},
    )
    assert payload["reason"] == "probe-inconclusive"
    assert code == 30
