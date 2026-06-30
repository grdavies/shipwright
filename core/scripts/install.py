#!/usr/bin/env python3
"""Install Shipwright into the local Cursor plugin directory (R5).

Replaces ``install.sh`` with a stdlib mirror-copy and hook installation via R40.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from _sw import hook_launcher, logging_setup, mirror
from _sw.cli import build_parser, run_module_main


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_dest() -> Path:
    return Path.home() / ".cursor" / "plugins" / "local" / "shipwright"


def install(dest: Path, *, src: Path | None = None, install_hooks: bool = True) -> int:
    root = repo_root()
    source = src or Path(os.environ.get("SW_INSTALL_SRC", root / "dist" / "cursor"))
    if not source.is_dir():
        logging_setup.error(f"dist/cursor/ not found at {source}")
        logging_setup.error("Run: python3 -m sw generate --all")
        return 1

    version_file = root / "version.txt"
    if version_file.is_file():
        version = version_file.read_text(encoding="utf-8").strip()
        logging_setup.info(f"Installing shipwright v{version} -> {dest}")
    else:
        logging_setup.info(f"Installing shipwright -> {dest}")

    if dest.is_symlink():
        logging_setup.info(f"Removing stale symlink at {dest}")
        dest.unlink()

    dest.mkdir(parents=True, exist_ok=True)
    mirror.mirror(
        source,
        dest,
        excludes=[".git", "node_modules"],
        delete=True,
    )

    if install_hooks:
        git_hooks = dest / ".git" / "hooks"
        # Plugin install copies dist; git hooks for dev repos use core/hooks via separate path
        core_hooks = source / "core" / "hooks"
        if core_hooks.is_dir():
            for hook_name in ("pre-commit", "pre-push", "commit-msg"):
                target = core_hooks / hook_name
                if target.is_file():
                    hook_launcher.install_hook(dest / "hooks", hook_name, target, repo_root=root)

    logging_setup.info("Done. Run 'Developer: Reload Window' in Cursor to pick up changes.")

    git_config = root / ".git"
    workflow = root / ".cursor" / "workflow.config.json"
    if git_config.exists():
        if workflow.is_file():
            logging_setup.info(
                f"This git repo ({root}) already has .cursor/workflow.config.json."
            )
            logging_setup.info("Run /sw-init there to validate or refresh repo-local configuration.")
        else:
            logging_setup.info(f"Tip: you ran install inside a git repo ({root}).")
            logging_setup.info(
                "Run /sw-init in that repo to configure Shipwright for this project (opt-in)."
            )
    return 0


def build_parser_install() -> argparse.ArgumentParser:
    parser = build_parser(
        prog="install",
        description="Install Shipwright plugin copy to the Cursor plugins directory.",
    )
    parser.add_argument("dest", nargs="?", default=None, help="Destination directory")
    parser.add_argument("--no-hooks", action="store_true", help="Skip hook installation")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser_install()
    args = parser.parse_args(argv)
    dest = Path(args.dest) if args.dest else default_dest()
    return install(dest, install_hooks=not args.no_hooks)


if __name__ == "__main__":
    run_module_main(lambda: main())
