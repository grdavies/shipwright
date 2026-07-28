#!/usr/bin/env python3
"""Canonical bootstrap CLI for consumer script invocation (PRD 078 TR2, R12, R13).

Discovers a trust-marked plugin scripts root via ``sw_scripts_resolve``, then prints or
executes a named helper. Consumers need no repo-local façade files.

Usage:
  python3 scripts/sw_bootstrap.py [--root WORKSPACE] --print SCRIPT
  python3 scripts/sw_bootstrap.py [--root WORKSPACE] SCRIPT [-- SCRIPT_ARGS...]
  python3 scripts/sw_bootstrap.py --require-envelope SCRIPT [-- SCRIPT_ARGS...]

``--print`` emits the resolved absolute helper path on stdout. Without ``--print``, the
helper is executed with ``exec`` semantics (replaces the bootstrap process). When a
serialized non-secret context envelope is available it is forwarded to the child process.
``--require-envelope`` refuses a silent working-directory fallback.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import build_parser, run_module_main
from repository_context import (
    CONTEXT_ENVELOPE_ENV,
    RepositoryContextError,
    envelope_from_env,
    from_root,
    merge_forwarded_envelope,
)
from sw_scripts_resolve import ScriptsResolveError, resolve_script

SAFE_SCRIPT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.py$")


def normalize_script_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        return name
    if not name.endswith(".py"):
        name = f"{name}.py"
    return name


def validate_script_name(raw: str) -> tuple[str | None, str | None]:
    """Return normalized basename or an error message."""
    name = normalize_script_name(raw)
    if not name:
        return None, "script name required"
    if "/" in raw or "\\" in raw or ".." in raw:
        return None, f"unsafe script name: {raw}"
    if not SAFE_SCRIPT_RE.match(name):
        return None, f"unsafe script name: {raw}"
    return name, None


def resolve_helper(
    workspace: Path,
    script_name: str,
    *,
    env: dict[str, str] | None = None,
) -> Path:
    validated, err = validate_script_name(script_name)
    if err:
        raise ScriptsResolveError(err)
    assert validated is not None
    return resolve_script(workspace, validated, env=env, executor=Path(__file__))


def build_argv_parser() -> argparse.ArgumentParser:
    return build_parser(
        prog="sw_bootstrap.py",
        description="Resolve and run Shipwright helper scripts from the plugin install.",
        epilog=(
            "Examples:\n"
            "  python3 scripts/sw_bootstrap.py --print wave_deliver.py\n"
            "  python3 scripts/sw_bootstrap.py wave_deliver.py -- --help\n"
            "  python3 scripts/sw_bootstrap.py --root /path/to/consumer host.py -- doctor"
        ),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_argv_parser()
    parser.add_argument(
        "--root",
        default=".",
        help="Consumer workspace root (default: cwd when envelope not required)",
    )
    parser.add_argument(
        "--require-envelope",
        action="store_true",
        help="Refuse when no serialized context envelope is present",
    )
    parser.add_argument(
        "--print",
        dest="print_path",
        action="store_true",
        help="Print resolved helper path instead of executing",
    )
    parser.add_argument(
        "script",
        help="Helper script basename (e.g. wave_deliver.py)",
    )
    parser.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the helper after optional -- separator",
    )
    return parser.parse_args(list(sys.argv[1:] if argv is None else argv))


def _strip_forward_separator(args: list[str]) -> list[str]:
    if args and args[0] == "--":
        return args[1:]
    return args


def resolve_workspace(
    args: argparse.Namespace,
    *,
    env: dict[str, str] | None = None,
) -> tuple[Path, dict[str, str]]:
    """Resolve workspace root and child environment with optional envelope forwarding."""
    source = dict(env if env is not None else os.environ)
    context = envelope_from_env(source)
    if args.require_envelope and context is None:
        raise RepositoryContextError(
            f"{CONTEXT_ENVELOPE_ENV} is required; refusing working-directory fallback"
        )
    if context is not None:
        context.assert_root_invariant()
        workspace = Path(context.root).resolve()
        child_env = merge_forwarded_envelope(source, context=context)
        return workspace, child_env
    if args.root == "." and args.require_envelope:
        raise RepositoryContextError(
            f"{CONTEXT_ENVELOPE_ENV} is required; refusing working-directory fallback"
        )
    workspace = Path(args.root).resolve()
    built = from_root(workspace)
    child_env = merge_forwarded_envelope(source, context=built)
    return workspace, child_env


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    script_args = _strip_forward_separator(list(args.script_args))
    try:
        workspace, child_env = resolve_workspace(args)
        target = resolve_helper(workspace, args.script, env=child_env)
    except (ScriptsResolveError, RepositoryContextError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.print_path:
        print(target)
        return 0

    exec_env = os.environ.copy()
    exec_env.update(child_env)
    exec_argv = [sys.executable, str(target), *script_args]
    os.execve(sys.executable, exec_argv, exec_env)
    return 0  # pragma: no cover


if __name__ == "__main__":
    run_module_main(main)
