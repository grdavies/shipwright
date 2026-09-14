"""Runtime paths bundled into the shipwright-workflow wheel (PRD 345 R2)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# This module is loaded via importlib in ``sw/build_support.py`` during PEP 517
# wheel builds, when ``_sw`` is not on ``sys.path``. Walk the tree here instead
# of importing ``iter_tree_files`` — ``Path.rglob("*")`` skips hidden names.

# Repo-root trees mirrored under ``sw/`` for wheel-only installs.
RUNTIME_TREE_NAMES: tuple[str, ...] = ("scripts", "dist")

# Handoff validation modules mirrored under ``sw/`` (PRD 352 R14 / TR6).
HANDOFF_RUNTIME_MODULES: tuple[str, ...] = (
    "core/handoff/importer.py",
    "core/handoff/bundle.py",
    "core/handoff/validate_bundle.py",
    "core/handoff/acknowledgement.py",
    "scripts/handoff_bundle.py",
)

# Skip test-only subtrees from the packaged scripts mirror.
SCRIPT_EXCLUDE_PARTS: frozenset[str] = frozenset({"unit_tests", "test", "__pycache__"})


def bundle_targets(root: Path) -> dict[str, Path]:
    sw = root / "sw"
    return {
        "scripts": sw / "scripts",
        "dist": sw / "dist",
        "version.txt": sw / "version.txt",
    }


def _should_copy_script(rel: Path) -> bool:
    return not any(part in SCRIPT_EXCLUDE_PARTS for part in rel.parts)


def _copy_tree(src: Path, dest: Path, *, filter_rel: callable | None = None) -> int:
    if dest.exists():
        shutil.rmtree(dest)
    if not src.is_dir():
        return 0
    count = 0
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(src)
            if filter_rel is not None and not filter_rel(rel):
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            count += 1
    return count


def sync_handoff_runtime_modules(root: Path) -> dict[str, object]:
    """Mirror handoff validation modules into ``sw/`` preserving repo-relative paths."""
    root = root.resolve()
    missing: list[str] = []
    synced: list[str] = []
    for rel in HANDOFF_RUNTIME_MODULES:
        src = root / rel
        if not src.is_file():
            missing.append(rel)
            continue
        dest = root / "sw" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        synced.append(rel)
    if missing:
        return {
            "verdict": "fail",
            "error": "handoff:missing-dependency",
            "missing": missing,
        }
    core_init = root / "sw" / "core" / "__init__.py"
    if not core_init.is_file():
        core_init.parent.mkdir(parents=True, exist_ok=True)
        core_init.write_text('"""Shipwright core runtime mirror."""\n', encoding="utf-8")
        synced.append("core/__init__.py")
    handoff_init = root / "sw" / "core" / "handoff" / "__init__.py"
    if not handoff_init.is_file():
        handoff_init.parent.mkdir(parents=True, exist_ok=True)
        handoff_init.write_text('"""Handoff runtime mirror."""\n', encoding="utf-8")
        synced.append("core/handoff/__init__.py")
    return {"verdict": "pass", "synced": synced}


def sync_runtime_bundle(root: Path) -> dict[str, object]:
    """Mirror runtime requirement trees into ``sw/`` for wheel packaging."""
    root = root.resolve()
    handoff = sync_handoff_runtime_modules(root)
    if handoff.get("verdict") != "pass":
        return handoff
    targets = bundle_targets(root)
    copied: dict[str, int | str] = {}

    scripts_src = root / "scripts"
    scripts_dest = targets["scripts"]
    copied["scripts"] = _copy_tree(
        scripts_src,
        scripts_dest,
        filter_rel=_should_copy_script,
    )

    dist_src = root / "dist"
    dist_dest = targets["dist"]
    copied["dist"] = _copy_tree(dist_src, dist_dest)

    version_src = root / "version.txt"
    version_dest = targets["version.txt"]
    if version_src.is_file():
        version_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(version_src, version_dest)
        copied["version.txt"] = version_src.as_posix()
    else:
        copied["version.txt"] = "missing"

    return {
        "verdict": "pass",
        "copied": copied,
        "handoff": handoff,
        "targets": {k: v.as_posix() for k, v in targets.items()},
    }


def runtime_requirements_present(root: Path) -> list[str]:
    """Return missing runtime requirement paths relative to repo root."""
    root = root.resolve()
    missing: list[str] = []
    for name in RUNTIME_TREE_NAMES:
        if not (root / name).is_dir():
            missing.append(name)
    if not (root / "version.txt").is_file():
        missing.append("version.txt")
    for rel in HANDOFF_RUNTIME_MODULES:
        if not (root / rel).is_file():
            missing.append(rel)
    return missing
