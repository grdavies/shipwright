#!/usr/bin/env python3
"""Planning-unit bundle validation — declaration, completeness, asset frontmatter (PRD 342 R30/R32)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths as pp  # noqa: E402

SCHEMA_REL = "core/sw-reference/planning-bundle.schema.json"
SCHEMA_VERSION = "PlanningBundle@v1"
DECLARATION_KEY = "bundle"
DECLARATION_TRUTHY = frozenset({"true", "yes", "1"})

PLANNING_UNIT_TYPES = frozenset(
    {"brainstorm", "gap", "prd", "decision", "amendment"}
)

DISPOSITION_UNDECLARED = "undeclared"
DISPOSITION_COMPLETE = "complete"
DISPOSITION_INCOMPLETE = "incomplete"
DISPOSITION_REJECTED = "rejected"

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def schema_path(root: Path) -> Path:
    return pp.git_root(root) / SCHEMA_REL


def load_bundle_contract(root: Path | None = None) -> dict[str, Any]:
    """Return the normative in-code contract mirroring planning-bundle.schema.json."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "declaration": {
            "frontmatterKey": DECLARATION_KEY,
            "truthyValues": [True, "true", "yes", "1"],
        },
        "requiredRoles": list(pp.BUNDLE_ASSET_ROLES),
        "assets": {
            role: {"role": role, "filename": pp.BUNDLE_ASSET_FILENAMES[role]}
            for role in pp.BUNDLE_ASSET_ROLES
        },
        "assetConstraints": {
            "forbidPlanningUnitFrontmatter": True,
            "forbidIdKey": True,
        },
    }


