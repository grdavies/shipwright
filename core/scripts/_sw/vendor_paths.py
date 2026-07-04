"""Inject vendored pure-Python packages onto sys.path (R12)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BOOTSTRAPPED = False


def repo_root(anchor: str | Path | None = None) -> Path:
    """Resolve repository root from vendor_paths or an anchor file/dir."""
    default = Path(__file__).resolve().parent.parent.parent
    if anchor is None:
        return default
    current = Path(anchor).resolve()
    if current.is_file():
        current = current.parent
    for _ in range(12):
        if (current / "scripts" / "unit_tests").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return default


def vendor_roots(root: Path | None = None) -> list[Path]:
    root = root or repo_root()
    manifest = json.loads((root / "scripts" / "_sw" / "depmanifest.json").read_text(encoding="utf-8"))
    paths: list[Path] = []
    for entry in (manifest.get("vendored") or {}).values():
        rel = entry.get("path", "")
        if not rel:
            continue
        candidate = root / rel
        if candidate.is_dir():
            paths.append(candidate.resolve())
    return paths


def bootstrap_vendor_paths(root: Path | None = None) -> list[Path]:
    """Prepend vendored package roots once; return paths added."""
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return []
    added: list[Path] = []
    for path in vendor_roots(root):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
            added.append(path)
    _BOOTSTRAPPED = True
    return added
