"""Argparse scaffold and CLI conventions for Shipwright Python entrypoints (R18)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable


def build_parser(
    *,
    prog: str | None = None,
    description: str | None = None,
    epilog: str | None = None,
) -> argparse.ArgumentParser:
    """Return an ArgumentParser with Shipwright CLI defaults."""
    return argparse.ArgumentParser(
        prog=prog,
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def main_entry(
    parser: argparse.ArgumentParser,
    handler,
    argv: list[str] | None = None,
) -> int:
    """Parse argv, invoke handler, and return its exit code."""
    args = parser.parse_args(argv)
    return int(handler(args))


def run_module_main(main_fn) -> None:
    """Standard ``if __name__ == '__main__'`` wrapper."""
    try:
        raise SystemExit(main_fn())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130) from None
