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
    "scripts/test/_runner.py",
    "scripts/test_scope.py",
    "scripts/suite_registry.py",
    ".github/workflows/pr-test-plan-ci.yml",
    ".github/workflows/ci.yml",
    "scripts/ci_plan_gen.py",
    "scripts/generate-pr-test-plan-ci-workflow.py",
)

REGISTRY_REL = Path("core/sw-reference/suite-registry.json")
CORE_DOMAIN_IDS: tuple[str, ...] = ("planning", "memory", "credential")
EVAL_DOMAIN_ID = "eval"
CHANGED_DOMAIN_PLAN_ID = "changed-domain"


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


def registry_plans(registry: dict[str, Any]) -> dict[str, Any]:
    plans = registry.get("plans")
    return plans if isinstance(plans, dict) else {}


def registry_domains(registry: dict[str, Any]) -> dict[str, Any]:
    domains = registry.get("domains")
    return domains if isinstance(domains, dict) else {}


def domain_path_triggers(domain: dict[str, Any]) -> list[str]:
    triggers = domain.get("pathTriggers")
    return [str(t) for t in triggers] if isinstance(triggers, list) else []


def domain_suite_ids(domain: dict[str, Any], *, core_only: bool = False) -> list[str]:
    key = "coreSuiteIds" if core_only else "suiteIds"
    values = domain.get(key)
    if isinstance(values, list) and values:
        return [str(v) for v in values]
    if core_only:
        return []
    suite_id = domain.get("suiteId")
    return [str(suite_id)] if suite_id else []


def changed_paths_match_domain(domain: dict[str, Any], changed_paths: list[str]) -> bool:
    triggers = domain_path_triggers(domain)
    if not triggers:
        return False
    for changed in changed_paths:
        for trigger in triggers:
            if path_matches_glob(changed, trigger):
                return True
    return False


def matched_domains(registry: dict[str, Any], changed_paths: list[str]) -> set[str]:
    matched: set[str] = set()
    for domain_id, domain in registry_domains(registry).items():
        if not isinstance(domain, dict):
            continue
        if changed_paths_match_domain(domain, changed_paths):
            matched.add(str(domain_id))
    return matched


def compute_changed_domain_plan(
    changed_paths: list[str],
    *,
    registry: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Select suites for the pull-request changed-domain plan (PRD 082 R35)."""
    root = root or repo_root()
    registry = registry or load_registry(root)
    normalized = [normalize_repo_path(p) for p in changed_paths if p.strip()]
    plans = registry_plans(registry)
    plan_meta = plans.get(CHANGED_DOMAIN_PLAN_ID)
    if not isinstance(plan_meta, dict):
        raise ValueError(f"missing named plan: {CHANGED_DOMAIN_PLAN_ID}")

    always_include = plan_meta.get("alwaysIncludeDomains")
    if not isinstance(always_include, list) or not always_include:
        always_include = list(CORE_DOMAIN_IDS)

    domains = registry_domains(registry)
    selected_domains: set[str] = set(matched_domains(registry, normalized))
    selected_domains.update(str(domain_id) for domain_id in always_include)

    suite_ids: set[str] = set()
    for domain_id in always_include:
        domain = domains.get(str(domain_id))
        if isinstance(domain, dict):
            suite_ids.update(domain_suite_ids(domain, core_only=True))

    for domain_id in selected_domains:
        if domain_id == EVAL_DOMAIN_ID:
            continue
        domain = domains.get(domain_id)
        if isinstance(domain, dict) and domain_id in matched_domains(registry, normalized):
            suite_ids.update(domain_suite_ids(domain))

    suite_ids.update(match_suite_ids(registry, normalized))
    eval_included = False
    eval_domain = domains.get(EVAL_DOMAIN_ID)
    if isinstance(eval_domain, dict) and changed_paths_match_domain(eval_domain, normalized):
        eval_included = True
        suite_ids.update(domain_suite_ids(eval_domain))

    return {
        "plan": CHANGED_DOMAIN_PLAN_ID,
        "changedPaths": normalized,
        "domains": sorted(selected_domains),
        "matchedDomains": sorted(matched_domains(registry, normalized)),
        "alwaysIncludeDomains": [str(d) for d in always_include],
        "evalIncluded": eval_included,
        "suites": sorted(suite_ids),
    }


def resolve_named_plan(
    plan_id: str,
    changed_paths: list[str] | None = None,
    *,
    registry: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or repo_root()
    registry = registry or load_registry(root)
    normalized = [normalize_repo_path(p) for p in (changed_paths or []) if p.strip()]
    plans = registry_plans(registry)
    plan = plans.get(plan_id)
    if not isinstance(plan, dict):
        raise ValueError(f"unknown named plan: {plan_id}")

    inherits = plan.get("inherits")
    if inherits:
        base = resolve_named_plan(str(inherits), normalized, registry=registry, root=root)
        return {
            "plan": plan_id,
            "inherits": str(inherits),
            "suites": list(base.get("suites") or []),
            "scope": plan.get("scope"),
            "includeIntegration": bool(plan.get("includeIntegration")),
        }

    selection = plan.get("selection")
    if selection == "changed-domains" or plan_id == CHANGED_DOMAIN_PLAN_ID:
        return compute_changed_domain_plan(normalized, registry=registry, root=root)

    scope = str(plan.get("scope") or "phase")
    if scope == "full":
        payload = build_plan(normalized, scope="full", registry=registry, root=root)
        out: dict[str, Any] = {
            "plan": plan_id,
            "scope": "full",
            "suites": payload.get("suites") or [],
            "pytestArgs": payload.get("pytestArgs") or [],
            "includeIntegration": bool(plan.get("includeIntegration")),
        }
        if plan.get("includeIntegration"):
            out["pytestArgs"] = ["scripts/unit_tests"]
        return out

    suite_ids = plan.get("suiteIds")
    if not isinstance(suite_ids, list):
        suite_ids = []
    return {
        "plan": plan_id,
        "scope": scope,
        "suites": sorted({str(sid) for sid in suite_ids}),
        "includeIntegration": bool(plan.get("includeIntegration")),
    }


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
        if norm.startswith("core/scripts/test/") and norm.endswith(".py"):
            paths.append(norm)
            continue
        if norm.startswith("core/scripts/_sw/host/") or norm.startswith(
            "scripts/_sw/host/"
        ):
            paths.append("core/scripts/test")
            continue
        if not norm.startswith("scripts/") or not norm.endswith(".py"):
            continue
        if "/test/" in f"/{norm}/" and not norm.startswith("scripts/unit_tests/"):
            continue
        module_path = norm.replace("/", ".").removesuffix(".py")
        unit_guess = f"scripts/unit_tests/{Path(norm).stem.replace('run_', '').replace('_fixtures', '')}"
        if norm.startswith("scripts/unit_tests/"):
            paths.append(norm)
            continue
        name = Path(norm).name
        if name.startswith("test_") or name.endswith("_test.py"):
            paths.append(norm)
            continue
        # Never collect implementation modules as pytest targets (import mismatch
        # with core/scripts mirrors). Prefer paired core test module when present.
        stem = Path(norm).stem
        paired = f"core/scripts/test/test_{stem}.py"
        # Skip phantom pairs (e.g. `_common.py` → `test__common.py`).
        if Path(paired).is_file() or (Path.cwd() / paired).is_file():
            paths.append(paired)
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
