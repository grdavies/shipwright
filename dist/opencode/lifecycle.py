"""OpenCode lifecycle handler — processes stdin when registered events fire (PRD 352 R5)."""

from __future__ import annotations

import sys

from hook_adapter import before_task_dispatch_stdio


def main(argv: list[str] | None = None) -> int:
    _ = argv
    return before_task_dispatch_stdio()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
