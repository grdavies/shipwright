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

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from credentials.child_env import (  # noqa: E402
    build_hook_verify_child_env,
    build_host_cli_child_env,
)


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


def materialize_child_env(
    child_env: ChildEnvSpec | None,
    *,
    parent: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a child environment from one of the two allowlist constructors."""
    if child_env is None:
        source = parent if parent is not None else os.environ
        return build_hook_verify_child_env(source)
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


def which_executable(name: str) -> str | None:
    """Resolve an executable on PATH without invoking a shell."""
    return shutil.which(name)
