#!/usr/bin/env python3
"""Publish-surface audit for deliver finalize (PRD 069 R6; PRD 325 R6–R7)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from memory_sot import (
    DECISION_STUB_ALLOWLIST,
    is_decision_body_path,
    load_config,
    resolve_decision_home,
)
from wave_json_io import write_json

AUDIT_REL = Path(".cursor/sw-deliver-runs/publish-surface-audit.json")
SEVERITIES_EXPECTED = ("critical", "warning")

PUBLISH_SURFACE_PROFILE_IN_REPO_PUBLIC = "in-repo-public"
PUBLISH_SURFACE_PROFILE_PRIVATE = "private"
PUBLISH_SURFACE_PROFILES = frozenset(
    {PUBLISH_SURFACE_PROFILE_IN_REPO_PUBLIC, PUBLISH_SURFACE_PROFILE_PRIVATE}
)
DEFAULT_PUBLISH_SURFACE_PROFILE = PUBLISH_SURFACE_PROFILE_PRIVATE

DECISION_INDEX_ALLOW = DECISION_STUB_ALLOWLIST

GITIGNORE_PRIVATE_SNIPPETS = (
    "docs/prds/",
    ".cursor/planning-materialized/",
    ".cursor/sw-deliver-runs/",
    "docs/learnings/",
)
GITIGNORE_IN_REPO_PUBLIC_SNIPPETS = (
    ".cursor/planning-materialized/",
    ".cursor/sw-deliver-runs/",
    "docs/learnings/",
)
# Backward-compatible alias for callers/tests that referenced the private set.
GITIGNORE_REQUIRED_SNIPPETS = GITIGNORE_PRIVATE_SNIPPETS


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def audit_path_for(root: Path) -> Path:
    return root / AUDIT_REL


def gitignore_required_snippets(profile: str) -> tuple[str, ...]:
    if profile == PUBLISH_SURFACE_PROFILE_IN_REPO_PUBLIC:
        return GITIGNORE_IN_REPO_PUBLIC_SNIPPETS
    return GITIGNORE_PRIVATE_SNIPPETS


def resolve_publish_surface_profile(
    root: Path, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Resolve publish-surface audit profile from workflow config + decision home."""
    if config is None:
        config = load_config(root)

    planning = config.get("planning") if isinstance(config, dict) else {}
    if isinstance(planning, dict):
        publish_surface = planning.get("publishSurface")
        if isinstance(publish_surface, dict):
            explicit = publish_surface.get("profile")
            if isinstance(explicit, str) and explicit.strip():
                requested = explicit.strip()
                if requested in PUBLISH_SURFACE_PROFILES:
                    return {"profile": requested, "source": "config"}
                return {
                    "profile": DEFAULT_PUBLISH_SURFACE_PROFILE,
                    "source": "config-unknown",
                    "requested": requested,
                }

    home = resolve_decision_home(root, config)
    from planning_store import resolve_effective_backend

    backend = str(resolve_effective_backend(root, config).get("effective") or "")
    decision_home = str(home.get("home") or "")

    if decision_home == "planning-store" or backend == "issue-store":
        return {
            "profile": PUBLISH_SURFACE_PROFILE_PRIVATE,
            "source": "derived-issue-store",
            "decisionHome": decision_home,
            "backend": backend,
        }

    if backend == PUBLISH_SURFACE_PROFILE_IN_REPO_PUBLIC and decision_home == "repo":
        return {
            "profile": PUBLISH_SURFACE_PROFILE_IN_REPO_PUBLIC,
            "source": "derived-in-repo-public",
            "decisionHome": decision_home,
            "backend": backend,
        }

    return {
        "profile": DEFAULT_PUBLISH_SURFACE_PROFILE,
        "source": "default",
        "decisionHome": decision_home,
        "backend": backend,
    }


