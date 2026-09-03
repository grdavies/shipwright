#!/usr/bin/env python3
"""Sync repo-root emittable content into core/ with authored-file protection (PRD 337 R12).

Operator entry point for the build chain. Wraps ``core_content_sync`` with explicit
``coreAuthoredAllowlist`` enforcement and dist authored-file preservation around
``python3 -m sw generate --all``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _sw import logging_setup
from _sw.cli import build_parser, run_module_main

import core_content_sync as _ccs

DIST_PLATFORMS = ("cursor", "claude-code")


def repo_root() -> Path:
    return _ccs.repo_root()


def load_manifest(root: Path) -> dict:
    return _ccs.load_manifest(root)


def _is_allowlisted(rel: str, allowlist: list[str]) -> bool:
    return _ccs._is_allowlisted(rel, allowlist)


def reject_unregistered_core_sot(root: Path, manifest: dict, *, force: bool = False) -> None:
    """Fail closed when core/sw-reference holds SoT files absent from coreAuthoredAllowlist (R12)."""
    if force and _ccs._force_escape_allowed():
        return

    core = root / "core"
    sw_dir = root / ".sw"
    if not sw_dir.is_dir():
        sw_dir = root / ".pf" if (root / ".pf").is_dir() else None
    if sw_dir is None:
        return

    allowlist = list(manifest.get("coreAuthoredAllowlist", []))
    deprecated = list(manifest.get("deprecatedAllowlist", []) or [])
    sw_reference = core / "sw-reference"
    if not sw_reference.is_dir():
        return

    unregistered: list[str] = []
    for path in sorted(sw_reference.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(sw_reference).as_posix()
        if _is_allowlisted(rel, allowlist):
            continue
        if _ccs._is_deprecated(rel, deprecated):
            continue
        if _ccs._sw_source_has_path(sw_dir, rel):
            continue
        if _ccs.mirror.matches_exclude_patterns(rel, list(_ccs.OPERATOR_LOCAL_PURGE_TARGETS)):
            continue
        unregistered.append(rel)

    if not unregistered:
        return

    logging_setup.error("copy-to-core: refuse unregistered core SoT (fail-closed):")
    for rel in unregistered:
        logging_setup.error(f"  - {rel}")
    logging_setup.error(
        "copy-to-core: add each path to coreAuthoredAllowlist in build-chain-sot.json "
        "or relocate the source into .sw/ before phase PRs land"
    )
    raise SystemExit(1)


def snapshot_authored_dist(root: Path, manifest: dict) -> dict[str, bytes]:
    """Capture allowlisted sw-reference bytes from dist/ before generate wipes the tree."""
    allowlist = list(manifest.get("coreAuthoredAllowlist", []))
    snapshot: dict[str, bytes] = {}
    for platform in DIST_PLATFORMS:
        ref = root / "dist" / platform / "core" / "sw-reference"
        if not ref.is_dir():
            continue
        for path in sorted(ref.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(ref).as_posix()
            if not _is_allowlisted(rel, allowlist):
                continue
            snapshot[f"{platform}/{rel}"] = path.read_bytes()
    return snapshot


def restore_authored_dist(root: Path, snapshot: dict[str, bytes]) -> None:
    """Restore authored dist sw-reference files removed or overwritten by generate."""
    for key, content in snapshot.items():
        platform, rel = key.split("/", 1)
        dest = root / "dist" / platform / "core" / "sw-reference" / rel
        if dest.is_file() and dest.read_bytes() == content:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)


def generate_all_preserving_authored(root: Path) -> int:
    """Run ``sw generate --all`` without wiping authored dist sw-reference files (R12)."""
    manifest = load_manifest(root)
    snapshot = snapshot_authored_dist(root, manifest)
    proc = subprocess.run(
        [sys.executable, "-m", "sw", "generate", "--all"],
        cwd=str(root),
        check=False,
    )
    if proc.returncode != 0:
        return proc.returncode
    restore_authored_dist(root, snapshot)
    return 0


def sync(root: Path, *, force: bool = False) -> int:
    manifest = load_manifest(root)
    reject_unregistered_core_sot(root, manifest, force=force)
    return _ccs.sync(root, force=force)


def build_parser_copy() -> argparse.ArgumentParser:
    parser = build_parser(
        prog="copy-to-core",
        description="Sync repo-root content into core/ with coreAuthoredAllowlist enforcement.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fixture/CI-only escape for orphan deletion and provenance divergence (logged)",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("sync", "generate"),
        default="sync",
        help="sync: mirror into core/ (default); generate: sw generate --all with authored dist preservation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser_copy()
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            return generate_all_preserving_authored(repo_root())
        return sync(repo_root(), force=args.force)
    except FileNotFoundError as exc:
        logging_setup.error(str(exc))
        return 1


if __name__ == "__main__":
    run_module_main(lambda: main())
