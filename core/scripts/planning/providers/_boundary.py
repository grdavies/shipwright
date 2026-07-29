"""Import-boundary scan for provider client modules (PRD 082 phase 13 / R27)."""
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_CLIENT_MODULES = frozenset(
    {
        "planning_github_client",
        "planning_gitlab_client",
        "planning_jira_client",
        "planning_linear_client",
    }
)
ALLOWED_IMPORT_PREFIXES = (
    "scripts/planning/providers/",
    "core/scripts/planning/providers/",
    "dist/cursor/scripts/planning/providers/",
    "dist/claude-code/scripts/planning/providers/",
)
SCAN_REL_PATHS = (
    "scripts/issues_lib.py",
    "scripts/planning/backends/issues.py",
)


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def provider_import_violations(root: Path) -> list[str]:
    """Return human-readable violations when a live client module is imported outside providers/."""
    violations: list[str] = []
    for rel in SCAN_REL_PATHS:
        path = root / rel
        if not path.is_file():
            continue
        rel_posix = _rel(root, path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_posix)
        except SyntaxError as exc:
            violations.append(f"{rel_posix}: syntax-error:{exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_CLIENT_MODULES:
                        violations.append(f"{rel_posix}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_CLIENT_MODULES:
                violations.append(f"{rel_posix}:{node.lineno}: from {node.module} import ...")
    return violations
