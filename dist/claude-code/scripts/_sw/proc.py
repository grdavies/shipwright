"""Cross-platform subprocess helpers that never invoke a shell (R30 support)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HookVerifyEnv:
    """Allowlisted hook/verify child environment specification."""

    declared_context_keys: tuple[str, ...] = ()
    pythonpath: str | None = None
    parent: dict[str, str] | None = None


@dataclass(frozen=True)
class HostCliEnv:
    """Allowlisted host-CLI child environment with one broker credential."""

    declared_context_keys: tuple[str, ...] = ()
    credential_env_name: str = ""
    credential_env_value: str = ""
    gh_host: str = ""
    gh_config_dir: str = ""
    pythonpath: str | None = None
    parent: dict[str, str] | None = None


ChildEnvSpec = HookVerifyEnv | HostCliEnv


class RawChildEnvRejected(TypeError):
    """Raised when callers attempt to pass an untagged environment mapping."""


def _reject_raw_env(env: object) -> None:
    if env is not None:
        raise RawChildEnvRejected(
            "raw environment mappings are rejected; pass child_env=HookVerifyEnv(...) "
            "or child_env=HostCliEnv(...)"
        )


def _child_env_builders():
    scripts_dir = Path(__file__).resolve().parents[1]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from credentials.child_env import build_hook_verify_child_env, build_host_cli_child_env

    return build_hook_verify_child_env, build_host_cli_child_env


def _non_credential_sw_keys(parent: dict[str, str]) -> tuple[str, ...]:
    """SW_* keys safe to forward for internal script dispatch (not credential-bearing)."""
    blocked = {
        "SW_PLANNING_ISSUES_TOKEN",
    }
    return tuple(
        sorted(
            key
            for key in parent
            if key.startswith("SW_") and key not in blocked
        )
    )


def materialize_child_env(
    child_env: ChildEnvSpec | None,
    *,
    parent: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a child environment from one of the two allowlist constructors."""
    build_hook_verify_child_env, build_host_cli_child_env = _child_env_builders()
    if child_env is None:
        # Default internal dispatch (e.g. wave.py → wave_*.py): forward SW_* harness
        # markers so CI-status deliver gate skip still works. Do not inherit host
        # tokens (GITHUB_TOKEN/GH_TOKEN); hooks must pass HookVerifyEnv explicitly.
        # Issue-store contract token is broker-injected for orchestrator children only
        # (PRD 070 separate-project); it is blocked from declared_context_keys.
        source = dict(parent if parent is not None else os.environ)
        env = build_hook_verify_child_env(
            source,
            declared_context_keys=_non_credential_sw_keys(source),
            pythonpath=source.get("PYTHONPATH"),
        )
        # Orchestrator-only injections (hooks must pass HookVerifyEnv and stay token-free).
        planning_token = source.get("SW_PLANNING_ISSUES_TOKEN", "").strip()
        if planning_token:
            env["SW_PLANNING_ISSUES_TOKEN"] = planning_token
        # Host CLI auth for check-gate / gh during deliver-loop (PRD 070 host.tokenEnv).
        for host_key in ("GH_TOKEN", "GITHUB_TOKEN"):
            host_token = source.get(host_key, "").strip()
            if host_token:
                env[host_key] = host_token
                break
        return env
    spec_parent = child_env.parent if child_env.parent is not None else parent
    source = spec_parent if spec_parent is not None else os.environ
    if isinstance(child_env, HookVerifyEnv):
        return build_hook_verify_child_env(
            source,
            declared_context_keys=child_env.declared_context_keys,
            pythonpath=child_env.pythonpath,
        )
    return build_host_cli_child_env(
        source,
        declared_context_keys=child_env.declared_context_keys,
        credential_env_name=child_env.credential_env_name,
        credential_env_value=child_env.credential_env_value,
        gh_host=child_env.gh_host,
        gh_config_dir=child_env.gh_config_dir,
        pythonpath=child_env.pythonpath,
    )


def run(
    args: Sequence[str],
    *,
    cwd: str | None = None,
    child_env: ChildEnvSpec | None = None,
    env: object = None,
    input_text: str | None = None,
    timeout: float | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run *args* without shell invocation; decode stdout/stderr as text."""
    _reject_raw_env(env)
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        env=materialize_child_env(child_env),
        input=input_text,
        timeout=timeout,
        check=False,
        shell=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            list(args),
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed


def run_checked(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Like :func:`run` but raises on non-zero exit."""
    return run(args, check=True, **kwargs)


def spawn(
    args: Sequence[str],
    *,
    cwd: str | None = None,
    child_env: ChildEnvSpec | None = None,
    env: object = None,
) -> subprocess.Popen[str]:
    """Start a child process without shell invocation."""
    _reject_raw_env(env)
    return subprocess.Popen(
        list(args),
        cwd=cwd,
        env=materialize_child_env(child_env),
        shell=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


_HOST_TRANSPORT_CONTEXT_KEYS: tuple[str, ...] = (
    "SW_HOST_FIXTURE",
    "SW_GATE_FIXTURE",
    "SW_GATE_NOW",
    "SW_LOCAL_GATE_FIXTURE",
)


def host_transport_child_env(
    *,
    parent: dict[str, str] | None = None,
) -> HostCliEnv | HookVerifyEnv:
    """Child env for host.py until broker transport migration (PRD 080 phase 18)."""
    source = dict(parent if parent is not None else os.environ)
    token = (source.get("GITHUB_TOKEN") or source.get("GH_TOKEN") or "").strip()
    pythonpath = source.get("PYTHONPATH")
    if not token:
        return HookVerifyEnv(
            declared_context_keys=_HOST_TRANSPORT_CONTEXT_KEYS,
            pythonpath=pythonpath,
            parent=source,
        )
    return HostCliEnv(
        declared_context_keys=_HOST_TRANSPORT_CONTEXT_KEYS,
        credential_env_name="GITHUB_TOKEN",
        credential_env_value=token,
        gh_host=source.get("GH_HOST", "github.com"),
        gh_config_dir=source.get("GH_CONFIG_DIR", ""),
        pythonpath=pythonpath,
        parent=source,
    )


def which_executable(name: str) -> str | None:
    """Resolve an executable on PATH without invoking a shell."""
    return shutil.which(name)
