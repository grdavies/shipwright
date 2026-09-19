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

MCP_EMIT_PLATFORMS = frozenset({"codex", "opencode"})
ORCHESTRATOR_NAME_SUFFIX = "-orchestrator"


def _git_common_dir(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--git-common-dir"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return start.resolve()
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        common = (start / common).resolve()
    return common.parent.resolve()


def _primary_worktree_path(repo_root: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return repo_root.resolve()
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line.split(" ", 1)[1].strip()).resolve()
    return repo_root.resolve()


def process_repo_root() -> Path:
    """Git toplevel for the active generate checkout (PRD 362 — cwd authority)."""
    for start in (Path.cwd(), REPO_ROOT):
        proc = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip()).resolve()
    return REPO_ROOT.resolve()


def is_orchestrator_worktree(repo_root: Path) -> bool:
    """True when repo_root is a deliver orchestrator worktree under .sw-worktrees/ (PRD 362 R1)."""
    root = repo_root.resolve()
    primary = _primary_worktree_path(_git_common_dir(root))
    sw_root = primary / ".sw-worktrees"
    if not sw_root.is_dir():
        return False
    try:
        root.relative_to(sw_root.resolve())
    except ValueError:
        return False
    return root.name.endswith(ORCHESTRATOR_NAME_SUFFIX)


def orchestrator_generate_guarded(platforms: list[str], *, all_flag: bool) -> bool:
    if all_flag:
        return True
    return any(p in MCP_EMIT_PLATFORMS for p in platforms)


def refuse_orchestrator_generate(
    repo_root: Path,
    platforms: list[str],
    *,
    all_flag: bool,
    restore_plan: bool,
) -> int | None:
    """Return exit code when refused; None when allowed to proceed."""
    if not is_orchestrator_worktree(repo_root):
        return None
    if restore_plan:
        return None
    if not orchestrator_generate_guarded(platforms, all_flag=all_flag):
        return None
    print(
        "sw generate: refused from orchestrator worktree without --restore-plan "
        "(PRD 362 R1/R3); use platform-scoped generate from the primary checkout",
        file=sys.stderr,
    )
    return 20


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
    # Platforms share sibling module basenames (generator, hook_registry, …).
    # Clear them between loads so `sw generate --all` cannot cross-wire adapters
    # (PRD 349: Codex/OpenCode both expose generator.py).
    for shared in (
        "generator",
        "hook_registry",
        "plugin_manifest",
        "emitter_base",
        "lifecycle_plugin",
    ):
        sys.modules.pop(shared, None)
    spec = importlib.util.spec_from_file_location(f"sw_emitter_{platform}", emitter_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"sw generate: failed to load emitter module for {platform}")
    mod = importlib.util.module_from_spec(spec)
    # Prefer this platform dir for sibling imports; keep prior platform dirs from winning.
    plat_dir = str(emitter_path.parent)
    sys.path = [plat_dir, str(REPO_ROOT / "sw"), *[p for p in sys.path if p != plat_dir]]
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
    gen.add_argument(
        "--restore-plan",
        action="store_true",
        help="Explicit operator restore plan for orchestrator-cwd generate (PRD 362 R1)",
    )
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

    if args.core is None and args.dest is None:
        refuse_rc = refuse_orchestrator_generate(
            process_repo_root(),
            platforms,
            all_flag=bool(args.all),
            restore_plan=bool(args.restore_plan),
        )
        if refuse_rc is not None:
            return refuse_rc

    for platform in platforms:
        out = generate_platform(platform, core_root=args.core, dest_root=args.dest)
        print(f"sw generate: wrote {out}")

    # Depth-aware planning_store shims: core/ uses parents[2], dist/*/scripts/
    # uses parents[3]. Naive core→dist copy would leave dist at depth 2; refresh
    # after emit so `sw generate --all` matches build-chain-sync (phase 10 / R27).
    # Skip fixture overrides (--core/--dest) so harness temp trees stay isolated.
    if args.core is None and args.dest is None:
        shim_gen = REPO_ROOT / "scripts" / "planning_shim_gen.py"
        if shim_gen.is_file():
            shim_rc = subprocess.run(
                [sys.executable, str(shim_gen), "--root", str(REPO_ROOT), "generate"],
                cwd=str(REPO_ROOT),
                check=False,
            ).returncode
            if shim_rc != 0:
                print(
                    f"sw generate: planning_shim_gen failed (exit {shim_rc})",
                    file=sys.stderr,
                )
                return shim_rc

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
