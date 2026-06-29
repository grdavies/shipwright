#!/usr/bin/env bash
# Planning-unit frontmatter validator (PRD 031 R19).
# Usage: planning-unit-validate.sh --path UNIT_BODY_FILE [--repo-root ROOT]
# Exit: 0 pass, 20 fail, 2 error
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATH_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path) PATH_FILE="${2:-}"; shift 2 ;;
    --repo-root) ROOT="${2:-}"; shift 2 ;;
    -h|--help)
      echo "usage: planning-unit-validate.sh --path UNIT_BODY_FILE [--repo-root ROOT]"
      exit 0
      ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

if [[ -z "$PATH_FILE" ]]; then
  echo '{"verdict":"fail","error":"--path required"}' >&2
  exit 2
fi

if [[ ! -f "$PATH_FILE" ]]; then
  echo "{\"verdict\":\"fail\",\"error\":\"not found: $PATH_FILE\"}" >&2
  exit 2
fi

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 - "$PLUGIN_ROOT" "$ROOT" "$PATH_FILE" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

plugin_root = Path(sys.argv[1])
repo_root = Path(sys.argv[2])
path_file = Path(sys.argv[3])
schema_path = plugin_root / "core/sw-reference/planning-unit.schema.json"

sys.path.insert(0, str(plugin_root / "core" / "scripts"))
sys.path.insert(0, str(plugin_root / "scripts"))
from planning_status_enum import validate_status  # noqa: E402

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
        parts = []
        for item in re.split(r",\s*", inner):
            item = item.strip().strip("'\"")
            if item:
                parts.append(item)
        return parts
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
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
    block = content[3:end]
    fm: dict = {}
    errors: list[str] = []
    for line_no, line in enumerate(block.splitlines(), start=2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line:
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
        status_err = validate_status(unit_type, fm["status"])
        if status_err:
            errors.append(status_err)
    return errors


def is_git_tracked(file_path: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(file_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0
    except OSError:
        return False


def validate_private_visibility(fm: dict, body_path: Path) -> list[str]:
    if fm.get("visibility") != "private":
        return []
    try:
        rel = body_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        rel = body_path
    if is_git_tracked(rel):
        return [f"visibility private but body path is git-tracked: {rel}"]
    return []


def main() -> int:
    text = path_file.read_text(encoding="utf-8")
    fm, parse_errors = parse_frontmatter(text)
    errors = list(parse_errors)
    errors.extend(validate_structure(fm))
    errors.extend(validate_private_visibility(fm, path_file))

    if errors:
        print(json.dumps({"verdict": "fail", "errors": errors, "path": str(path_file)}))
        return 20

    print(json.dumps({"verdict": "pass", "path": str(path_file), "id": fm.get("id")}))
    return 0


sys.exit(main())
PY