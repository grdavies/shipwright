"""PRD 358 D10 — overflow secret-scan and brokered Linear e2e tokens."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_linear_client as plc
from credentials.model import (
    CredentialRef,
    Principal,
    Resolution,
    ResolutionState,
    ResolvedToken,
    Secret,
)
from planning_canonical import CommentRecord


_TEST_VALUE = "unit-test-linear-e2e-broker-value-abcdef"


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ("." + "cursor")).mkdir(parents=True, exist_ok=True)


def _linear_cfg(*, credential_ref: str | None = None, token_env: str | None = "ISSUES_LINEAR_TOKEN") -> dict[str, Any]:
    issues: dict[str, Any] = {"provider": "linear", "teamKey": "ENG"}
    if credential_ref:
        issues["credentialRef"] = credential_ref
    if token_env:
        issues["tokenEnv"] = token_env
    return {
        "projectId": "acme-demo",
        "host": {
            "provider": "github",
            "remote": "origin",
            "ssrfAllowlist": ["api.linear.app", "api.github.com"],
        },
        "planning": {
            "store": {
                "backend": "issue-store",
                "projectKey": "demo",
                "issues": issues,
            }
        },
    }


def test_overflow_post_hits_secret_scan_before_comment_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Overflow comment bodies must pass secret_scan_text before GraphQL commentCreate."""
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg_path = tmp_path / ("." + "cursor") / "workflow.config.json"
    cfg_path.write_text(json.dumps(_linear_cfg(credential_ref="linear-work")), encoding="utf-8")

    credential = Resolution.resolved(
        CredentialRef("linear-work"),
        ResolvedToken(Secret(_TEST_VALUE), Principal(profile="work")),
    )
    monkeypatch.setattr(plc, "require_prd061_facade_projection_ready", lambda root: None)

    posted = {"count": 0}

    def fake_add_comment(self, issue_id: str, body: str, **kwargs: Any) -> CommentRecord:
        posted["count"] += 1
        return CommentRecord(id="comment-1", body=body, markers=list(kwargs.get("markers") or []))

    monkeypatch.setattr(plc.LinearIssuesClient, "add_comment", fake_add_comment)

    client = plc.LinearIssuesClient(tmp_path, credential=credential, cfg=_linear_cfg(credential_ref="linear-work"))
    secret_body = "ghp_" + "A" * 36
    overflow = CommentRecord(id="", body=secret_body, markers=["sw-chunk-overflow"])

    with pytest.raises(SystemExit) as exc:
        client._post_overflow_comments("issue-1", [overflow], head="head")
    assert exc.value.code == 2
    assert posted["count"] == 0


def test_linear_e2e_refuses_token_env_without_credential_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ambient tokenEnv alias cannot satisfy Linear e2e — credentials.resolver required."""
    _init_repo(tmp_path)
    cfg_path = tmp_path / ("." + "cursor") / "workflow.config.json"
    cfg_path.write_text(json.dumps(_linear_cfg(credential_ref=None)), encoding="utf-8")
    monkeypatch.setenv("ISSUES_LINEAR_TOKEN", _TEST_VALUE)

    resolution = plc.resolve_linear_e2e_credential(tmp_path)
    assert resolution.state is ResolutionState.UNRESOLVED
    assert resolution.reason == "linear-e2e-tokenenv-refused"


def test_linear_e2e_uses_credentials_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """credentialRef routes through credentials.resolver for Linear e2e."""
    _init_repo(tmp_path)
    cfg = _linear_cfg(credential_ref="linear-work", token_env="ISSUES_LINEAR_TOKEN")
    cfg_path = tmp_path / ("." + "cursor") / "workflow.config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    expected = Resolution.resolved(
        CredentialRef("linear-work"),
        ResolvedToken(Secret(_TEST_VALUE), Principal(profile="work")),
    )
    resolve_mock = MagicMock(return_value=expected)
    monkeypatch.setattr("credentials.resolver.resolve", resolve_mock)

    resolution = plc.resolve_linear_e2e_credential(tmp_path)
    assert resolution.state is ResolutionState.RESOLVED
    assert resolution.token is not None
    assert resolution.token.token.value == _TEST_VALUE
    resolve_mock.assert_called_once()


def test_acceptance_test_env_scrubs_ambient_linear_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nested acceptance pytest must not inherit ambient ISSUES_LINEAR_TOKEN (D10)."""
    _init_repo(tmp_path)
    cfg = _linear_cfg(credential_ref=None)
    cfg_path = tmp_path / ("." + "cursor") / "workflow.config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    captured: dict[str, str] = {}
    monkeypatch.setenv("ISSUES_LINEAR_TOKEN", _TEST_VALUE)

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env") or {}
        captured["token"] = env.get("ISSUES_LINEAR_TOKEN", "")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        plc,
        "_resolve_acceptance_test",
        lambda root, rel: (tmp_path / "t.py", tmp_path),
    )

    out = plc._acceptance_test_ready(tmp_path, "scripts/unit_tests/planning/test_prd358_overflow_secret_scan.py")
    assert out.get("verdict") == "ready"
    assert captured.get("token") == ""
