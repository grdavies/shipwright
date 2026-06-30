"""Fail-closed CPython >= 3.9 interpreter probe (R2)."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

from _sw import proc

_MIN_VERSION = (3, 9)
_STORE_STUB_MARKERS = (
    "Python was not found",
    "run without arguments to install from the Microsoft Store",
    "App execution aliases",
)
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass(frozen=True)
class InterpreterResult:
    executable: list[str]
    version: tuple[int, int, int]
    version_text: str


class InterpreterProbeError(RuntimeError):
    """Raised when no conforming interpreter is available."""


def _parse_version(text: str) -> tuple[int, int, int] | None:
    for line in text.splitlines():
        match = _VERSION_RE.search(line.strip())
        if match:
            patch = int(match.group(3) or 0)
            return int(match.group(1)), int(match.group(2)), patch
    return None


def _is_store_stub(stderr: str, stdout: str) -> bool:
    combined = f"{stdout}\n{stderr}".lower()
    return any(marker.lower() in combined for marker in _STORE_STUB_MARKERS)


def _probe_candidate(args: list[str]) -> InterpreterResult | None:
    if not args:
        return None
    if args[0] != "py" and proc.which_executable(args[0]) is None:
        return None
    completed = proc.run(
        [*args, "-c", "import sys; print(sys.version)"],
        timeout=15.0,
    )
    if completed.returncode != 0:
        if _is_store_stub(completed.stderr, completed.stdout):
            return None
        return None
    version = _parse_version(completed.stdout)
    if version is None:
        return None
    if version[0] < 3 or (version[0] == 3 and version[1] < _MIN_VERSION[1]):
        return None
    if version[0] >= 4:
        return None
    return InterpreterResult(
        executable=args,
        version=version,
        version_text=completed.stdout.strip(),
    )


def candidate_commands() -> list[list[str]]:
    override = os.environ.get("SW_PYTHON", "").strip()
    if override:
        return [[override]]
    candidates: list[list[str]] = []
    for name in ("python3", "python"):
        if proc.which_executable(name):
            candidates.append([name])
    if proc.which_executable("py"):
        candidates.append(["py", "-3"])
    return candidates


def probe(required: tuple[int, int] = _MIN_VERSION) -> InterpreterResult:
    errors: list[str] = []
    for args in candidate_commands():
        result = _probe_candidate(args)
        if result is None:
            errors.append(f"rejected: {' '.join(args)}")
            continue
        if result.version[0:2] < required:
            errors.append(
                f"too old: {' '.join(args)} ({result.version_text})"
            )
            continue
        return result
    detail = "; ".join(errors) if errors else "no python executable found"
    raise InterpreterProbeError(
        "No conforming CPython >= 3.9 interpreter found. "
        f"Install Python 3.9+ and ensure `python3`, `python`, or `py -3` works. ({detail})"
    )


def remediation_message() -> str:
    try:
        probe()
        return "interpreter ok"
    except InterpreterProbeError as exc:
        return str(exc)


def current_interpreter_ok() -> bool:
    version = sys.version_info
    return version.major == 3 and version >= _MIN_VERSION
