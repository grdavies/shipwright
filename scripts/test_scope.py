#!/usr/bin/env python3
"""Map git diffs to pytest collection plans via suite-registry pathTriggers (PRD 054 TR2–TR3)."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from _sw.cli import build_parser, run_module_main

WIDEN_GLOBS: tuple[str, ...] = (
    "core/sw-reference/suite-registry.json",
    "core/sw-reference/suite-registry.schema.json",
    "core/sw-reference/pr-test-plan.manifest.json",
    ".cursor/workflow.config.json",
    "workflow.config.json",
    "scripts/test/_runner.py",
    "scripts/test_scope.py",
    "scripts/suite_registry.py",
    ".github/workflows/pr-test-plan-ci.yml",
    "scripts/generate-pr-test-plan-ci-workflow.py",
)

REGISTRY_REL = Path("core/sw-reference/suite-registry.json")


def repo_root(start: Path | None = None) -> Path:
    start = start or Path(__file__).resolve().parent
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return cur


def normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def path_matches_glob(path: str, pattern: str) -> bool:
    norm = normalize_repo_path(path)
    pat = normalize_repo_path(pattern)
    if fnmatch.fnmatch(norm, pat):
        return True
    if not pat.startswith("**/"):
        return fnmatch.fnmatch(norm, f"**/{pat}")
    return False


def widen_reason(changed_paths: list[str]) -> str | None:
    for path in changed_paths:
        for glob in WIDEN_GLOBS:
            if path_matches_glob(path, glob):
                return "global-infra"
    return None


def load_registry(root: Path) -> dict[str, Any]:
    path = root / REGISTRY_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("suites"), list):
        raise ValueError("invalid suite registry shape")
    return data


def entry_triggers(entry: dict[str, Any]) -> list[str]:
    triggers = entry.get("pathTriggers")
    if isinstance(triggers, list) and triggers:
        return [str(t) for t in triggers]
    script = entry.get("script", "")
    if script.startswith("scripts/test/run_") and script.endswith("_fixtures.py"):
        return [script]
    return []


def entry_matches_paths(entry: dict[str, Any], changed_paths: list[str]) -> bool:
    triggers = entry_triggers(entry)
    if not triggers:
        return False
    for changed in changed_paths:
        for trigger in triggers:
            if path_matches_glob(changed, trigger):
                return True
    return False


def expand_tag_closure(
    registry: dict[str, Any],
    matched_ids: set[str],
    *,
    tag_closure: bool,
) -> set[str]:
    if not tag_closure:
        return set(matched_ids)
    by_id = {row["id"]: row for row in registry.get("suites") or []}
    tags: set[str] = set()
    for sid in matched_ids:
        for tag in by_id.get(sid, {}).get("tags") or []:
            tags.add(str(tag))
    if not tags:
        return set(matched_ids)
    expanded = set(matched_ids)
    for row in registry.get("suites") or []:
        row_tags = {str(t) for t in (row.get("tags") or [])}
        if row_tags & tags:
            expanded.add(row["id"])
    return expanded


def match_suite_ids(
    registry: dict[str, Any],
    changed_paths: list[str],
    *,
    tag_closure: bool = True,
) -> set[str]:
    matched: set[str] = set()
    for row in registry.get("suites") or []:
        if entry_matches_paths(row, changed_paths):
            matched.add(row["id"])
    return expand_tag_closure(registry, matched, tag_closure=tag_closure)


def fallback_pytest_paths(changed_paths: list[str]) -> list[str]:
    paths: list[str] = []
    for raw in changed_paths:
        norm = normalize_repo_path(raw)
        if not norm.startswith("scripts/") or not norm.endswith(".py"):
            continue
        if "/test/" in f"/{norm}/" and not norm.startswith("scripts/unit_tests/"):
            continue
        module_path = norm.replace("/", ".").removesuffix(".py")
        unit_guess = f"scripts/unit_tests/{Path(norm).stem.replace('run_', '').replace('_fixtures', '')}"
        if norm.startswith("scripts/unit_tests/"):
            paths.append(norm)
        else:
            paths.append(norm)
    return sorted(set(paths))


def pytest_targets_for_suites(registry: dict[str, Any], suite_ids: set[str]) -> tuple[list[str], list[str]]:
    markers: list[str] = []
    paths: list[str] = []
    by_id = {row["id"]: row for row in registry.get("suites") or []}
    for sid in sorted(suite_ids):
        row = by_id.get(sid, {})
        marker = row.get("pytestMarker")
        pytest_path = row.get("pytestPath")
        if marker:
            markers.append(str(marker))
        elif pytest_path:
            paths.append(str(pytest_path))
        elif row.get("script", "").startswith("scripts/unit_tests/"):
            paths.append(row["script"])
    return markers, paths


def should_run_full_dist_compare(scope: str, changed_paths: list[str]) -> bool:
    """Full dist/cursor golden compare only in full scope or widen (PRD 055 R29)."""
    if scope.strip().lower() == "full":
        return True
    return widen_reason(changed_paths) is not None


def build_plan(
    changed_paths: list[str],
    *,
    scope: str = "phase",
    tag_closure: bool = True,
    registry: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or repo_root()
    registry = registry or load_registry(root)
    normalized = [normalize_repo_path(p) for p in changed_paths if p.strip()]
    reason = widen_reason(normalized)
    effective_scope = "full" if reason else scope

    if effective_scope == "full":
        return {
            "scope": "full",
            "suites": [],
            "pytest": True,
            "widenReason": reason,
            "pytestArgs": ["scripts/unit_tests"],
            "markers": [],
            "paths": ["scripts/unit_tests"],
            "advisories": [],
        }

    if effective_scope == "fast":
        return {
            "scope": "fast",
            "suites": [],
            "pytest": True,
            "widenReason": None,
            "pytestArgs": ["-m", "not integration", "scripts/unit_tests"],
            "markers": ["not integration"],
            "paths": ["scripts/unit_tests"],
            "advisories": [],
        }

    suite_ids = match_suite_ids(registry, normalized, tag_closure=tag_closure)
    markers, paths = pytest_targets_for_suites(registry, suite_ids)
    advisories: list[str] = []

    if not suite_ids and normalized:
        paths = fallback_pytest_paths(normalized)
        if paths:
            advisories.append("no-registry-match: using touched scripts/**/*.py fallback")

    pytest_args: list[str] = []
    if markers:
        expr = " or ".join(markers)
        pytest_args.extend(["-m", expr])
    if paths:
        pytest_args.extend(paths)
    if not pytest_args:
        pytest_args = ["scripts/unit_tests"]

    return {
        "scope": "phase",
        "suites": sorted(suite_ids),
        "pytest": True,
        "widenReason": reason,
        "pytestArgs": pytest_args,
        "markers": markers,
        "paths": paths,
        "advisories": advisories,
    }


def git_changed_paths(root: Path, base: str | None = None) -> list[str]:
    if base:
        ref = base
    else:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        branch = proc.stdout.strip() or "HEAD"
        merge = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        ref = merge.stdout.strip() if merge.returncode == 0 else "HEAD~1"
    diff = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", ref, "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if diff.returncode != 0:
        diff = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    return [line.strip() for line in diff.stdout.splitlines() if line.strip()]


def resolve_changed_paths(root: Path, explicit: list[str] | None) -> list[str]:
    if explicit:
        return [normalize_repo_path(p) for p in explicit if p.strip()]
    env = __import__("os").environ.get("SW_CHANGED_PATHS", "").strip()
    if env:
        return [normalize_repo_path(p) for p in env.splitlines() if p.strip()]
    return git_changed_paths(root)


def cmd_plan(args: argparse.Namespace) -> int:
    root = Path(args.root or repo_root())
    changed = resolve_changed_paths(root, args.paths)
    plan = build_plan(
        changed,
        scope=args.scope,
        tag_closure=not args.no_tag_closure,
        root=root,
    )
    print(json.dumps(plan, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="test-scope",
        description="Resolve pytest collection scope from changed paths and suite registry (PRD 054).",
    )
    parser.add_argument("--root", default=None, help="Repository root")
    parser.add_argument("--scope", default="phase", choices=["fast", "phase", "full"])
    parser.add_argument("--no-tag-closure", action="store_true")
    parser.add_argument("paths", nargs="*", help="Changed repo-relative paths (default: git diff)")
    args = parser.parse_args(argv)
    return cmd_plan(args)


if __name__ == "__main__":
    run_module_main(main)