def git_tracked_paths(root: Path) -> tuple[list[str] | None, str | None]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "git ls-files failed").strip()
        return None, err
    return [
        line.strip().replace("\\", "/")
        for line in proc.stdout.splitlines()
        if line.strip()
    ], None


def leaked_publish_paths(tracked: list[str]) -> list[str]:
    leaks: list[str] = []
    for path in tracked:
        if path.startswith("docs/learnings/"):
            leaks.append(path)
        elif is_decision_body_path(path):
            leaks.append(path)
        elif path == ".cursor/sw-base-state.json":
            leaks.append(path)
        elif path.startswith(".cursor/tmp-") and path.endswith(".sh"):
            leaks.append(path)
        elif path.startswith(".cursor/hooks/state/") or "/.cursor/hooks/state/" in path:
            leaks.append(path)
        elif path == ".cursor/planning-materialized" or path.startswith(
            ".cursor/planning-materialized/"
        ):
            leaks.append(path)
    return sorted(leaks)


def docs_prds_tracked(tracked: list[str]) -> list[str]:
    return sorted(p for p in tracked if p == "docs/prds" or p.startswith("docs/prds/"))


def decision_body_leaks(tracked: list[str]) -> list[str]:
    return sorted(p for p in tracked if is_decision_body_path(p))


def _check_decision_home_migration(root: Path, tracked: list[str] | None, discovery_error: str | None) -> dict[str, Any]:
    del tracked, discovery_error
    home = resolve_decision_home(root)
    planning_store = home.get("home") == "planning-store"
    detail: dict[str, Any] = {"decisionHome": home}
    if not planning_store:
        return {
            "id": "decision-home-migration",
            "severity": "warning",
            "status": "skipped",
            "considered": False,
            "detail": detail,
        }
    return {
        "id": "decision-home-migration",
        "severity": "warning",
        "status": "passed",
        "considered": True,
        "detail": detail,
    }


def _check_denylist_leaked(root: Path, tracked: list[str] | None, discovery_error: str | None) -> dict[str, Any]:
    del root
    if tracked is None:
        return {
            "id": "denylist-leaked-paths",
            "severity": "critical",
            "status": "failed",
            "considered": False,
            "detail": discovery_error or "git ls-files unavailable",
        }
    leaks = leaked_publish_paths(tracked)
    return {
        "id": "denylist-leaked-paths",
        "severity": "critical",
        "status": "failed" if leaks else "passed",
        "considered": True,
        "detail": {"leaks": leaks} if leaks else None,
    }


def _check_docs_prds_absent(
    root: Path,
    tracked: list[str] | None,
    discovery_error: str | None,
    *,
    profile: str,
) -> dict[str, Any]:
    del root
    if profile == PUBLISH_SURFACE_PROFILE_IN_REPO_PUBLIC:
        return {
            "id": "docs-prds-absent",
            "severity": "critical",
            "status": "skipped",
            "considered": False,
            "detail": {"profile": PUBLISH_SURFACE_PROFILE_IN_REPO_PUBLIC},
        }
    if tracked is None:
        return {
            "id": "docs-prds-absent",
            "severity": "critical",
            "status": "failed",
            "considered": False,
            "detail": discovery_error or "git ls-files unavailable",
        }
    tracked_prds = docs_prds_tracked(tracked)
    return {
        "id": "docs-prds-absent",
        "severity": "critical",
        "status": "failed" if tracked_prds else "passed",
        "considered": True,
        "detail": {"tracked": tracked_prds} if tracked_prds else None,
    }


def _check_gitignore_hygiene(
    root: Path,
    tracked: list[str] | None,
    discovery_error: str | None,
    *,
    profile: str,
) -> dict[str, Any]:
    del tracked, discovery_error
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return {
            "id": "gitignore-publish-hygiene",
            "severity": "warning",
            "status": "failed",
            "considered": True,
            "detail": "missing .gitignore",
        }
    text = gitignore.read_text(encoding="utf-8", errors="replace")
    required = gitignore_required_snippets(profile)
    missing = [snippet for snippet in required if snippet not in text]
    detail: dict[str, Any] | str | None
    if missing:
        detail = {"missingSnippets": missing, "profile": profile}
    else:
        detail = {"profile": profile}
    return {
        "id": "gitignore-publish-hygiene",
        "severity": "warning",
        "status": "failed" if missing else "passed",
        "considered": True,
        "detail": detail,
    }


