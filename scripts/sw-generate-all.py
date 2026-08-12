#!/usr/bin/env python3
"""Allowlisted generate step for build-chain sync (PRD 060 R12 / 080 phase 26)."""
from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Final

from _sw.cli import run_module_main

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_ROOT = REPO_ROOT / "dist"
PLATFORMS: Final[tuple[str, ...]] = ("cursor", "claude-code")

# Credential broker + hook/command/rule/provider surfaces that must stay in dist sync.
CREDENTIAL_SOURCE_PREFIXES: Final[tuple[str, ...]] = (
    "scripts/credentials/",
    "scripts/credentials-doctor.py",
    "scripts/env-read-guard.py",
    "scripts/init_credential_migration.py",
    "scripts/_sw/env-read-exemptions.json",
    "scripts/_sw/credential-migration-release.json",
    "rules/sw-guardrails.mdc",
    "commands/sw-init.md",
    "providers/host/",
    "providers/planning-store/",
    "providers/recallium.md",
    "hooks/before_task_dispatch.py",
    "hooks/guardrail_core.py",
)


def _discover_platforms(root: Path) -> tuple[str, ...]:
    platforms_root = root / "platforms"
    if not platforms_root.is_dir():
        return PLATFORMS
    names = sorted(
        child.name
        for child in platforms_root.iterdir()
        if child.is_dir() and (child / "emitter.py").is_file()
    )
    return tuple(names) if names else PLATFORMS


def credential_affected_rel_paths(root: Path | None = None) -> list[str]:
    """Return repo-relative paths for credential-affected broker and workflow surfaces."""
    base = root or REPO_ROOT
    paths: list[str] = []
    for prefix in CREDENTIAL_SOURCE_PREFIXES:
        candidate = base / prefix
        core_candidate = base / "core" / prefix
        if candidate.is_file():
            paths.append(prefix)
            continue
        if core_candidate.is_file():
            paths.append(prefix)
            continue
        scan_roots: list[tuple[Path, str]] = []
        if candidate.is_dir():
            scan_roots.append((candidate, prefix))
        elif core_candidate.is_dir():
            scan_roots.append((core_candidate, prefix))
        if not scan_roots:
            continue
        for scan_root, rel_prefix in scan_roots:
            for path in sorted(scan_root.rglob("*")):
                if not path.is_file():
                    continue
                rel = f"{rel_prefix.rstrip('/')}/{path.relative_to(scan_root).as_posix()}"
                if "/__pycache__/" in f"/{rel}/" or rel.endswith(".pyc"):
                    continue
                paths.append(rel)
    return paths


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_source(base: Path, rel: str) -> Path | None:
    core_path = base / "core" / rel
    source_path = base / rel
    if core_path.is_file():
        return core_path
    if source_path.is_file():
        return source_path
    return None


def _zipapp_arcname(rel: str) -> str | None:
    if not rel.startswith("scripts/"):
        return None
    return rel[len("scripts/") :]


def _resolve_zipapp(base: Path, platform: str) -> Path | None:
    pyz = base / "dist" / platform / "shipwright.pyz"
    if not pyz.exists():
        versioned = sorted((base / "dist" / platform).glob("shipwright-*.pyz"))
        if not versioned:
            return None
        return versioned[-1]
    return pyz.resolve()


def _zipapp_entry_hash(pyz: Path, arcname: str) -> str | None:
    with zipfile.ZipFile(pyz) as zf:
        try:
            return hashlib.sha256(zf.read(arcname)).hexdigest()
        except KeyError:
            return None


def _dist_surface_path(base: Path, platform: str, canonical: Path) -> Path:
    try:
        core_rel = canonical.relative_to(base / "core")
    except ValueError:
        return base / "dist" / platform / canonical.relative_to(base).as_posix()
    for candidate in (
        base / "dist" / platform / "core" / core_rel,
        base / "dist" / platform / core_rel,
    ):
        if candidate.is_file():
            return candidate
    return base / "dist" / platform / core_rel


def credential_dist_drift(root: Path | None = None) -> list[str]:
    """Return repo-relative dist paths that differ from core source for credential surfaces."""
    base = root or REPO_ROOT
    drift: list[str] = []
    for rel in credential_affected_rel_paths(base):
        canonical = _canonical_source(base, rel)
        if canonical is None:
            continue
        digest = _file_hash(canonical)
        arcname = _zipapp_arcname(rel)
        for platform in _discover_platforms(base):
            if arcname is not None:
                pyz = _resolve_zipapp(base, platform)
                label = f"dist/{platform}/shipwright.pyz#{arcname}"
                if pyz is None:
                    drift.append(label)
                    continue
                entry_hash = _zipapp_entry_hash(pyz, arcname)
                if entry_hash is None or entry_hash != digest:
                    drift.append(label)
                continue
            dist_path = _dist_surface_path(base, platform, canonical)
            if not dist_path.is_file():
                drift.append(dist_path.relative_to(base).as_posix())
                continue
            if _file_hash(dist_path) != digest:
                drift.append(dist_path.relative_to(base).as_posix())
    return drift


def generate_all(root: Path | None = None) -> int:
    base = root or REPO_ROOT
    result = subprocess.run(
        [sys.executable, "-m", "sw", "generate", "--all"],
        cwd=str(base),
    )
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    del argv
    code = generate_all()
    if code != 0:
        return code
    drift = credential_dist_drift()
    if drift:
        print("FAIL sw-generate-all: credential dist drift after generate:", file=sys.stderr)
        for path in drift:
            print(f"  {path}", file=sys.stderr)
        return 1
    print("OK sw-generate-all: credential surfaces regenerated")
    return 0


if __name__ == "__main__":
    run_module_main(main)
