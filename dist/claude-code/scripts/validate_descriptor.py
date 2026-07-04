#!/usr/bin/env python3
"""Validate a platform descriptor against platforms/descriptor.schema.json."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REQUIRED_KEYS = ("platform", "hooks", "skills", "commands", "rules", "subagents", "mcp", "memoryXport")


def allowed_for(schema: dict, field: str) -> list[str]:
    props = schema.get("properties", {}).get(field, {})
    enum = props.get("enum")
    return list(enum) if isinstance(enum, list) else []


def validate(path: Path, schema_path: Path) -> int:
    if not path.is_file():
        print(f"descriptor-validate: file not found: {path}", file=sys.stderr)
        return 2
    if not schema_path.is_file():
        print(f"descriptor-validate: schema not found: {schema_path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"descriptor-validate: invalid JSON: {path}")
        return 1
    if not isinstance(data, dict):
        print(f"descriptor-validate: invalid JSON: {path}")
        return 1
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    for key in REQUIRED_KEYS:
        if key not in data:
            print(f"descriptor-validate: missing required flag: {key}")
            return 1
    extra = [k for k in data if k not in REQUIRED_KEYS]
    if extra:
        print(f"descriptor-validate: unknown keys: {','.join(extra)}")
        return 1
    for key in REQUIRED_KEYS[1:]:
        value = data[key]
        allowed = allowed_for(schema, key)
        if value not in allowed:
            print(f"descriptor-validate: invalid {key} value: {value}")
            return 1
    platform = data.get("platform")
    if not platform or platform == "null":
        print("descriptor-validate: platform must be a non-empty string")
        return 1
    print(f"descriptor-validate: ok platform={platform}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("descriptor-validate: descriptor path required", file=sys.stderr)
        return 2
    desc = Path(args[0]).resolve()
    schema = SCRIPT_DIR.parent / "platforms" / "descriptor.schema.json"
    return validate(desc, schema)


if __name__ == "__main__":
    from _sw.cli import run_module_main
    run_module_main(main)