CheckFn = Callable[[Path, list[str] | None, str | None], dict[str, Any]]


def checks_for_profile(profile: str) -> tuple[CheckFn, ...]:
    resolved = (
        profile
        if profile in PUBLISH_SURFACE_PROFILES
        else DEFAULT_PUBLISH_SURFACE_PROFILE
    )

    def docs_prds_check(
        root: Path, tracked: list[str] | None, discovery_error: str | None
    ) -> dict[str, Any]:
        return _check_docs_prds_absent(
            root, tracked, discovery_error, profile=resolved
        )

    def gitignore_check(
        root: Path, tracked: list[str] | None, discovery_error: str | None
    ) -> dict[str, Any]:
        return _check_gitignore_hygiene(
            root, tracked, discovery_error, profile=resolved
        )

    return (
        _check_denylist_leaked,
        docs_prds_check,
        _check_decision_home_migration,
        gitignore_check,
    )


CHECKS = checks_for_profile(DEFAULT_PUBLISH_SURFACE_PROFILE)


def run_publish_surface_audit(
    root: Path,
    *,
    tracked_override: list[str] | None = None,
    profile_override: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate publish-surface checklist; does not write JSON."""
    profile_meta = (
        {"profile": profile_override, "source": "override"}
        if profile_override in PUBLISH_SURFACE_PROFILES
        else resolve_publish_surface_profile(root, config)
    )
    profile = str(profile_meta["profile"])
    checks = checks_for_profile(profile)

    discovery_error: str | None = None
    tracked: list[str] | None
    if tracked_override is not None:
        tracked = tracked_override
    else:
        tracked, discovery_error = git_tracked_paths(root)

    items = [check(root, tracked, discovery_error) for check in checks]
    passed = [item["id"] for item in items if item.get("status") == "passed"]
    failed = [
        item["id"]
        for item in items
        if item.get("status") == "failed" and item.get("considered") is True
    ]
    skipped = [item["id"] for item in items if item.get("status") == "skipped"]

    severities_considered = sorted(
        {
            str(item["severity"])
            for item in items
            if item.get("considered") is True
        }
    )
    all_severities_considered = list(severities_considered) == list(SEVERITIES_EXPECTED)
    blocking_failed = bool(failed) or not all_severities_considered

    verdict = "not-ready" if blocking_failed else "ready"
    resume = None
    if verdict == "not-ready":
        resume = "python3 scripts/publish_surface_audit.py --root . --write"

    return {
        "verdict": verdict,
        "action": "publish-surface-audit",
        "profile": profile,
        "profileResolution": profile_meta,
        "considered": items,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "severitiesExpected": list(SEVERITIES_EXPECTED),
        "severitiesConsidered": severities_considered,
        "allSeveritiesConsidered": all_severities_considered,
        "resumeCommand": resume,
        "auditedAt": utc_now(),
    }


def emit_publish_surface_audit(root: Path, *, write: bool = True) -> dict[str, Any]:
    """Run audit and optionally persist JSON under .cursor/sw-deliver-runs/."""
    result = run_publish_surface_audit(root)
    result["path"] = str(AUDIT_REL)
    if write:
        path = audit_path_for(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, result)
    return result


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish-surface audit (PRD 069 R6)")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--write", action="store_true", help="Persist audit JSON")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    result = emit_publish_surface_audit(root, write=args.write)
    emit(result, exit_code=0 if result.get("verdict") == "ready" else 20)


if __name__ == "__main__":
    main()
