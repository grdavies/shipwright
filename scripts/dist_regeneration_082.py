#!/usr/bin/env python3
"""PRD 082 R27 — distribution freshness checks for registered build-chain modules."""
from __future__ import annotations

import hashlib
import json
import zipfile
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


def _is_bytecode_noise(path: Path) -> bool:
    """Runtime bytecode must not affect distribution freshness digests."""
    return path.suffix == ".pyc" or "__pycache__" in path.parts


def _tree_digest(root: Path, rel: str) -> str:
    base = root / rel
    if not base.exists():
        return ""
    if base.is_file():
        return _file_digest(base)
    h = hashlib.sha256()
    for item in sorted(base.rglob("*")):
        if item.is_file() and not _is_bytecode_noise(item):
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


def _resolve_zipapp(root: Path, dist_target: str) -> Path | None:
    platform_dir = root / dist_target
    pyz = platform_dir / "shipwright.pyz"
    if pyz.exists():
        return pyz.resolve()
    versioned = sorted(platform_dir.glob("shipwright-*.pyz"))
    return versioned[-1] if versioned else None


def _zipapp_arc_prefix(rel: str) -> str | None:
    if not rel.startswith("scripts/"):
        return None
    return rel[len("scripts/") :]


def _zipapp_file_digest(pyz: Path, arcname: str) -> str | None:
    with zipfile.ZipFile(pyz) as zf:
        try:
            return hashlib.sha256(zf.read(arcname)).hexdigest()
        except KeyError:
            return None


def _zipapp_tree_digest(pyz: Path, arc_prefix: str) -> str:
    h = hashlib.sha256()
    with zipfile.ZipFile(pyz) as zf:
        names = sorted(
            name
            for name in zf.namelist()
            if name.startswith(arc_prefix) and not name.endswith("/")
        )
        for name in names:
            if "__pycache__" in name or name.endswith(".pyc"):
                continue
            rel_name = name[len(arc_prefix) :] if arc_prefix else name
            h.update(rel_name.encode())
            h.update(zf.read(name))
    return h.hexdigest()


def _zipapp_digest(root: Path, dist_target: str, rel: str) -> str | None:
    arc = _zipapp_arc_prefix(rel)
    if arc is None:
        return None
    pyz = _resolve_zipapp(root, dist_target)
    if pyz is None:
        return None
    if rel.endswith("/"):
        return _zipapp_tree_digest(pyz, arc)
    return _zipapp_file_digest(pyz, arc)


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
                    zip_digest = _zipapp_digest(root, target, rel)
                    if zip_digest is not None:
                        if zip_digest != source_digest:
                            stale.append(
                                {
                                    "kind": "zipapp-stale",
                                    "group": group,
                                    "path": rel,
                                    "target": target,
                                }
                            )
                        continue
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
