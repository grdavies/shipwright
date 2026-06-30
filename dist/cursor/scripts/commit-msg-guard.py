#!/usr/bin/env python3
"""Conventional Commit message validator (PRD 026 R25)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

FALLBACK_TYPES = "feat fix perf revert docs chore refactor test"


def load_types(root: Path) -> str:
    cfg = root / "release-please-config.json"
    if not cfg.is_file():
        return FALLBACK_TYPES
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        types: list[str] = []
        for pkg in data.get("packages", {}).values():
            for sec in pkg.get("changelog-sections", []):
                t = sec.get("type")
                if t and t not in types:
                    types.append(t)
        return " ".join(types) if types else FALLBACK_TYPES
    except (json.JSONDecodeError, OSError):
        return FALLBACK_TYPES


def types_alternation(root: Path) -> str:
    return load_types(root).replace(" ", "|")


def validate_message(root: Path, msg: str) -> tuple[int, dict]:
    if Path(msg).is_file():
        lines = [
            line
            for line in Path(msg).read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        msg = lines[0] if lines else ""
    subject = msg.splitlines()[0] if msg else ""
    if not subject.strip():
        return 3, {"verdict": "fail", "reason": "empty-subject"}
    alt = types_alternation(root)
    if re.match(rf"^({alt})(\([a-z0-9._/-]+\))?!?: .+", subject):
        return 0, {"verdict": "pass", "subject": subject}
    return 3, {
        "verdict": "fail",
        "subject": subject,
        "allowedTypes": load_types(root),
        "remediation": "use <type>(<scope>): <description> e.g. feat: add branch guard",
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = SCRIPT_DIR.parent
    if not args:
        print("usage: commit-msg-guard {types | validate <message-or-file>}", file=sys.stderr)
        return 2
    cmd = args[0]
    if cmd == "types":
        print(load_types(root))
        return 0
    if cmd == "validate":
        if len(args) < 2:
            print("usage: commit-msg-guard validate <message-or-file>", file=sys.stderr)
            return 2
        code, payload = validate_message(root, args[1])
        stream = sys.stdout if code == 0 else sys.stderr
        stream.write(json.dumps(payload) + "\n")
        return code
    print("usage: commit-msg-guard {types | validate <message-or-file>}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    run_module_main(main)