def parse_frontmatter(text: str) -> dict[str, Any] | None:
    """Parse simple YAML-ish frontmatter; None when absent."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    fm: dict[str, Any] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if not key:
            continue
        raw_val = value.strip()
        if not raw_val:
            fm[key] = ""
            continue
        lowered = raw_val.lower()
        if lowered in {"true", "yes"}:
            fm[key] = True
        elif lowered in {"false", "no"}:
            fm[key] = False
        elif (raw_val.startswith('"') and raw_val.endswith('"')) or (
            raw_val.startswith("'") and raw_val.endswith("'")
        ):
            fm[key] = raw_val[1:-1]
        else:
            fm[key] = raw_val
    return fm


def is_bundle_declared(frontmatter: dict[str, Any] | None) -> bool:
    """True when canonical-body frontmatter declares a bundle (R30)."""
    if not frontmatter:
        return False
    value = frontmatter.get(DECLARATION_KEY)
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() in DECLARATION_TRUTHY:
        return True
    if isinstance(value, (int, float)) and value == 1:
        return True
    return False


def _looks_like_planning_unit_frontmatter(fm: dict[str, Any]) -> bool:
    """True when frontmatter matches planning-unit shape (type enum and/or id)."""
    if "id" in fm:
        return True
    unit_type = fm.get("type")
    if isinstance(unit_type, str) and unit_type.strip().lower() in PLANNING_UNIT_TYPES:
        return True
    return False


def asset_frontmatter_violation(text: str) -> str | None:
    """Return rejection reason when an asset violates R32; else None."""
    fm = parse_frontmatter(text)
    if fm is None:
        return None
    if "id" in fm:
        return "asset-carries-id-key"
    if _looks_like_planning_unit_frontmatter(fm):
        return "asset-carries-planning-unit-frontmatter"
    return None


def canonical_body_path(unit_dir: Path) -> Path | None:
    """First *.md (non-tasks) carrying an id: frontmatter key — matches index selection."""
    if not unit_dir.is_dir():
        return None
    for path in sorted(unit_dir.glob("*.md")):
        if path.name.startswith("tasks-"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = parse_frontmatter(text)
        if fm and fm.get("id"):
            return path
    return None


def _unit_dir_rel(root: Path, unit_dir: Path) -> str:
    worktree = pp.git_root(root)
    resolved = unit_dir if unit_dir.is_absolute() else worktree / unit_dir
    try:
        return str(resolved.resolve().relative_to(worktree.resolve())).replace("\\", "/")
    except ValueError:
        return str(unit_dir).replace("\\", "/")


def validate_unit_bundle(
    root: Path,
    unit_dir: Path | str,
    *,
    body_path: Path | str | None = None,
    body_text: str | None = None,
) -> dict[str, Any]:
    """Validate bundle declaration + completeness + asset frontmatter (R30, R32).

    Dispositions:
    - undeclared: no declaration signal — never incomplete, even if asset files exist
    - complete: declared and all five assets present without R32 violations
    - incomplete: declared but one or more required assets missing
    - rejected: a present named asset carries planning-unit frontmatter or an id: key
    """
    worktree = pp.git_root(root)
    unit_path = Path(unit_dir)
    if not unit_path.is_absolute():
        unit_path = worktree / unit_path
    unit_rel = _unit_dir_rel(worktree, unit_path)
    asset_rels = pp.bundle_asset_paths_rel(unit_rel)

    body: Path | None
    if body_path is not None:
        body = Path(body_path)
        if not body.is_absolute():
            body = worktree / body
    else:
        body = canonical_body_path(unit_path)

    if body_text is not None:
        body_fm = parse_frontmatter(body_text)
    elif body is not None and body.is_file():
        body_fm = parse_frontmatter(body.read_text(encoding="utf-8"))
    else:
        body_fm = None

    declared = is_bundle_declared(body_fm)

    present: list[str] = []
    missing: list[str] = []
    violations: list[dict[str, str]] = []

    for role, rel in asset_rels.items():
        path = worktree / rel
        if not path.is_file():
            missing.append(role)
            continue
        present.append(role)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(
                {"role": role, "path": rel, "reason": f"unreadable:{exc}"}
            )
            continue
        reason = asset_frontmatter_violation(text)
        if reason:
            violations.append({"role": role, "path": rel, "reason": reason})

    if violations:
        return {
            "verdict": "fail",
            "disposition": DISPOSITION_REJECTED,
            "declared": declared,
            "unitDir": unit_rel,
            "bodyPath": str(body.relative_to(worktree)).replace("\\", "/")
            if body is not None and body.exists()
            else None,
            "present": present,
            "missing": missing if declared else [],
            "violations": violations,
            "error": violations[0]["reason"],
            "contract": load_bundle_contract(worktree),
        }

    if not declared:
        return {
            "verdict": "pass",
            "disposition": DISPOSITION_UNDECLARED,
            "declared": False,
            "unitDir": unit_rel,
            "bodyPath": str(body.relative_to(worktree)).replace("\\", "/")
            if body is not None and body.exists()
            else None,
            "present": present,
            "missing": [],
            "incomplete": False,
            "contract": load_bundle_contract(worktree),
        }

    incomplete = bool(missing)
    disposition = DISPOSITION_INCOMPLETE if incomplete else DISPOSITION_COMPLETE
    return {
        "verdict": "pass" if not incomplete else "fail",
        "disposition": disposition,
        "declared": True,
        "unitDir": unit_rel,
        "bodyPath": str(body.relative_to(worktree)).replace("\\", "/")
        if body is not None and body.exists()
        else None,
        "present": present,
        "missing": missing,
        "incomplete": incomplete,
        "contract": load_bundle_contract(worktree),
    }


def validate_asset_text(text: str, *, role: str | None = None) -> dict[str, Any]:
    """Validate a single asset body against R32 constraints."""
    reason = asset_frontmatter_violation(text)
    if reason:
        return {
            "verdict": "fail",
            "disposition": DISPOSITION_REJECTED,
            "role": role,
            "error": reason,
        }
    return {"verdict": "pass", "disposition": "ok", "role": role}


def cmd_contract(root: Path) -> None:
    contract = load_bundle_contract(root)
    path = schema_path(root)
    emit(
        {
            "verdict": "pass",
            "contract": contract,
            "schemaPath": SCHEMA_REL if path.is_file() else None,
        }
    )


def cmd_validate(root: Path, args: list[str]) -> None:
    unit_dir: str | None = None
    body: str | None = None
    i = 0
    while i < len(args):
        if args[i] == "--unit-dir" and i + 1 < len(args):
            unit_dir = args[i + 1]
            i += 2
            continue
        if args[i] == "--body" and i + 1 < len(args):
            body = args[i + 1]
            i += 2
            continue
        i += 1
    if not unit_dir:
        fail("--unit-dir required")
    result = validate_unit_bundle(root, unit_dir, body_path=body)
    exit_code = 0 if result.get("verdict") == "pass" else 20
    emit(result, exit_code)


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        fail("usage: planning_bundle.py <repo-root> <contract|validate> ...")
    root = Path(args[0]).resolve()
    command = args[1] if len(args) > 1 else ""
    rest = args[2:]
    if command == "contract":
        cmd_contract(root)
    elif command == "validate":
        cmd_validate(root, rest)
    else:
        fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
