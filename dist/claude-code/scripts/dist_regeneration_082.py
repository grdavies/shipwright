#!/usr/bin/env python3
"""PRD 082 R27 — distribution freshness checks for registered build-chain modules."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

DIST_TARGETS = ("dist/cursor", "dist/claude-code")

PRD_082_SOURCE_MODULES: dict[str, tuple[str, ...]] = {
    "planningPackage": ("scripts/planning/",),
    "ledger": (
        "scripts/planning_refusal_ledger.py",
        "scripts/planning_refusal_ledger_cli.py",
        "scripts/planning_audit_journal.py",
        "scripts/planning_audit_journal_cli.py",
        "scripts/planning_ledger_store.py",
    ),
    "redaction": (
        "scripts/memory_redact.py",
        "scripts/memory_redact_patterns.py",
        "scripts/memory_redact_allowlist.py",
        "scripts/memory_redaction_provenance.py",
        "scripts/redaction-guard.py",
    ),
    "evalHarness": ("scripts/test/memory-eval/",),
    "doctor": (
        "scripts/planning-doctor.py",
        "scripts/planning_doctor_ledger.py",
        "scripts/memory_doctor_checks.py",
    ),
}


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(root: Path, rel: str) -> str:
    base = root / rel
    if not base.exists():
        return ""
    if base.is_file():
        return _file_digest(base)
    h = hashlib.sha256()
    for item in sorted(base.rglob("*")):
        if item.is_file():
            h.update(item.relative_to(base).as_posix().encode())
            h.update(item.read_bytes())
    return h.hexdigest()


def load_source_modules(manifest_path: Path) -> dict[str, list[str]]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw = data.get("sourceModules") or {}
    return {key: list(value) for key, value in raw.items()}


def check_source_modules_registered(manifest_path: Path) -> list[dict[str, str]]:
    if not manifest_path.is_file():
        return [{"kind": "manifest-missing", "path": str(manifest_path)}]
    registered = load_source_modules(manifest_path)
    drift: list[dict[str, str]] = []
    for group, expected in PRD_082_SOURCE_MODULES.items():
        actual = registered.get(group)
        if actual is None:
            drift.append({"kind": "module-group-missing", "group": group})
            continue
        if tuple(actual) != expected:
            drift.append(
                {
                    "kind": "module-group-mismatch",
                    "group": group,
                    "expected": json.dumps(expected),
                    "actual": json.dumps(actual),
                }
            )
    return drift


def _expects_dist_mirror(rel: str) -> bool:
    return not rel.startswith("scripts/test/")


def find_stale_distribution_mirrors(root: Path, *, modules: dict[str, list[str]] | None = None) -> list[dict[str, str]]:
    modules = modules or {k: list(v) for k, v in PRD_082_SOURCE_MODULES.items()}
    stale: list[dict[str, str]] = []
    for group, paths in modules.items():
        for rel in paths:
            source = root / rel
            if not source.exists():
                stale.append({"kind": "source-missing", "group": group, "path": rel})
                continue
            if not _expects_dist_mirror(rel):
                continue
            source_digest = _tree_digest(root, rel)
            for target in DIST_TARGETS:
                mirror = root / target / rel
                if not mirror.exists():
                    stale.append(
                        {
                            "kind": "mirror-missing",
                            "group": group,
                            "path": rel,
                            "target": target,
                        }
                    )
                    continue
                mirror_digest = _tree_digest(root, f"{target}/{rel}")
                if source_digest != mirror_digest:
                    stale.append(
                        {
                            "kind": "mirror-stale",
                            "group": group,
                            "path": rel,
                            "target": target,
                        }
                    )
    return stale


def check_distribution_freshness(root: Path, manifest_path: Path | None = None) -> list[dict[str, str]]:
    manifest = manifest_path or root / "core/sw-reference/build-chain-paths.json"
    drift = check_source_modules_registered(manifest)
    if drift:
        return drift
    registered = load_source_modules(manifest)
    return find_stale_distribution_mirrors(root, modules=registered)
