"""sw CLI — minimal generation entrypoint (M0–M3)."""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_ROOT = REPO_ROOT / "core"
PLATFORMS_ROOT = REPO_ROOT / "platforms"
DIST_ROOT = REPO_ROOT / "dist"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from capability_index import write_index  # noqa: E402
from kernel_classification import sync_sw_ship_chain_markers  # noqa: E402


def _discover_platforms() -> list[str]:
    if not PLATFORMS_ROOT.is_dir():
        return []
    names: list[str] = []
    for child in sorted(PLATFORMS_ROOT.iterdir()):
        if child.is_dir() and (child / "emitter.py").is_file():
            names.append(child.name)
    return names


def _load_emitter_module(platform: str):
    emitter_path = PLATFORMS_ROOT / platform / "emitter.py"
    if not emitter_path.is_file():
        raise SystemExit(f"sw generate: no emitter for platform '{platform}' at {emitter_path}")
    spec = importlib.util.spec_from_file_location(f"sw_emitter_{platform}", emitter_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"sw generate: failed to load emitter module for {platform}")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(emitter_path.parent))
    sys.path.insert(0, str(REPO_ROOT / "sw"))
    spec.loader.exec_module(mod)
    return mod


def generate_platform(platform: str, *, core_root: Path | None = None, dest_root: Path | None = None) -> Path:
    core = core_root or CORE_ROOT
    repo = core.parent if (core_root and core.name == "core") else REPO_ROOT
    if (core / "sw-reference" / "kernel-classification.json").is_file():
        sync_sw_ship_chain_markers(repo)
    write_index(core)
    dest = (dest_root or DIST_ROOT) / platform
    mod = _load_emitter_module(platform)
    if not hasattr(mod, "emit"):
        raise SystemExit(f"sw generate: emitter for {platform} missing emit()")
    mod.emit(core, REPO_ROOT, dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sw", description="Shipwright platform generator")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Emit dist/<platform>/ from core/")
    gen.add_argument("platform", nargs="?", help="Platform id (e.g. cursor, claude-code)")
    gen.add_argument("--all", action="store_true", help="Generate all platforms with emitters")
    gen.add_argument("--core", type=Path, default=None, help="Override core/ root (fixtures)")
    gen.add_argument("--dest", type=Path, default=None, help="Override dist output root")
    gen.add_argument(
        "--install",
        metavar="DEST",
        nargs="?",
        const="",
        default=None,
        help="After generating, run scripts/install.py [DEST] for the cursor platform",
    )

    args = parser.parse_args(argv)
    if args.command != "generate":
        return 1

    platforms: list[str]
    if args.all:
        platforms = _discover_platforms()
        if not platforms:
            print("sw generate --all: no platform emitters found", file=sys.stderr)
            return 1
    elif args.platform:
        platforms = [args.platform]
    else:
        gen.print_help()
        return 1

    for platform in platforms:
        out = generate_platform(platform, core_root=args.core, dest_root=args.dest)
        print(f"sw generate: wrote {out}")

    if args.install is not None and "cursor" in platforms:
        install_script = REPO_ROOT / "scripts" / "install.py"
        if not install_script.is_file():
            print(f"sw generate: --install: script not found at {install_script}", file=sys.stderr)
            return 1
        cmd: list[str] = [sys.executable, str(install_script)]
        if args.install:
            cmd.append(args.install)
        dest_root = args.dest or DIST_ROOT
        env = {**os.environ, "SW_INSTALL_SRC": str(dest_root / "cursor")}
        result = subprocess.run(cmd, check=False, env=env)
        if result.returncode != 0:
            return result.returncode
    elif args.install is not None:
        print(
            "sw generate: --install: skipped (cursor platform not in this generate run)",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
