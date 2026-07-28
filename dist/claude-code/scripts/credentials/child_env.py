"""Default-deny child-environment constructors (PRD 080 phase 7 / R5)."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence

# Platform variables required for subprocess execution — never credential-bearing.
PLATFORM_ESSENTIAL_KEYS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "USERNAME",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "COMSPEC",
        "WINDIR",
        "APPDATA",
        "LOCALAPPDATA",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "XDG_RUNTIME_DIR",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
    }
)

# GitHub host credential variables — always broker-set for host-CLI children.
GH_HOST_ENV = "GH_HOST"
GH_CONFIG_DIR_ENV = "GH_CONFIG_DIR"

# Sentinel variables that must never be inherited into a sanitized child.
GITHUB_TOKEN_ENV_KEYS: frozenset[str] = frozenset(
    {
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
    }
)

ISSUES_TOKEN_ENV_KEYS: frozenset[str] = frozenset(
    {
        "ISSUES_GITHUB_TOKEN",
        "ISSUES_GITLAB_TOKEN",
        "ISSUES_JIRA_TOKEN",
        "ISSUES_LINEAR_TOKEN",
        "SW_PLANNING_ISSUES_TOKEN",
    }
)

HOST_TOKEN_ENV_KEYS: frozenset[str] = frozenset(
    {
        "GITLAB_TOKEN",
        "BITBUCKET_TOKEN",
    }
)

BROKER_CONTROLLED_GH_KEYS: frozenset[str] = frozenset({GH_HOST_ENV, GH_CONFIG_DIR_ENV})

BLOCKED_INHERITANCE_KEYS: frozenset[str] = (
    GITHUB_TOKEN_ENV_KEYS | ISSUES_TOKEN_ENV_KEYS | HOST_TOKEN_ENV_KEYS | BROKER_CONTROLLED_GH_KEYS
)


class ChildEnvError(ValueError):
    """Invalid child-environment construction request."""


def _validate_declared_context_keys(declared_context_keys: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in declared_context_keys:
        key = str(raw).strip()
        if not key:
            raise ChildEnvError("declared SW context keys must be non-empty")
        if not key.startswith("SW_"):
            raise ChildEnvError(f"context key must start with SW_: {key!r}")
        if key in BLOCKED_INHERITANCE_KEYS:
            raise ChildEnvError(f"context key is credential-bearing and cannot be declared: {key!r}")
        normalized.append(key)
    return tuple(normalized)


def _platform_essentials(parent: Mapping[str, str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in PLATFORM_ESSENTIAL_KEYS:
        if key in parent:
            env[key] = parent[key]
    return env


def _declared_sw_context(parent: Mapping[str, str], declared_context_keys: Sequence[str]) -> dict[str, str]:
    keys = _validate_declared_context_keys(declared_context_keys)
    env: dict[str, str] = {}
    for key in keys:
        if key in parent:
            env[key] = parent[key]
    return env


def build_hook_verify_child_env(
    parent: Mapping[str, str] | None = None,
    *,
    declared_context_keys: Sequence[str] = (),
    pythonpath: str | None = None,
) -> dict[str, str]:
    """Build a hook/verify child environment from allowlists only (no copy-and-delete)."""
    source = parent if parent is not None else os.environ
    env = _platform_essentials(source)
    env.update(_declared_sw_context(source, declared_context_keys))
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    return env


def build_host_cli_child_env(
    parent: Mapping[str, str] | None = None,
    *,
    declared_context_keys: Sequence[str] = (),
    credential_env_name: str,
    credential_env_value: str,
    gh_host: str,
    gh_config_dir: str,
    pythonpath: str | None = None,
) -> dict[str, str]:
    """Build a host-CLI child environment with one broker-injected credential variable."""
    name = str(credential_env_name).strip()
    if not name:
        raise ChildEnvError("credential_env_name is required")
    if name.startswith("SW_"):
        raise ChildEnvError("credential_env_name must not be an SW context key")

    source = parent if parent is not None else os.environ
    env = build_hook_verify_child_env(
        source,
        declared_context_keys=declared_context_keys,
        pythonpath=pythonpath,
    )
    env[name] = credential_env_value
    env[GH_HOST_ENV] = gh_host
    env[GH_CONFIG_DIR_ENV] = gh_config_dir
    return env


def spawn_canary_probe(env: Mapping[str, str], *, keys: Sequence[str]) -> dict[str, str | None]:
    """Spawn a minimal child that reports selected environment values (test helper)."""
    import json
    import subprocess

    script = (
        "import json, os, sys\n"
        "keys = json.loads(sys.argv[1])\n"
        "print(json.dumps({k: os.environ.get(k) for k in keys}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, json.dumps(list(keys))],
        env=dict(env),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)
