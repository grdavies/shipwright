#!/usr/bin/env python3
"""CI guard: capability fixture gateRef must not regress to .sh (PRD 050 R17)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from capability_trust import check_gateref_no_shell


def main(argv=None):
    result = check_gateref_no_shell(Path.cwd().resolve())
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "pass" else 20


if __name__ == "__main__":
    run_module_main(main)
