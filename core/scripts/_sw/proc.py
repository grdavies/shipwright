"""Cross-platform subprocess helpers that never invoke a shell (R30 support)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any


def run(
    args: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    timeout: float | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run *args* without shell invocation; decode stdout/stderr as text."""
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        env=None if env is None else dict(env),
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
    env: Mapping[str, str] | None = None,
) -> subprocess.Popen[str]:
    """Start a child process without shell invocation."""
    return subprocess.Popen(
        list(args),
        cwd=cwd,
        env=None if env is None else dict(env),
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
