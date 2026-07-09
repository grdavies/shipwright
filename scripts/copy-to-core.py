#!/usr/bin/env python3
"""Refresh core/ workflow copies from repo-root sources (R5).

Replaces ``copy-to-core.sh`` with stdlib JSON parsing and mirror-copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from _sw import logging_setup, mirror
from _sw.cli import build_parser, run_module_main

PROVENANCE_REL = ".sw/build-chain-last-synced.json"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_manifest(root: Path) -> dict:
    manifest_path = root / "core" / "sw-reference" / "build-chain-sot.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing manifest {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _is_allowlisted(rel: str, allowlist: list[str]) -> bool:
    for entry in allowlist:
        if entry.endswith("/"):
            prefix = entry[:-1]
            if rel == prefix or rel.startswith(f"{prefix}/"):
                return True
        elif rel == entry:
            return True
    return False


def _is_deprecated(rel: str, deprecated: list[str]) -> bool:
    for entry in deprecated:
        if not entry:
            continue
        if rel == entry or rel.startswith(f"{entry}/"):
            return True
    return False


def _sw_source_has_path(sw_dir: Path, rel: str) -> bool:
    if (sw_dir / rel).exists():
        return True
    parent = rel
    while "/" in parent:
        parent = parent.rsplit("/", 1)[0]
        if (sw_dir / parent).exists():
            return True
    return False


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sw_reference_tree_hashes(base: Path) -> dict[str, str]:
    if not base.is_dir():
        return {}
    out: dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        if path.is_file():
            rel = path.relative_to(base).as_posix()
            out[rel] = _file_hash(path)
    return out


def _provenance_path(root: Path) -> Path:
    return root / PROVENANCE_REL


def _load_provenance(root: Path) -> dict | None:
    path = _provenance_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _write_provenance(root: Path, core_hashes: dict[str, str]) -> None:
    path = _provenance_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "syncedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "coreSwReference": core_hashes,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _force_escape_allowed() -> bool:
    if os.environ.get("SW_BUILD_CHAIN_FORCE") == "1":
        return True
    if os.environ.get("SW_ISSUES_FIXTURE") == "1":
        return True
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        return True
    return False


def _refuse_force_outside_escape() -> None:
    logging_setup.error(
        "copy-to-core: --force is fixture/CI-only — set SW_BUILD_CHAIN_FORCE=1 in CI or use .sw/ remediation"
    )
    raise SystemExit(1)


def check_core_sw_reference_divergence(
    root: Path,
    sw_dir: Path,
    manifest: dict,
    *,
    force: bool,
) -> None:
    """Refuse when core/sw-reference diverged without a matching .sw/ source (PRD 060 R11)."""
    if force and not _force_escape_allowed():
        _refuse_force_outside_escape()

    core_ref = root / "core" / "sw-reference"
    if not core_ref.is_dir():
        return

    allowlist = list(manifest.get("coreAuthoredAllowlist", []))
    current = _sw_reference_tree_hashes(core_ref)
    sw_hashes = _sw_reference_tree_hashes(sw_dir)
    provenance = _load_provenance(root)
    last = (provenance or {}).get("coreSwReference") if isinstance(provenance, dict) else {}
    if not isinstance(last, dict):
        last = {}

    diverged: list[str] = []
    for rel, core_hash in sorted(current.items()):
        if _is_allowlisted(rel, allowlist):
            continue
        sw_hash = sw_hashes.get(rel)
        if sw_hash and sw_hash == core_hash:
            continue
        prior = last.get(rel)
        if prior and prior == core_hash:
            continue
        if sw_hash is None and not _sw_source_has_path(sw_dir, rel):
            continue
        diverged.append(rel)

    if not diverged:
        return

    if force:
        logging_setup.warning(
            "copy-to-core: WARNING --force proceeding past core/sw-reference divergence: "
            + " ".join(diverged)
        )
        return

    logging_setup.error("copy-to-core: refuse core-only divergence (fail-closed):")
    for rel in diverged:
        logging_setup.error(f"  - {rel}")
    logging_setup.error(
        "copy-to-core: copy edits into .sw/ then re-run, or use fixture/CI-only --force"
    )
    raise SystemExit(1)


def check_sw_reference_orphans(core: Path, sw_dir: Path, manifest: dict, *, force: bool) -> None:
    sw_reference = core / "sw-reference"
    if not sw_reference.is_dir():
        return
    if force and not _force_escape_allowed():
        _refuse_force_outside_escape()

    allowlist = list(manifest.get("coreAuthoredAllowlist", []))
    deprecated = list(manifest.get("deprecatedAllowlist", []) or [])
    orphans: list[str] = []
    for path in sorted(sw_reference.rglob("*")):
        if not path.is_file() and not path.is_dir():
            continue
        rel = path.relative_to(sw_reference).as_posix()
        if _is_allowlisted(rel, allowlist):
            continue
        if _is_deprecated(rel, deprecated):
            continue
        if _sw_source_has_path(sw_dir, rel):
            continue
        orphans.append(rel)
    if not orphans:
        return
    if force:
        logging_setup.warning(
            f"copy-to-core: WARNING --force deleting sw-reference orphans: {' '.join(orphans)}"
        )
        return
    logging_setup.error("copy-to-core: refuse orphan deletion under core/sw-reference/ (fail-closed):")
    for rel in orphans:
        logging_setup.error(f"  - {rel}")
    logging_setup.error(
        "copy-to-core: add to coreAuthoredAllowlist, relocate to .sw/, deprecatedAllowlist, or use --force"
    )
    raise SystemExit(1)


def sync(root: Path, *, force: bool = False) -> int:
    core = root / "core"
    manifest = load_manifest(root)
    core.mkdir(parents=True, exist_ok=True)

    sw_reference_input = None
    if (root / ".pf").is_dir():
        sw_reference_input = root / ".pf"
    elif (root / ".sw").is_dir():
        sw_reference_input = root / ".sw"

    if sw_reference_input is not None:
        check_core_sw_reference_divergence(root, sw_reference_input, manifest, force=force)

    for dirname in ("commands", "skills", "rules", "agents", "providers"):
        src = root / dirname
        if not src.is_dir():
            continue
        mirror.mirror(src, core / dirname, delete=True)

    roles = manifest.get("roles") or {}
    core_scripts = roles.get("coreScripts") or {}
    scripts_excludes = list(core_scripts.get("excludes") or ["test/", "check-frozen.py"])
    if "*.bak" not in scripts_excludes:
        scripts_excludes.append("*.bak")
    mirror.mirror(root / "scripts", core / "scripts", excludes=scripts_excludes, delete=True, purge_excludes=True)
    frozen = core / "scripts" / "check-frozen.py"
    if frozen.exists():
        frozen.unlink()

    if sw_reference_input is not None:
        check_sw_reference_orphans(core, sw_reference_input, manifest, force=force)
        excludes = list(manifest.get("coreAuthoredAllowlist", [])) if sw_reference_input.name == ".sw" else []
        excludes.append("build-chain-last-synced.json")
        mirror.mirror(sw_reference_input, core / "sw-reference", excludes=excludes, delete=True)

    _write_provenance(root, _sw_reference_tree_hashes(core / "sw-reference"))
    logging_setup.info(f"copy-to-core: synced emittable content -> {core}")
    return 0


def build_parser_copy() -> argparse.ArgumentParser:
    parser = build_parser(
        prog="copy-to-core",
        description="Sync repo-root harness and content dirs into core/ per build-chain-sot.json.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fixture/CI-only escape for orphan deletion and provenance divergence (logged)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser_copy()
    args = parser.parse_args(argv)
    try:
        return sync(repo_root(), force=args.force)
    except FileNotFoundError as exc:
        logging_setup.error(str(exc))
        return 1


if __name__ == "__main__":
    run_module_main(lambda: main())
