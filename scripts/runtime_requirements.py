"""Runtime paths bundled into the shipwright-workflow wheel (PRD 345 R2)."""

from __future__ import annotations

import shutil
from pathlib import Path

# Repo-root trees mirrored under ``sw/`` for wheel-only installs.
RUNTIME_TREE_NAMES: tuple[str, ...] = ("scripts", "dist")

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
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        if filter_rel is not None and not filter_rel(rel):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def sync_runtime_bundle(root: Path) -> dict[str, object]:
    """Mirror runtime requirement trees into ``sw/`` for wheel packaging."""
    root = root.resolve()
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

    return {"verdict": "pass", "copied": copied, "targets": {k: v.as_posix() for k, v in targets.items()}}


def runtime_requirements_present(root: Path) -> list[str]:
    """Return missing runtime requirement paths relative to repo root."""
    root = root.resolve()
    missing: list[str] = []
    for name in RUNTIME_TREE_NAMES:
        if not (root / name).is_dir():
            missing.append(name)
    if not (root / "version.txt").is_file():
        missing.append("version.txt")
    return missing
