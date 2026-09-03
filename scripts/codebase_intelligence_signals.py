#!/usr/bin/env python3
"""Shared read-only signal collectors for Codebase Intelligence (PRD 280 R3/R12).

Used by ``architecture_radar.py`` and ``domain_vocabulary.py``. Collectors never
mutate git state, worktrees, or source files.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

DEFAULT_GIT_CHURN_DAYS = 30
DEFAULT_ACTIVITY_BIAS_MIN = 3
DEFAULT_ACTIVITY_BIAS_LAST = 30

SIGNAL_KINDS = frozenset(
    {
        "git-churn",
        "review-findings",
        "gap-linkage",
        "reverts",
        "import-fanout",
        "test-fragility",
        "interface-churn",
        "co-change",
        "remediation-patterns",
        "architecture-learnings",
        "activity-bias",
    }
)


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_workflow_config(root: Path) -> dict[str, Any]:
    from shipwright_paths import load_workflow_config as _load_workflow_config

    return _load_workflow_config(root)
def intelligence_config(root: Path) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    intel = planning.get("intelligence") if isinstance(planning.get("intelligence"), dict) else {}
    radar = intel.get("radar") if isinstance(intel.get("radar"), dict) else {}
    windows = radar.get("windows") if isinstance(radar.get("windows"), dict) else {}
    return {
        "gitChurnDays": int(windows.get("gitChurnDays") or DEFAULT_GIT_CHURN_DAYS),
        "activityBiasMinPrCount": int(
            windows.get("activityBiasMinPrCount") or DEFAULT_ACTIVITY_BIAS_MIN
        ),
        "activityBiasLastPrs": int(
            windows.get("activityBiasLastPrs") or DEFAULT_ACTIVITY_BIAS_LAST
        ),
        "postMerge": bool((radar.get("postMerge") is True)),
        "strictMode": bool(
            ((intel.get("vocabulary") or {}) if isinstance(intel.get("vocabulary"), dict) else {}).get(
                "strictMode"
            )
            is True
        ),
    }


def _run_git(root: Path, args: list[str], *, timeout: int = 60) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout or ""


def collect_git_churn(root: Path, *, days: int | None = None) -> dict[str, Any]:
    """Count path touch frequency over the churn window (read-only)."""
    cfg = intelligence_config(root)
    window = int(days if days is not None else cfg["gitChurnDays"])
    since = (utc_now() - timedelta(days=window)).strftime("%Y-%m-%d")
    out = _run_git(
        root,
        ["log", f"--since={since}", "--name-only", "--pretty=format:", "--diff-filter=ACMR"],
    )
    counts: Counter[str] = Counter()
    for line in out.splitlines():
        path = line.strip()
        if path and not path.startswith("."):
            counts[path] += 1
    return {
        "signal": "git-churn",
        "windowDays": window,
        "since": since,
        "byPath": dict(counts.most_common(500)),
        "pathCount": len(counts),
    }


def collect_reverts(root: Path, *, days: int | None = None) -> dict[str, Any]:
    """Paths touched by revert commits in the window."""
    cfg = intelligence_config(root)
    window = int(days if days is not None else cfg["gitChurnDays"])
    since = (utc_now() - timedelta(days=window)).strftime("%Y-%m-%d")
    out = _run_git(
        root,
        [
            "log",
            f"--since={since}",
            "--grep=^[Rr]evert",
            "--extended-regexp",
            "--name-only",
            "--pretty=format:%H%x09%s",
        ],
    )
    by_path: Counter[str] = Counter()
    reverts: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in out.splitlines():
        if "\t" in line and re.match(r"^[0-9a-f]{7,40}\t", line):
            sha, subject = line.split("\t", 1)
            current = {"sha": sha, "subject": subject}
            reverts.append(current)
            continue
        path = line.strip()
        if path and current is not None:
            by_path[path] += 1
    return {
        "signal": "reverts",
        "windowDays": window,
        "revertCount": len(reverts),
        "byPath": dict(by_path.most_common(200)),
        "samples": reverts[:20],
    }


_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
    re.MULTILINE,
)


def collect_import_fanout(root: Path, *, roots: list[str] | None = None) -> dict[str, Any]:
    """Approximate import fan-out for Python modules under scripts/ and core/scripts/."""
    search_roots = roots or ["scripts", "core/scripts"]
    fanout: dict[str, set[str]] = defaultdict(set)
    for rel in search_roots:
        base = root / rel
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            rel_path = str(path.relative_to(root))
            for match in _IMPORT_RE.finditer(text):
                mod = match.group(1) or match.group(2)
                if mod:
                    fanout[rel_path].add(mod.split(".")[0])
    ranked = {
        path: len(mods)
        for path, mods in sorted(fanout.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:300]
    }
    return {
        "signal": "import-fanout",
        "byPath": ranked,
        "moduleCount": len(ranked),
    }


def collect_review_findings(root: Path) -> dict[str, Any]:
    """Aggregate path mentions from local review / learning store artifacts (best-effort)."""
    by_path: Counter[str] = Counter()
    sources: list[str] = []
    candidates = [
        root / ".cursor" / "sw-learning-store",
        root / ".cursor" / "sw-deliver-runs",
    ]
    path_re = re.compile(r"(?:^|[\s`\"'(])((?:scripts|core|docs)/[\w./-]+\.(?:py|md|ts|tsx|json))")
    for base in candidates:
        if not base.exists():
            continue
        for path in base.rglob("*.json"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            hits = path_re.findall(text)
            if hits:
                sources.append(str(path.relative_to(root)))
                by_path.update(hits)
    return {
        "signal": "review-findings",
        "byPath": dict(by_path.most_common(200)),
        "sourceFiles": sources[:50],
        "note": "best-effort scan of local review/learning JSON; empty when no artifacts",
    }


def collect_gap_linkage(root: Path) -> dict[str, Any]:
    """Scan gap / planning materialized docs for path references (read-only)."""
    by_path: Counter[str] = Counter()
    bases = [
        root / ".cursor" / "planning-materialized" / "docs" / "prds" / "gap",
        root / "docs" / "prds" / "gap",
    ]
    path_re = re.compile(r"`((?:scripts|core|docs)/[^`\s]+)`|\*\*File:\*\*\s*`?([^\s`]+)`?")
    scanned = 0
    for base in bases:
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in path_re.finditer(text):
                hit = match.group(1) or match.group(2)
                if hit:
                    by_path[hit.strip()] += 1
    return {
        "signal": "gap-linkage",
        "byPath": dict(by_path.most_common(200)),
        "filesScanned": scanned,
    }


def collect_test_fragility(root: Path, *, days: int | None = None) -> dict[str, Any]:
    """Proxy: churn on test paths as fragility signal."""
    churn = collect_git_churn(root, days=days)
    fragile = {
        path: count
        for path, count in (churn.get("byPath") or {}).items()
        if "/test" in path or path.startswith("scripts/unit_tests/") or path.endswith("_test.py")
    }
    return {
        "signal": "test-fragility",
        "windowDays": churn.get("windowDays"),
        "byPath": dict(sorted(fragile.items(), key=lambda kv: (-kv[1], kv[0]))[:200]),
        "note": "proxy = git churn on test paths; not flake DB",
    }


def collect_activity_bias(root: Path) -> dict[str, Any]:
    """Modules appearing in ≥N of last M merge commits on default branch."""
    cfg = intelligence_config(root)
    n = cfg["activityBiasMinPrCount"]
    m = cfg["activityBiasLastPrs"]
    out = _run_git(root, ["log", f"-n{m}", "--name-only", "--pretty=format:"])
    per_commit: list[set[str]] = []
    current: set[str] = set()
    for line in out.splitlines():
        path = line.strip()
        if not path:
            if current:
                per_commit.append(current)
                current = set()
            continue
        current.add(path)
    if current:
        per_commit.append(current)
    appearances: Counter[str] = Counter()
    for files in per_commit:
        for path in files:
            appearances[path] += 1
    active = {path: count for path, count in appearances.items() if count >= n}
    return {
        "signal": "activity-bias",
        "minPrCount": n,
        "lastPrs": m,
        "byPath": dict(sorted(active.items(), key=lambda kv: (-kv[1], kv[0]))[:300]),
        "activePathCount": len(active),
    }


def collect_all(root: Path) -> dict[str, Any]:
    cfg = intelligence_config(root)
    collectors = [
        collect_git_churn(root),
        collect_reverts(root),
        collect_import_fanout(root),
        collect_review_findings(root),
        collect_gap_linkage(root),
        collect_test_fragility(root),
        collect_activity_bias(root),
    ]
    return {
        "verdict": "pass",
        "action": "collect-all",
        "readOnly": True,
        "config": cfg,
        "collectedAt": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signals": collectors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Shared Codebase Intelligence signal collectors (PRD 280 R12)"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="Show resolved planning.intelligence windows")
    sub.add_parser("collect-all", help="Run all read-only collectors")
    for name in (
        "git-churn",
        "reverts",
        "import-fanout",
        "review-findings",
        "gap-linkage",
        "test-fragility",
        "activity-bias",
    ):
        sub.add_parser(name, help=f"Collect {name} signal only")

    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.command == "config":
        emit({"verdict": "pass", "action": "config", "config": intelligence_config(root)})
    if args.command == "collect-all":
        emit(collect_all(root))

    mapping = {
        "git-churn": collect_git_churn,
        "reverts": collect_reverts,
        "import-fanout": collect_import_fanout,
        "review-findings": collect_review_findings,
        "gap-linkage": collect_gap_linkage,
        "test-fragility": collect_test_fragility,
        "activity-bias": collect_activity_bias,
    }
    fn = mapping.get(args.command)
    if not fn:
        fail(f"unknown command: {args.command}")
    result = fn(root)
    emit({"verdict": "pass", "action": args.command, "readOnly": True, **result})
    return 0


if __name__ == "__main__":
    run_module_main(main)
