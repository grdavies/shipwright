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
from runtime_requirements import runtime_requirements_present, sync_runtime_bundle


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


def build_wheel(root: Path, *, out_dir: Path) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(out_dir)],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "pip wheel failed")
    wheels = sorted(out_dir.glob("shipwright_workflow-*.whl"))
    if not wheels:
        raise RuntimeError(f"no shipwright_workflow wheel emitted under {out_dir}")
    return {"verdict": "pass", "wheel": wheels[-1].as_posix()}


def build_dist(
    root: Path,
    *,
    skip_generate: bool = False,
    sync_runtime: bool = True,
    build_wheel_flag: bool = False,
    wheel_dir: Path | None = None,
) -> dict:
    if not skip_generate:
        run_generate(root)

    missing = runtime_requirements_present(root)
    if missing:
        return {"verdict": "error", "error": f"missing runtime requirements: {', '.join(missing)}"}

    roots = default_install_roots(root)
    if not roots:
        return {"verdict": "error", "error": "no dist install roots found"}

    transformed: list[dict[str, int | str]] = []
    for install_root in roots:
        docs_root = install_root / "documentation"
        stats = transform_tree(docs_root)
        transformed.append({"installRoot": install_root.as_posix(), **stats})

    bundle = None
    if sync_runtime:
        bundle = sync_runtime_bundle(root)

    wheel = None
    if build_wheel_flag:
        wheel = build_wheel(root, out_dir=wheel_dir or (root / "dist" / "wheels"))

    result: dict[str, object] = {
        "verdict": "pass",
        "transformed": transformed,
        "runtimeBundle": bundle,
    }
    if wheel is not None:
        result["wheel"] = wheel
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build dist and rewrite install-root doc links")
    parser.add_argument("--root", type=Path, default=repo_root())
    parser.add_argument(
        "--skip-generate",
        action="store_true",
        help="Only apply link transforms to existing dist/*/documentation trees",
    )
    parser.add_argument(
        "--skip-runtime-sync",
        action="store_true",
        help="Skip mirroring runtime requirements into sw/ for wheel packaging",
    )
    parser.add_argument(
        "--wheel",
        action="store_true",
        help="After sync, build shipwright-workflow wheel under dist/wheels/",
    )
    parser.add_argument(
        "--wheel-dir",
        type=Path,
        default=None,
        help="Override wheel output directory (default: <root>/dist/wheels)",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    try:
        result = build_dist(
            root,
            skip_generate=args.skip_generate,
            sync_runtime=not args.skip_runtime_sync,
            build_wheel_flag=args.wheel,
            wheel_dir=args.wheel_dir,
        )
    except RuntimeError as exc:
        print(json.dumps({"verdict": "error", "error": str(exc)}), file=sys.stderr)
        return 2

    print(json.dumps(result, separators=(",", ":")))
    return 0 if result.get("verdict") == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
