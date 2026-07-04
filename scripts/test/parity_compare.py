#!/usr/bin/env python3
"""Compare a directory tree against a parity manifest (relative-path<TAB>sha256)."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

EMITTABLE_ROOTS: tuple[str, ...] = (
    "commands",
    "skills",
    "rules",
    "agents",
    "providers",
    "scripts",
)


def should_skip_relpath(relpath: str) -> bool:
    norm = relpath.replace("\\", "/")
    if "/__pycache__/" in f"/{norm}/" or norm.endswith("/__pycache__") or norm == "__pycache__":
        return True
    if norm.endswith(".pyc") or norm.endswith(".bak"):
        return True
    if norm.startswith("scripts/test/") or norm == "scripts/test":
        return True
    if norm.startswith("scripts/.cursor/sw-coverage/") or norm == "scripts/.cursor/sw-coverage":
        return True
    if norm in ("scripts/install.sh", "scripts/install.py"):
        return True
    if norm.startswith("hooks/") or norm == "hooks":
        return True
    return False


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(manifest_path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if "\t" not in line:
            continue
        rel_path, expected_hash = line.split("\t", 1)
        rel_path = rel_path.strip()
        expected_hash = expected_hash.strip()
        if rel_path:
            entries[rel_path] = expected_hash
    return entries


def compare_tree(target_dir: Path, manifest_path: Path) -> tuple[int, str]:
    """Return (exit_code, message). Exit 0 on full match."""
    if not target_dir.is_dir():
        return 2, f"parity-compare: target is not a directory: {target_dir}"
    if not manifest_path.is_file():
        return 2, f"parity-compare: manifest not found: {manifest_path}"

    resolved_target = target_dir.resolve()
    manifest = load_manifest(manifest_path)

    for rel_path, expected_hash in manifest.items():
        target_file = resolved_target / rel_path
        if not target_file.is_file():
            return 1, f"parity-mismatch: missing file: {rel_path}"
        actual_hash = file_sha256(target_file)
        if actual_hash != expected_hash:
            return 1, f"parity-mismatch: hash diff: {rel_path}"

    for root_name in EMITTABLE_ROOTS:
        root_path = resolved_target / root_name
        if not root_path.is_dir():
            continue
        for file_path in root_path.rglob("*"):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(resolved_target)).replace("\\", "/")
            if should_skip_relpath(rel):
                continue
            if rel not in manifest:
                return 1, f"parity-mismatch: extra file: {rel}"

    return 0, f"parity-match: tree matches manifest ({len(manifest)} files)"


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        print("usage: parity_compare.py <target-dir> <manifest>", file=sys.stderr)
        return 2
    code, message = compare_tree(Path(args[0]), Path(args[1]))
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
