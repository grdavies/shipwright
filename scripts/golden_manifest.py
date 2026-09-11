#!/usr/bin/env python3
"""Generate and verify the cursor golden manifest from ``dist/cursor`` (PRD 343).

Canonical output: ``scripts/test/fixtures/parity/cursor-golden.manifest``.
Generation is deterministic and idempotent (R2): two consecutive runs with the
same tree produce byte-identical manifest bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

# Keep skip rules aligned with scripts/snapshot-tree.py so existing parity
# consumers see the same path set.
_EMITTABLE = ("commands", "skills", "rules", "agents", "providers")
_DEFAULT_MANIFEST_REL = Path("scripts/test/fixtures/parity/cursor-golden.manifest")


def should_skip(relpath: str) -> bool:
    if "__pycache__" in relpath or relpath.endswith(".pyc"):
        return True
    if relpath.endswith(".bak"):
        return True
    if "/.git/" in relpath or "/node_modules/" in relpath:
        return True
    if "/.cursor/sw-coverage/" in relpath or relpath.startswith(".cursor/sw-coverage/"):
        return True
    if relpath.startswith("scripts/.cursor/sw-coverage/"):
        return True
    if relpath == "scripts/test" or relpath.startswith("scripts/test/"):
        return True
    if relpath == "scripts/install.py":
        return True
    if relpath.startswith("hooks"):
        return True
    return False


def resolve_snapshot_root(repo_root: Path) -> Path:
    """Prefer ``dist/cursor`` when present; else ``core``; else repo root."""
    dist_cursor = repo_root / "dist" / "cursor"
    if (dist_cursor / "providers").is_dir() or (dist_cursor / "commands").is_dir():
        return dist_cursor
    core = repo_root / "core"
    if (core / "providers").is_dir() or (core / "commands").is_dir():
        return core
    return repo_root


def default_manifest_path(repo_root: Path) -> Path:
    return repo_root / _DEFAULT_MANIFEST_REL


def iter_snapshot_files(snapshot_root: Path) -> Iterable[tuple[str, Path]]:
    for dirname in _EMITTABLE:
        base = snapshot_root / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(snapshot_root).as_posix()
            if should_skip(rel):
                continue
            yield rel, path
    scripts = snapshot_root / "scripts"
    if scripts.is_dir():
        for path in sorted(scripts.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(snapshot_root).as_posix()
            if should_skip(rel):
                continue
            yield rel, path


def render_manifest(snapshot_root: Path) -> str:
    """Return deterministic manifest text (sorted ``rel\\tsha256`` lines + trailing newline)."""
    lines: list[str] = []
    seen: set[str] = set()
    for rel, path in iter_snapshot_files(snapshot_root):
        if rel in seen:
            continue
        seen.add(rel)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{rel}\t{digest}")
    if not lines:
        return ""
    return "\n".join(sorted(lines)) + "\n"


def generate_manifest_text(repo_root: Path) -> str:
    return render_manifest(resolve_snapshot_root(repo_root))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_manifest(
    repo_root: Path,
    *,
    out_path: Path | None = None,
) -> dict[str, object]:
    """Generate and write the golden manifest. Idempotent for unchanged trees."""
    text = generate_manifest_text(repo_root)
    target = out_path if out_path is not None else default_manifest_path(repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    before = target.read_text(encoding="utf-8") if target.is_file() else None
    target.write_text(text, encoding="utf-8")
    after = target.read_text(encoding="utf-8")
    return {
        "verdict": "pass",
        "action": "generate",
        "path": str(target.relative_to(repo_root)) if target.is_relative_to(repo_root) else str(target),
        "bytes": len(after.encode("utf-8")),
        "sha256": content_hash(after),
        "changed": before != after,
        "snapshotRoot": str(resolve_snapshot_root(repo_root).relative_to(repo_root))
        if resolve_snapshot_root(repo_root).is_relative_to(repo_root)
        else str(resolve_snapshot_root(repo_root)),
    }


def check_staleness(
    repo_root: Path,
    *,
    manifest_path: Path | None = None,
) -> dict[str, object]:
    """Compare on-disk manifest to freshly generated content (PRD 343 R3).

    Available in phase 1 for unit coverage; gate wiring lands in phase 2.
    """
    target = manifest_path if manifest_path is not None else default_manifest_path(repo_root)
    expected = generate_manifest_text(repo_root)
    expected_hash = content_hash(expected)
    if not target.is_file():
        return {
            "verdict": "fail",
            "action": "check-staleness",
            "stale": True,
            "error": "manifest-missing",
            "path": str(target),
            "expectedSha256": expected_hash,
        }
    actual = target.read_text(encoding="utf-8")
    actual_hash = content_hash(actual)
    stale = actual != expected
    return {
        "verdict": "fail" if stale else "pass",
        "action": "check-staleness",
        "stale": stale,
        "path": str(target.relative_to(repo_root)) if target.is_relative_to(repo_root) else str(target),
        "actualSha256": actual_hash,
        "expectedSha256": expected_hash,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="golden_manifest",
        description="Generate or verify scripts/test/fixtures/parity/cursor-golden.manifest",
    )
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate", help="Write golden manifest from dist/cursor (default)")
    gen.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (default: scripts/test/fixtures/parity/cursor-golden.manifest)",
    )
    gen.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON receipt on stdout",
    )

    chk = sub.add_parser(
        "check-staleness",
        help="Fail when on-disk manifest differs from dist/cursor snapshot",
    )
    chk.add_argument("--manifest", type=Path, default=None, help="Manifest path to check")
    chk.add_argument("--json", action="store_true", help="Emit JSON receipt on stdout")

    # Default command = generate when no subcommand given.
    parser.set_defaults(command="generate", out=None, json=False, manifest=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    # Allow bare invocation and `generate` synonym.
    if not argv or argv[0].startswith("-"):
        argv = ["generate", *argv]
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent

    if args.command == "generate":
        result = write_manifest(repo_root, out_path=args.out)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"golden_manifest: wrote {result['path']} sha256={result['sha256']}")
        return 0

    if args.command == "check-staleness":
        result = check_staleness(repo_root, manifest_path=args.manifest)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        elif result.get("stale"):
            print(
                f"golden_manifest: STALE {result.get('path')} "
                f"actual={result.get('actualSha256')} expected={result.get('expectedSha256')}",
                file=sys.stderr,
            )
        else:
            print(f"golden_manifest: fresh {result.get('path')}")
        return 0 if result.get("verdict") == "pass" else 20

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    run_module_main(main)
