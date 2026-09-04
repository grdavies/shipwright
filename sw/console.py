"""Packaged console entry for ``shipwright`` (PRD 342 R17).

Resolves ``init`` and ``self`` onto the existing install / configure / upgrade
spine — no parallel installation path.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path


def _scripts_dir() -> Path:
    """Locate ``scripts/`` whether running from a source checkout or an install."""
    here = Path(__file__).resolve()
    candidate = here.parent.parent / "scripts"
    if candidate.is_dir():
        return candidate
    sibling = here.parent / "scripts"
    if sibling.is_dir():
        return sibling
    return candidate


def _load_scripts_module(name: str, filename: str):
    scripts = _scripts_dir()
    path = scripts / filename
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _dispatch_init(argv: list[str]) -> int:
    install = _load_scripts_module("sw_install_console", "install.py")
    return int(install.main_init(argv))


def _dispatch_self(argv: list[str]) -> int:
    """Route ``self`` onto the existing upgrade-gate spine (R17).

    Phase 6 replaces this with ``scripts/sw_self.py`` for check/upgrade verbs;
    until then the console resolves ``self`` to the in-flight deliver upgrade gate.
    """
    if argv and argv[0] in ("-h", "--help"):
        print(
            "usage: shipwright self [check|upgrade] ...\n"
            "  Phase 5 routes onto scripts/upgrade-gate.py; "
            "full check/upgrade land in phase 6.",
            file=sys.stderr,
        )
        return 0
    rest = list(argv)
    if rest and rest[0] in ("check", "upgrade", "gate"):
        rest = rest[1:]
    gate = _load_scripts_module("sw_upgrade_gate_console", "upgrade-gate.py")
    return int(gate.main(rest))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(
            "usage: shipwright <init|self> ...\n"
            "  init  — machine mirror then repository configure "
            "(shipwright init --integration <tool>)\n"
            "  self  — resolve onto the existing upgrade spine",
            file=sys.stderr,
        )
        return 0
    verb, rest = args[0], args[1:]
    dispatch: dict[str, Callable[[list[str]], int]] = {
        "init": _dispatch_init,
        "self": _dispatch_self,
    }
    handler = dispatch.get(verb)
    if handler is None:
        print(f"unknown verb: {verb}", file=sys.stderr)
        print("usage: shipwright <init|self> ...", file=sys.stderr)
        return 2
    return handler(rest)


if __name__ == "__main__":
    raise SystemExit(main())
