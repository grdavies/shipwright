#!/usr/bin/env python3
"""Detect Cursor vs Claude Code platform via unified host resolver (PRD 352 R11)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from _sw.cli import run_module_main

_HERE = Path(__file__).resolve().parent
if (_HERE.parent / "core" / "adapters" / "host_resolver.py").is_file():
    _REPO_ROOT = _HERE.parent
else:
    _REPO_ROOT = _HERE.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.adapters.host_resolver import (  # noqa: E402
    DestinationValidationError,
    requalify,
)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print("usage: detect-platform [--json]")
        return 0
    if args and args[0] not in ("--json",):
        print(json.dumps({"verdict": "fail", "error": "unknown argument"}), file=sys.stderr)
        return 2
    required = [
        item.strip()
        for item in str(os.environ.get("SW_HOST_REQUIRED_CAPABILITIES") or "").split(",")
        if item.strip()
    ]
    try:
        qualified = requalify(
            required_capabilities=required or None,
            repo_root=_REPO_ROOT,
        )
    except DestinationValidationError as exc:
        print(json.dumps(exc.as_dict()), file=sys.stderr)
        return 2
    if "--json" in args:
        print(
            json.dumps(
                {
                    "platform": qualified.host_id,
                    "host_id": qualified.host_id,
                    "surface_adapter": qualified.surface_adapter,
                    "installed_version": qualified.installed_version,
                    "auth_status": qualified.auth_status,
                }
            )
        )
    else:
        print(qualified.host_id)
    return 0


if __name__ == "__main__":
    run_module_main(main)
