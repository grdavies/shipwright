#!/usr/bin/env python3
"""Build packaged platform dist and apply install-root documentation link transforms (PRD 345)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from docs_link_transform import default_install_roots, transform_tree


def repo_root() -> Path:
    return SCRIPT_DIR.parent


def run_generate(root: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sw", "generate", "--all"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "sw generate --all failed")


def build_dist(root: Path, *, skip_generate: bool = False) -> dict:
    if not skip_generate:
        run_generate(root)

    roots = default_install_roots(root)
    if not roots:
        return {"verdict": "error", "error": "no dist install roots found"}

    transformed: list[dict[str, int | str]] = []
    for install_root in roots:
        docs_root = install_root / "documentation"
        stats = transform_tree(docs_root)
        transformed.append({"installRoot": install_root.as_posix(), **stats})

    return {"verdict": "pass", "transformed": transformed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build dist and rewrite install-root doc links")
    parser.add_argument("--root", type=Path, default=repo_root())
    parser.add_argument(
        "--skip-generate",
        action="store_true",
        help="Only apply link transforms to existing dist/*/documentation trees",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    try:
        result = build_dist(root, skip_generate=args.skip_generate)
    except RuntimeError as exc:
        print(json.dumps({"verdict": "error", "error": str(exc)}), file=sys.stderr)
        return 2

    print(json.dumps(result, separators=(",", ":")))
    return 0 if result.get("verdict") == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
