"""Two-repository two-account isolation tests (PRD 080 22.4 / R7, R5)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from credentials.child_env import (
    GITHUB_TOKEN_ENV_KEYS,
    build_host_cli_child_env,
    spawn_canary_probe,
)
from credentials.doctor import diagnose_surface
from credentials.config_surface import resolve_config_surface
from credentials.model import CredentialRef, Principal, ResolutionState, Secret
from credentials.pairing_store import approve_pairing, record_first_use
from credentials.resolver import BackendResolveResult, RepositoryContext, register_backend_adapter, resolve_lookup

SENTINEL = "sentinel-must-not-leak"


class _PerAccountBackend:
    def resolve(self, entry, **kwargs):  # noqa: ANN001
        account = entry.account or entry.ref
        return BackendResolveResult(
            state=ResolutionState.RESOLVED,
            token=Secret(f"broker-token-{account}"),
            principal=Principal(profile=account, account=account),
            backend=entry.backend,
        )


def _valid_entry(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "backend": "environment",
        "provider": "github",
        "hostname": "github.com",
        "account": "work",
        "allowedRepos": ["owner/repo"],
        "allowedProjectIds": ["proj-1"],
        "allowedEndpoints": ["https://api.github.com"],
    }
    payload.update(overrides)
    return payload


def _write_selector(path: Path, entries: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    os.chmod(path, 0o600)


def _write_pairing(path: Path, ref: str, project_id: str, remote: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    record_first_use(ref, project_id, remote, path=path, skip_integrity=True)
    approve_pairing(ref, project_id, remote, path=path, skip_integrity=True)


def _write_config(root: Path, project_id: str, credential_ref: str, repo_slug: str) -> None:
    cfg = {
        "projectId": project_id,
        "host": {
            "provider": "github",
            "credentialRef": credential_ref,
        },
        "planning": {
            "store": {
                "issues": {
                    "provider": "github-issues",
                    "credentialRef": credential_ref,
                },
            },
        },
    }
    allowed = [repo_slug]
    path = root / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return allowed


def _init_git_remote(root: Path, slug: str) -> str:
    remote = f"https://github.com/{slug}.git"
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)
    return remote


class TestTwoRepoTwoAccountIsolation:
    def test_interleaved_operations_do_not_cross_select_accounts(
        self, tmp_path: Path
    ) -> None:
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        remote_a = _init_git_remote(repo_a, "acme/alpha")
        remote_b = _init_git_remote(repo_b, "acme/beta")

        selector = tmp_path / "credential-selector.json"
        _write_selector(
            selector,
            {
                "github-alice": _valid_entry(
                    account="alice",
                    allowedRepos=["acme/alpha"],
                    allowedProjectIds=["proj-alpha"],
                ),
                "github-bob": _valid_entry(
                    account="bob",
                    allowedRepos=["acme/beta"],
                    allowedProjectIds=["proj-beta"],
                ),
            },
        )

        _write_config(repo_a, "proj-alpha", "github-alice", "acme/alpha")
        _write_config(repo_b, "proj-beta", "github-bob", "acme/beta")
        pairing = tmp_path / "credential-pairings.json"
        _write_pairing(pairing, "github-alice", "proj-alpha", remote_a)
        _write_pairing(pairing, "github-bob", "proj-beta", remote_b)

        register_backend_adapter("environment", _PerAccountBackend())

        context_a = RepositoryContext(
            remote=remote_a,
            repo_slug="acme/alpha",
            project_id="proj-alpha",
            destination_endpoint="https://api.github.com",
        )
        result_a = resolve_lookup(
            CredentialRef("github-alice"),
            provider="github",
            purpose="host",
            context=context_a,
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )
        assert result_a.principal == Principal(profile="alice", account="alice")

        context_b = RepositoryContext(
            remote=remote_b,
            repo_slug="acme/beta",
            project_id="proj-beta",
            destination_endpoint="https://api.github.com",
        )
        result_b = resolve_lookup(
            CredentialRef("github-bob"),
            provider="github",
            purpose="planning",
            context=context_b,
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )
        assert result_b.principal == Principal(profile="bob", account="bob")
        assert result_a.principal != result_b.principal

        surface_a = resolve_config_surface(
            json.loads((repo_a / ".cursor/workflow.config.json").read_text(encoding="utf-8"))
        )
        surface_b = resolve_config_surface(
            json.loads((repo_b / ".cursor/workflow.config.json").read_text(encoding="utf-8"))
        )
        diag_a = diagnose_surface(
            repo_a,
            json.loads((repo_a / ".cursor/workflow.config.json").read_text(encoding="utf-8")),
            surface_a.host,
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
            register_env_backend=False,
        )
        diag_b = diagnose_surface(
            repo_b,
            json.loads((repo_b / ".cursor/workflow.config.json").read_text(encoding="utf-8")),
            surface_b.planning,
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
            register_env_backend=False,
        )
        assert diag_a.resolved_principal["account"] == "alice"
        assert diag_b.resolved_principal["account"] == "bob"

    def test_child_process_does_not_inherit_ambient_tokens(self, tmp_path: Path) -> None:
        parent = {key: SENTINEL for key in GITHUB_TOKEN_ENV_KEYS}
        parent["PATH"] = "/usr/bin"
        parent["SW_RUN_DIR"] = ".cursor/sw-deliver-runs/two-repo"
        env = build_host_cli_child_env(
            parent,
            declared_context_keys=("SW_RUN_DIR",),
            credential_env_name="GITHUB_TOKEN",
            credential_env_value="broker-only-token",
            gh_host="github.com",
            gh_config_dir="/broker/gh",
        )
        observed = spawn_canary_probe(
            env,
            keys=tuple(sorted(GITHUB_TOKEN_ENV_KEYS)) + ("GITHUB_TOKEN", "SW_RUN_DIR"),
        )
        for key in GITHUB_TOKEN_ENV_KEYS:
            if key == "GITHUB_TOKEN":
                assert observed[key] == "broker-only-token"
            else:
                assert observed[key] != SENTINEL, key
        assert observed["SW_RUN_DIR"] == parent["SW_RUN_DIR"]
