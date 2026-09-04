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
    """Route ``self check|upgrade`` onto ``scripts/sw_self.py`` (R20)."""
    self_mod = _load_scripts_module("sw_self_console", "sw_self.py")
    return int(self_mod.main(argv))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(
            "usage: shipwright <init|self> ...\n"
            "  init  — machine mirror then repository configure "
            "(shipwright init --integration <tool>)\n"
            "  self  — check / upgrade against the distribution origin "
            "(shipwright self check|upgrade)",
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
