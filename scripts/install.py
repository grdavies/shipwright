#!/usr/bin/env python3
"""Install Shipwright into a host integration plugin directory (R5, PRD 338 R29).

Replaces ``install.sh`` with a stdlib mirror-copy and hook installation via R40.
Supports Cursor and Claude Code targets with comparable mirror/refresh semantics.

PRD 342 R18: ``shipwright init --integration <tool>`` chains machine-level
mirroring then repository configuration through this module and ``sw-configure``
— no parallel installation path.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from _sw import hook_launcher, logging_setup, mirror
from _sw.cli import build_parser, run_module_main

# Keep in sync with memory_provider_catalog.CATALOG_* (hook trust after install).
_CATALOG_EMIT_REL = Path("core/sw-reference/memory-provider-catalog.json")
_CATALOG_SW_REL = Path(".sw/memory-provider-catalog.json")

# Integration id → dist tree under the Shipwright source / package root (R18).
INTEGRATION_DIST: dict[str, str] = {
    "cursor": "dist/cursor",
    "claude-code": "dist/claude-code",
}

# Paths preserved across refresh — operator-owned state under the machine install root.
USER_OWNED_INSTALL_PREFIXES: tuple[str, ...] = (".sw/local",)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def plugin_root_env_for(integration: str) -> str:
    norm = normalize_integration(integration)
    return "CURSOR_PLUGIN_ROOT" if norm == "cursor" else "CLAUDE_PLUGIN_ROOT"


def package_root(integration: str = "cursor") -> Path:
    """Resolve the Shipwright source tree or packaged install root."""
    norm = normalize_integration(integration)
    env_val = os.environ.get(plugin_root_env_for(norm), "").strip()
    if env_val:
        return Path(env_val).expanduser().resolve()
    return repo_root()


def is_packaged_install_root(root: Path, integration: str) -> bool:
    """True when ``root`` is already an emitted platform dist tree."""
    norm = normalize_integration(integration)
    resolved = root.resolve()
    if norm == "cursor":
        return (resolved / ".cursor-plugin" / "plugin.json").is_file()
    return (resolved / ".claude-plugin" / "plugin.json").is_file()


def mirror_excludes() -> list[str]:
    return [".git", "node_modules", *USER_OWNED_INSTALL_PREFIXES]


def _preserve_user_owned(dest: Path) -> dict[str, bytes]:
    preserved: dict[str, bytes] = {}
    if not dest.is_dir():
        return preserved
    for prefix in USER_OWNED_INSTALL_PREFIXES:
        base = dest / prefix
        if not base.exists():
            continue
        if base.is_file():
            preserved[prefix] = base.read_bytes()
            continue
        for path in base.rglob("*"):
            if path.is_file():
                rel = path.relative_to(dest).as_posix()
                preserved[rel] = path.read_bytes()
    return preserved


def _restore_user_owned(dest: Path, preserved: dict[str, bytes]) -> None:
    for rel, content in preserved.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def default_dest() -> Path:
    return Path.home() / ".cursor" / "plugins" / "local" / "shipwright"


def normalize_integration(integration: str) -> str:
    key = integration.strip().lower().replace("_", "-")
    if key in {"cursor", "cursor-ide", "cursor-plugin"}:
        return "cursor"
    if key in {"claude-code", "claude", "anthropic"}:
        return "claude-code"
    raise ValueError(f"unsupported integration: {integration}")


def default_dest_for(integration: str) -> Path:
    """Declared machine install root for an integration (R22 machine scope)."""
    norm = normalize_integration(integration)
    if norm == "cursor":
        return default_dest()
    return Path.home() / ".claude" / "plugins" / "local" / "shipwright"


def dist_source_for(integration: str, *, root: Path | None = None) -> Path:
    norm = normalize_integration(integration)
    root = (root or package_root(norm)).resolve()
    nested = root / INTEGRATION_DIST[norm]
    if nested.is_dir():
        return nested
    if is_packaged_install_root(root, norm):
        return root
    return nested


def plan_machine_write_paths(source: Path, dest: Path) -> list[str]:
    """Enumerate every destination path a mirror would write (R22 machine scope)."""
    paths: list[str] = []
    if not source.is_dir():
        return paths
    skip = {".git", "node_modules", "__pycache__"}
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        if any(part in skip for part in rel.parts):
            continue
        paths.append(str((dest / rel).resolve()))
    if (source / _CATALOG_EMIT_REL).is_file():
        catalog = str((dest / _CATALOG_SW_REL).resolve())
        if catalog not in paths:
            paths.append(catalog)
    return sorted(set(paths))


def _load_sw_configure():
    """Load hyphenated ``sw-configure.py`` without inventing a parallel module."""
    path = Path(__file__).resolve().parent / "sw-configure.py"
    name = "sw_configure_packaged"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def init_packaged(
    *,
    integration: str,
    repo: Path,
    dest: Path | None = None,
    source_root: Path | None = None,
    accept_ci_stub: bool = True,
    dry_run: bool = False,
    install_hooks: bool = False,
) -> dict[str, Any]:
    """Chain machine mirror then repository configure (R18).

    Reuses ``install`` + ``sw-configure`` — no parallel installation path.
    """
    configure = _load_sw_configure()
    source_root = source_root or repo_root()
    norm = normalize_integration(integration)
    machine_dest = (dest or default_dest_for(norm)).expanduser().resolve()
    dist_src = dist_source_for(norm, root=source_root)
    repo = repo.expanduser().resolve()

    scope = configure.enumerate_write_scope(
        repo,
        integration=norm,
        machine_dest=machine_dest,
        dist_source=dist_src,
        accept_ci_stub=accept_ci_stub,
    )

    if dry_run:
        return {
            "verdict": "pass",
            "action": "dry-run",
            "integration": norm,
            "scope": scope,
            "wrote": False,
        }

    if not dist_src.is_dir():
        return {
            "verdict": "fail",
            "action": "init",
            "error": "dist-missing",
            "message": f"integration dist not found at {dist_src}",
            "remediation": "python3 -m sw generate --all",
            "scope": scope,
        }

    rc = install(
        machine_dest,
        src=dist_src,
        integration=norm,
        install_hooks=install_hooks,
    )
    if rc != 0:
        return {
            "verdict": "fail",
            "action": "init",
            "error": "machine-install-failed",
            "exitCode": rc,
            "scope": scope,
        }

    configure_result = configure.apply_packaged_configure(
        repo,
        accept_ci_stub=accept_ci_stub,
    )
    if configure_result.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "action": "init",
            "error": "repo-configure-failed",
            "configure": configure_result,
            "scope": scope,
        }

    return {
        "verdict": "pass",
        "action": "init",
        "integration": norm,
        "machineDest": str(machine_dest),
        "repo": str(repo),
        "scope": scope,
        "configure": configure_result,
        "wrote": True,
    }


def _is_externally_managed() -> bool:
    """Detect PEP 668 externally managed environment (e.g., Homebrew Python on macOS)."""
    import sysconfig
    stdlib = Path(sysconfig.get_path("stdlib"))
    marker = stdlib / "EXTERNALLY-MANAGED"
    return marker.is_file()


def install_console(*, root: Path | None = None) -> int:
    """Install editable ``shipwright`` console from a source checkout (PRD 345 R9).

    Handles PEP 668 externally managed environments by using --user or providing
    guidance on using uv/pipx.
    """
    root = (root or repo_root()).resolve()
    if not (root / "pyproject.toml").is_file():
        return 0
    if os.environ.get("SW_SKIP_CONSOLE_INSTALL", "").strip().lower() in ("1", "true", "yes"):
        return 0

    # Try standard editable install first
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", "."],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        logging_setup.info("Installed shipwright console entry point (editable).")
        return 0

    # Check if this is a PEP 668 failure (externally managed environment)
    if _is_externally_managed() or "externally-managed" in proc.stderr.lower():
        logging_setup.warning(
            "PEP 668 externally managed environment detected (e.g., Homebrew Python)."
        )
        logging_setup.info("Trying pip install --user -e . ...")

        # Try --user install
        proc_user = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "-e", "."],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if proc_user.returncode == 0:
            logging_setup.info("Installed shipwright console entry point (editable, --user).")
            logging_setup.info(
                "Note: Ensure ~/.local/bin is in your PATH for the 'shipwright' command."
            )
            return 0

        # --user also failed — provide guidance
        logging_setup.error("Console install failed in externally managed environment.")
        logging_setup.info("")
        logging_setup.info("Recommended alternatives for contributors:")
        logging_setup.info("  1. Use a virtual environment:")
        logging_setup.info("       python3 -m venv .venv && source .venv/bin/activate")
        logging_setup.info("       pip install -e .")
        logging_setup.info("  2. Use pipx for editable development:")
        logging_setup.info("       pipx install --editable .")
        logging_setup.info("  3. Skip console install and use scripts directly:")
        logging_setup.info("       export SW_SKIP_CONSOLE_INSTALL=1")
        logging_setup.info("       python3 scripts/install.py")
        logging_setup.info("")
        return proc_user.returncode

    # Non-PEP-668 failure
    logging_setup.error(proc.stderr or proc.stdout or "console install failed")
    return proc.returncode


def seed_memory_provider_catalog(dest: Path) -> bool:
    """Ensure plugin installs expose the catalog under `.sw/` for hook validation.

    Dist mirrors ``core/sw-reference/``; hooks historically resolve
    ``.sw/memory-provider-catalog.json``. Seed that path from the emit mirror when present.
    """
    emit = dest / _CATALOG_EMIT_REL
    if not emit.is_file():
        return False
    target = dest / _CATALOG_SW_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(emit, target)
    return True


def install(
    dest: Path,
    *,
    src: Path | None = None,
    integration: str = "cursor",
    install_hooks: bool = True,
) -> int:
    norm = normalize_integration(integration)
    root = package_root(norm)
    if src is not None:
        source = src
    elif os.environ.get("SW_INSTALL_SRC"):
        source = Path(os.environ["SW_INSTALL_SRC"])
    else:
        source = dist_source_for(norm, root=root)

    if not source.is_dir():
        logging_setup.error(f"dist/{norm}/ not found at {source}")
        logging_setup.error("Run: python3 -m sw generate --all")
        return 1

    version_file = source / "version.txt"
    if not version_file.is_file():
        version_file = root / "version.txt"
    if version_file.is_file():
        version = version_file.read_text(encoding="utf-8").strip()
        logging_setup.info(f"Installing shipwright ({norm}) v{version} -> {dest}")
    else:
        logging_setup.info(f"Installing shipwright ({norm}) -> {dest}")

    if dest.is_symlink():
        logging_setup.info(f"Removing stale symlink at {dest}")
        dest.unlink()

    dest.mkdir(parents=True, exist_ok=True)
    preserved = _preserve_user_owned(dest)
    # Mirror unlinks destination-entry symlinks before copy so a leftover
    # scripts/ (or nested) symlink cannot redirect the install into another repo.
    mirror.mirror(
        source,
        dest,
        excludes=mirror_excludes(),
        delete=True,
    )
    _restore_user_owned(dest, preserved)

    if seed_memory_provider_catalog(dest):
        logging_setup.info("Seeded .sw/memory-provider-catalog.json from core/sw-reference emit.")
    else:
        logging_setup.warning(
            "memory-provider-catalog.json missing from dist emit; "
            "hook trust may fail until generate includes core/sw-reference/memory-provider-catalog.json"
        )

    if install_hooks:
        # Plugin install copies dist; git hooks for dev repos use core/hooks via separate path
        core_hooks = source / "core" / "hooks"
        if core_hooks.is_dir():
            for hook_name in ("pre-commit.py", "pre-push.py", "commit-msg.py"):
                target = core_hooks / hook_name
                if target.is_file():
                    hook_launcher.install_hook(
                        dest / "hooks",
                        hook_name.removesuffix(".py"),
                        target,
                        repo_root=root,
                    )

    if norm == "cursor":
        logging_setup.info("Done. Run 'Developer: Reload Window' in Cursor to pick up changes.")
    else:
        logging_setup.info("Done. Restart Claude Code to pick up plugin changes.")

    git_config = root / ".git"
    workflow = root / ".cursor" / "workflow.config.json"
    if git_config.exists():
        if workflow.is_file():
            logging_setup.info(
                # shipwright-paths-exclusion: operator-facing message names legacy path during redirect window
                f"This git repo ({root}) already has .cursor/workflow.config.json."
            )
            logging_setup.info("Run /sw-init there to validate or refresh repo-local configuration.")
        else:
            logging_setup.info(f"Tip: you ran install inside a git repo ({root}).")
            logging_setup.info(
                "Run /sw-init in that repo to configure Shipwright for this project (opt-in)."
            )

    console_rc = install_console(root=repo_root())
    if console_rc != 0:
        return console_rc
    return 0


def build_parser_install() -> argparse.ArgumentParser:
    parser = build_parser(
        prog="install",
        description="Install Shipwright plugin copy to a host integration plugin directory.",
    )
    parser.add_argument("dest", nargs="?", default=None, help="Destination directory")
    parser.add_argument(
        "--integration",
        default="cursor",
        choices=["cursor", "claude-code"],
        help="Target host integration (default: cursor)",
    )
    parser.add_argument("--no-hooks", action="store_true", help="Skip hook installation")
    return parser


def build_parser_init() -> argparse.ArgumentParser:
    parser = build_parser(
        prog="shipwright init",
        description=(
            "Machine mirror then repository configure for one integration (PRD 342 R18)."
        ),
    )
    parser.add_argument(
        "--integration",
        required=True,
        help="Host integration to enable (cursor | claude-code)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Repository root to configure (default: cwd)",
    )
    parser.add_argument(
        "--dest",
        default=None,
        help="Override machine install root (tests / non-default layouts)",
    )
    parser.add_argument(
        "--source-root",
        default=None,
        help="Shipwright source/package root providing dist/<integration>/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Enumerate repo-scope and machine-scope writes without writing",
    )
    parser.add_argument(
        "--no-ci-stub",
        action="store_true",
        help="Skip operator-accepted CI stub write",
    )
    parser.add_argument(
        "--install-hooks",
        action="store_true",
        help="Also install git hooks into the machine dest (dev installs)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser_install()
    args = parser.parse_args(argv)
    dest = Path(args.dest) if args.dest else default_dest_for(args.integration)
    return install(
        dest,
        integration=args.integration,
        install_hooks=not args.no_hooks,
    )


def main_init(argv: list[str] | None = None) -> int:
    parser = build_parser_init()
    args = parser.parse_args(argv)
    try:
        result = init_packaged(
            integration=args.integration,
            repo=Path(args.repo) if args.repo else Path.cwd(),
            dest=Path(args.dest) if args.dest else None,
            source_root=Path(args.source_root) if args.source_root else None,
            accept_ci_stub=not args.no_ci_stub,
            dry_run=args.dry_run,
            install_hooks=args.install_hooks,
        )
    except ValueError as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "pass" else 1


if __name__ == "__main__":
    run_module_main(lambda: main())
