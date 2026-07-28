"""Canary child-environment spawn tests (PRD 080 7.3 / R5)."""

from __future__ import annotations

import pytest

from credentials.child_env import (
    BROKER_CONTROLLED_GH_KEYS,
    GITHUB_TOKEN_ENV_KEYS,
    GH_CONFIG_DIR_ENV,
    GH_HOST_ENV,
    HOST_TOKEN_ENV_KEYS,
    ISSUES_TOKEN_ENV_KEYS,
    build_hook_verify_child_env,
    build_host_cli_child_env,
    spawn_canary_probe,
)

SENTINEL = "sentinel-must-not-leak"


def _polluted_parent() -> dict[str, str]:
    parent = {
        "PATH": "/usr/bin",
        "HOME": "/home/tester",
        GH_HOST_ENV: SENTINEL,
        GH_CONFIG_DIR_ENV: SENTINEL,
    }
    for key in GITHUB_TOKEN_ENV_KEYS | ISSUES_TOKEN_ENV_KEYS | HOST_TOKEN_ENV_KEYS:
        parent[key] = SENTINEL
    parent["SW_RUN_DIR"] = ".cursor/sw-deliver-runs/canary"
    parent["SW_PHASE_SLUG"] = "canary-phase"
    return parent


CANARY_KEYS = tuple(
    sorted(GITHUB_TOKEN_ENV_KEYS | ISSUES_TOKEN_ENV_KEYS | HOST_TOKEN_ENV_KEYS | BROKER_CONTROLLED_GH_KEYS)
)


class TestHookVerifyCanary:
    def test_sentinel_tokens_absent_declared_context_survives(self) -> None:
        parent = _polluted_parent()
        env = build_hook_verify_child_env(
            parent,
            declared_context_keys=("SW_RUN_DIR", "SW_PHASE_SLUG"),
        )
        observed = spawn_canary_probe(env, keys=CANARY_KEYS + ("SW_RUN_DIR", "SW_PHASE_SLUG"))
        for key in CANARY_KEYS:
            assert observed[key] is None, key
        assert observed["SW_RUN_DIR"] == parent["SW_RUN_DIR"]
        assert observed["SW_PHASE_SLUG"] == parent["SW_PHASE_SLUG"]


class TestHostCliCanary:
    def test_sentinel_tokens_absent_broker_values_present(self) -> None:
        parent = _polluted_parent()
        env = build_host_cli_child_env(
            parent,
            declared_context_keys=("SW_RUN_DIR",),
            credential_env_name="GITHUB_TOKEN",
            credential_env_value="broker-github-token",
            gh_host="github.com",
            gh_config_dir="/broker/gh-config",
        )
        observed = spawn_canary_probe(env, keys=CANARY_KEYS + ("GITHUB_TOKEN", "SW_RUN_DIR"))
        for key in CANARY_KEYS:
            if key == "GITHUB_TOKEN":
                assert observed[key] == "broker-github-token"
            else:
                assert observed[key] != SENTINEL, key
        assert observed[GH_HOST_ENV] == "github.com"
        assert observed[GH_CONFIG_DIR_ENV] == "/broker/gh-config"
        assert observed["GH_TOKEN"] is None
        assert observed["SW_RUN_DIR"] == parent["SW_RUN_DIR"]
