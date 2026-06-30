#!/usr/bin/env python3
"""Host verb dispatcher — routes to provider adapter modules (PRD 026/042).

Usage:
  host.py [--root PATH] <verb> [--key value ...]

Emits JSON on stdout; exit 0 on ok/degraded, non-zero on hard failure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _sw import jsonio  # noqa: E402
from _sw.host import bitbucket, github, gitlab, local  # noqa: E402
from host_lib import resolve_provider  # noqa: E402

ADAPTERS = {
    "github": github,
    "gitlab": gitlab,
    "bitbucket": bitbucket,
    "none": local,
    "local": local,
}


def dispatch(root: Path, verb: str, args: list[str]) -> tuple[dict, int]:
    resolved = resolve_provider(root)
    if resolved.get("verdict") != "ok":
        payload = {
            "verdict": "fail",
            "verb": verb,
            "reason": "unknown_provider",
            "detail": resolved,
        }
        return payload, 30

    provider = resolved.get("provider", "none")
    adapter_id = "local" if provider == "none" else provider
    adapter = ADAPTERS.get(adapter_id)
    if adapter is None:
        payload = {
            "verdict": "degraded",
            "verb": verb,
            "provider": provider,
            "reason": "capability-missing",
            "retryable": False,
        }
        return payload, 0
    return adapter.dispatch(root, verb, args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Host verb dispatcher")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("verb", nargs="?")
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    if not args.verb:
        print('{"verdict":"fail","reason":"usage","message":"verb required"}', file=sys.stderr)
        return 2

    root = args.root.resolve()
    verb_args = [item for item in args.rest if item != "--"]
    payload, code = dispatch(root, args.verb, verb_args)
    jsonio.emit(payload, indent=2)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
