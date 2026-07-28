"""Allowlist child-environment constructor tests (PRD 080 7.2 / R5)."""

from __future__ import annotations

import os

import pytest

from credentials.child_env import (
    GH_CONFIG_DIR_ENV,
    GH_HOST_ENV,
    build_hook_verify_child_env,
    build_host_cli_child_env,
)


def _parent(**overrides: str) -> dict[str, str]:
    base = {
        "PATH": "/usr/bin",
        "HOME": "/home/tester",
        "GITHUB_TOKEN": "parent-github-token",
        "GH_TOKEN": "parent-gh-token",
        "GH_ENTERPRISE_TOKEN": "parent-enterprise",
        "GITHUB_ENTERPRISE_TOKEN": "parent-github-enterprise",
        "ISSUES_GITHUB_TOKEN": "parent-issues-github",
        "ISSUES_GITLAB_TOKEN": "parent-issues-gitlab",
        "ISSUES_JIRA_TOKEN": "parent-issues-jira",
        "ISSUES_LINEAR_TOKEN": "parent-issues-linear",
        "SW_PLANNING_ISSUES_TOKEN": "parent-planning-issues",
        "GITLAB_TOKEN": "parent-gitlab",
        "BITBUCKET_TOKEN": "parent-bitbucket",
        GH_HOST_ENV: "parent.example.com",
        GH_CONFIG_DIR_ENV: "/parent/gh-config",
        "SW_RUN_DIR": ".cursor/sw-deliver-runs/example",
        "SW_PHASE_MODE": "1",
        "UNDECLARED_SECRET": "must-not-forward",
    }
    base.update(overrides)
    return base


class TestHookVerifyAllowlist:
    def test_empty_parent_yields_platform_only(self) -> None:
        env = build_hook_verify_child_env({})
        assert env == {}
        assert "GITHUB_TOKEN" not in env
        assert "UNDECLARED_SECRET" not in env

    def test_one_declared_context_key_survives(self) -> None:
        parent = _parent()
        env = build_hook_verify_child_env(
            parent,
            declared_context_keys=("SW_RUN_DIR",),
        )
        assert env["SW_RUN_DIR"] == parent["SW_RUN_DIR"]
        assert "SW_PHASE_MODE" not in env
        assert "GITHUB_TOKEN" not in env
        assert "UNDECLARED_SECRET" not in env

    def test_many_declared_context_keys_survive(self) -> None:
        parent = _parent()
        env = build_hook_verify_child_env(
            parent,
            declared_context_keys=("SW_RUN_DIR", "SW_PHASE_MODE"),
        )
        assert env["SW_RUN_DIR"] == parent["SW_RUN_DIR"]
        assert env["SW_PHASE_MODE"] == parent["SW_PHASE_MODE"]
        assert "UNDECLARED_SECRET" not in env

    def test_undeclared_key_is_not_forwarded(self) -> None:
        parent = _parent()
        env = build_hook_verify_child_env(parent, declared_context_keys=())
        assert "UNDECLARED_SECRET" not in env
        assert "SW_RUN_DIR" not in env


class TestHostCliAllowlist:
    def test_broker_sets_gh_host_and_config_dir(self) -> None:
        parent = _parent()
        env = build_host_cli_child_env(
            parent,
            declared_context_keys=("SW_RUN_DIR",),
            credential_env_name="GITHUB_TOKEN",
            credential_env_value="broker-token",
            gh_host="github.com",
            gh_config_dir="/broker/gh-config",
        )
        assert env[GH_HOST_ENV] == "github.com"
        assert env[GH_CONFIG_DIR_ENV] == "/broker/gh-config"
        assert env[GH_HOST_ENV] != parent[GH_HOST_ENV]
        assert env[GH_CONFIG_DIR_ENV] != parent[GH_CONFIG_DIR_ENV]
        assert env["GITHUB_TOKEN"] == "broker-token"
        assert "GH_TOKEN" not in env
        assert env["SW_RUN_DIR"] == parent["SW_RUN_DIR"]

    def test_exactly_one_broker_injected_credential_variable(self) -> None:
        parent = _parent()
        env = build_host_cli_child_env(
            parent,
            credential_env_name="GH_TOKEN",
            credential_env_value="only-one",
            gh_host="github.com",
            gh_config_dir="/broker/gh-config",
        )
        credential_keys = [key for key in env if key.endswith("TOKEN") or key == "GH_TOKEN"]
        assert credential_keys == ["GH_TOKEN"]
        assert env["GH_TOKEN"] == "only-one"
