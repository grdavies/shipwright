#!/usr/bin/env python3
"""Planning-unit frontmatter validator (PRD 031 R19)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

KNOWN_KEYS = frozenset({
    "id", "type", "status", "title", "visibility",
    "depends", "blocks", "supersedes", "extends", "absorbs",
    "priority", "tags",
})
REQUIRED_KEYS = frozenset({"id", "type", "status", "title", "visibility"})
ARRAY_KEYS = frozenset({"depends", "blocks", "supersedes", "extends", "absorbs", "tags"})
UNIT_TYPES = frozenset({"brainstorm", "gap", "prd", "decision", "amendment"})


def parse_scalar(raw: str):
    raw = raw.strip()
    if not raw:
        return ""
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in re.split(r",\s*", inner) if item.strip().strip("\"'")]
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def parse_frontmatter(content: str) -> tuple[dict, list[str]]:
    if not content.startswith("---"):
        return {}, ["missing frontmatter block"]
    end = content.find("\n---", 3)
    if end == -1:
        return {}, ["unterminated frontmatter block"]
    fm: dict = {}
    errors: list[str] = []
    for line_no, line in enumerate(content[3:end].splitlines(), start=2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in line:
            if stripped and ":" not in line:
                errors.append(f"line {line_no}: malformed frontmatter line")
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        if key not in KNOWN_KEYS:
            errors.append(f"unknown key: {key}")
            continue
        fm[key] = parse_scalar(val)
    return fm, errors


def validate_structure(fm: dict) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_KEYS - set(fm))
    if missing:
        errors.append(f"missing required keys: {', '.join(missing)}")
    unit_type = fm.get("type")
    if unit_type not in UNIT_TYPES:
        errors.append(f"invalid type: {unit_type!r}")
    for key in ARRAY_KEYS:
        if key not in fm:
            continue
        val = fm[key]
        if not isinstance(val, list):
            errors.append(f"{key} must be an array")
        elif not all(isinstance(item, str) and item for item in val):
            errors.append(f"{key} must be a non-empty string array")
    priority = fm.get("priority")
    if priority is not None and not isinstance(priority, int):
        errors.append("priority must be an integer")
    visibility = fm.get("visibility")
    if visibility not in {"public", "private", "memory"}:
        errors.append(f"invalid visibility: {visibility!r}")
    if unit_type in UNIT_TYPES and isinstance(fm.get("status"), str):
        from planning_status_enum import validate_status
        status_err = validate_status(unit_type, fm["status"])
        if status_err:
            errors.append(status_err)
    return errors


def is_git_tracked(file_path: Path, repo_root: Path) -> bool:
    proc = subprocess.run(["git", "ls-files", "--error-unmatch", str(file_path)], cwd=repo_root, capture_output=True, text=True)
    return proc.returncode == 0


def validate_private_visibility(fm: dict, body_path: Path, repo_root: Path) -> list[str]:
    if fm.get("visibility") not in {"private", "memory"}:
        return []
    try:
        rel = body_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        rel = body_path
    if is_git_tracked(rel, repo_root):
        return [f"visibility {fm.get('visibility')} but body path is git-tracked: {rel}"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planning-unit-validate.py")
    parser.add_argument("--path", required=True)
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)
    plugin_root = SCRIPT_DIR.parent
    repo_root = Path(args.repo_root).resolve() if args.repo_root else plugin_root
    path_file = Path(args.path)
    if not path_file.is_file():
        print(json.dumps({"verdict": "fail", "error": f"not found: {path_file}"}))
        return 2
    fm, parse_errors = parse_frontmatter(path_file.read_text(encoding="utf-8"))
    errors = list(parse_errors) + validate_structure(fm) + validate_private_visibility(fm, path_file, repo_root)
    if errors:
        print(json.dumps({"verdict": "fail", "errors": errors, "path": str(path_file)}))
        return 20
    print(json.dumps({"verdict": "pass", "path": str(path_file), "id": fm.get("id")}))
    return 0


if __name__ == "__main__":
    run_module_main(main)
