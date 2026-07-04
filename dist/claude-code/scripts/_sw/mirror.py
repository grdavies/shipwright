"""Python mirror-copy library replacing rsync -a --delete (R6)."""

from __future__ import annotations

import fnmatch
import os
import shutil
import stat
from pathlib import Path


def _matches_excludes(rel_posix: str, excludes: list[str]) -> bool:
    for pattern in excludes:
        pat = pattern.rstrip("/")
        if fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(rel_posix, f"{pat}/*"):
            return True
        if rel_posix == pat or rel_posix.startswith(f"{pat}/"):
            return True
    return False


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_symlink():
        link_to = os.readlink(src)
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(link_to)
        return
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path, excludes: list[str], rel_prefix: str = "") -> None:
    for entry in sorted(src.iterdir(), key=lambda p: p.name):
        rel = f"{rel_prefix}{entry.name}" if not rel_prefix else f"{rel_prefix}/{entry.name}"
        if _matches_excludes(rel, excludes):
            continue
        target = dst / entry.name
        if entry.is_dir() and not entry.is_symlink():
            target.mkdir(parents=True, exist_ok=True)
            _copy_tree(entry, target, excludes, rel)
            continue
        _copy_file(entry, target)


def _prune_orphans(src: Path, dst: Path, excludes: list[str], rel_prefix: str = "") -> None:
    if not dst.exists():
        return
    for entry in sorted(dst.iterdir(), key=lambda p: p.name):
        rel = f"{rel_prefix}{entry.name}" if not rel_prefix else f"{rel_prefix}/{entry.name}"
        if _matches_excludes(rel, excludes):
            continue
        src_entry = src / entry.name
        if not src_entry.exists():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            continue
        if entry.is_dir() and not entry.is_symlink() and src_entry.is_dir():
            _prune_orphans(src_entry, entry, excludes, rel)


def _purge_excluded(dst: Path, excludes: list[str], rel_prefix: str = "") -> None:
    if not dst.exists():
        return
    for entry in sorted(dst.iterdir(), key=lambda p: p.name):
        rel = f"{rel_prefix}{entry.name}" if not rel_prefix else f"{rel_prefix}/{entry.name}"
        if _matches_excludes(rel, excludes):
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            continue
        if entry.is_dir() and not entry.is_symlink():
            _purge_excluded(entry, excludes, rel)


def mirror(
    src: Path,
    dst: Path,
    *,
    excludes: list[str] | None = None,
    delete: bool = True,
    purge_excludes: bool = False,
) -> None:
    """Replicate ``rsync -a --delete`` semantics for directory trees."""
    excludes = list(excludes or [])
    if not src.is_dir():
        raise FileNotFoundError(f"mirror source not found: {src}")
    dst.mkdir(parents=True, exist_ok=True)
    _copy_tree(src, dst, excludes)
    if delete:
        _prune_orphans(src, dst, excludes)
    if purge_excludes:
        _purge_excluded(dst, excludes)
