"""Tri-state branch-protection probe fixtures (PRD 080 18.5 / R3) — Z,O,E,S."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import host_lib
from credentials.model import CredentialRef, Resolution, ResolutionState


_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _load_docs_merge():
    path = _SCRIPTS / "docs-merge.py"
    spec = importlib.util.spec_from_file_location("docs_merge_mod", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_private_repo(tmp_path: Path, *, credential_ref: str | None = "github-work") -> Path:
    cfg_dir = tmp_path / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    host: dict[str, object] = {
        "provider": "github",
        "remote": "origin",
        "apiBaseUrl": "https://api.github.com",
    }
    if credential_ref is not None:
        host["credentialRef"] = credential_ref
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps(
            {
                "projectId": "acme-demo",
                "defaultBaseBranch": "main",
                "host": host,
                "docs": {"twoTrack": {"allowDirectTrunk": True}},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


class TestCredentialRefUnresolved:
    def test_private_repo_credential_ref_without_token_is_unresolved_pr_route(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _write_private_repo(tmp_path)
        monkeypatch.setattr(
            host_lib,
            "git_remote_url",
            lambda _root, _remote: "https://github.com/acme/private-repo.git",
        )
        monkeypatch.setattr(
            host_lib,
            "resolve",
            lambda ref, **_kwargs: Resolution.unresolved(ref, reason="unavailable-backend"),
        )

        resolution = host_lib.resolve_host_credential(root, provider="github")
        assert resolution.state is ResolutionState.UNRESOLVED
        assert not resolution.is_explicitly_unauthenticated

        probe = host_lib.probe_github_branch_protection(root, "main")
        assert probe["verdict"] == "ambiguous"
        assert probe["route"] == "pr"
        assert probe["reason"] == "credential-unresolved"
        assert probe.get("protected") is None


class TestUnauthenticated404SelectsPr:
    def test_unauthenticated_404_selects_pull_request_route(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _write_private_repo(tmp_path, credential_ref=None)
        monkeypatch.setattr(
            host_lib,
            "git_remote_url",
            lambda _root, _remote: "https://github.com/acme/private-repo.git",
        )

        def fake_transport(**kwargs: object) -> dict[str, object]:
            assert kwargs.get("credential") is not None
            return {"verdict": "ok", "status": 404, "statusCode": 404, "body": "Not Found"}

        with patch("_sw.host_transport.urllib_request", side_effect=fake_transport):
            probe = host_lib.probe_github_branch_protection(root, "main")

        assert probe["verdict"] == "ambiguous"
        assert probe["route"] == "pr"
        assert probe["reason"] == "unauthenticated-404"

        docs_merge = _load_docs_merge()
        probe_for_docs = {**probe, "allowDirectTrunk": True, "route": "pr"}
        with patch.object(docs_merge, "probe_branch_protection", return_value=probe_for_docs):
            result, code = docs_merge.cmd_direct_trunk(root, dry_run=True)
            assert code == 13
            assert result["error"] == "direct-trunk-refused"
            assert docs_merge._protection_route(root) == "pr"


class TestEmptyDoesNotImplySuccess:
    def test_empty_token_env_without_ref_is_explicit_no_auth_not_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _write_private_repo(tmp_path, credential_ref=None)
        monkeypatch.setattr(
            host_lib,
            "git_remote_url",
            lambda _root, _remote: "https://github.com/acme/private-repo.git",
        )
        resolution = host_lib.resolve_host_credential(root, provider="github")
        assert resolution.state is ResolutionState.EXPLICITLY_NO_AUTH
        assert resolution.state is not ResolutionState.RESOLVED
