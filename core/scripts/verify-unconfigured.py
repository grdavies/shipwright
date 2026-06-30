#!/usr/bin/env python3
"""Placeholder taxonomy for verify.* commands (PRD 018 R3/R28). """
from __future__ import annotations

import sys

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    import json
    import re
    import sys
    from pathlib import Path

    config_path = sys.argv[1]
    as_json = sys.argv[2] == "1"

    VACUOUS = re.compile(
        r"^\s*(?:"
        r"|:\s*"
        r"|true\s*"
        r"|exit\s+0\s*"
        r"|echo\b.*"
        r")\s*$",
        re.I,
    )


    def is_vacuous(cmd: str) -> bool:
        if cmd is None:
            return True
        s = str(cmd).strip()
        if not s:
            return True
        if VACUOUS.match(s):
            return True
        return False


    cfg = {}
    if config_path and Path(config_path).is_file():
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))

    verify = cfg.get("verify") or {}
    allow = bool(verify.get("allowUnconfigured", False))

    unconfigured_keys = []
    for key, cmd in verify.items():
        if key == "allowUnconfigured":
            continue
        if is_vacuous(cmd):
            unconfigured_keys.append(key)

    configured = len(unconfigured_keys) == 0 and len(verify) > 0
    if not verify:
        configured = False
        unconfigured_keys = ["all"]

    finding = {
        "signal": "verify-unconfigured" if not configured else None,
        "configured": configured,
        "unconfiguredKeys": unconfigured_keys,
        "allowUnconfigured": allow,
        "cta": "run /sw-init",
        "blocking": not allow,
    }

    if as_json:
        print(json.dumps(finding, indent=2))
    else:
        if configured:
            print("verify: configured")
        else:
            print(f"verify-unconfigured: {', '.join(unconfigured_keys)} — run /sw-init")

    sys.exit(0 if configured or allow else 1)
    return 0


if __name__ == "__main__":
    run_module_main(main)
