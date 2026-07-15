#!/usr/bin/env python3
"""README version badge check — GitHub-release shields.io SoT (PRD 069 R7)."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_OWNER = "grdavies"
DEFAULT_REPO = "shipwright"

GITHUB_RELEASE_BADGE_RE = re.compile(
    r"\[!\[[^\]]*\]\(https://img\.shields\.io/github/v/release/"
    r"([^/]+)/([^/\)]+)(?:\?[^)]*)?\)\]"
    r"\(https://github\.com/\1/\2/releases(?:/latest)?\)"
)


def github_remote_slug(root: Path) -> tuple[str, str] | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)", url)
    if not match:
        return None
    return match.group("owner"), match.group("repo")


def expected_badge_markdown(owner: str, repo: str) -> str:
    badge_url = f"https://img.shields.io/github/v/release/{owner}/{repo}"
    releases_url = f"https://github.com/{owner}/{repo}/releases"
    return f"[![GitHub release]({badge_url})]({releases_url})"


def find_github_release_badge(readme_text: str) -> re.Match[str] | None:
    return GITHUB_RELEASE_BADGE_RE.search(readme_text)


def check_readme_badge(root: Path, owner: str, repo: str) -> tuple[str, str]:
    readme_path = root / "README.md"
    if not readme_path.is_file():
        raise ValueError("README.md is missing")
    text = readme_path.read_text(encoding="utf-8")
    match = find_github_release_badge(text)
    if match is None:
        raise ValueError("README.md missing GitHub-release shields.io badge")
    found_owner, found_repo = match.group(1), match.group(2)
    if found_owner != owner or found_repo != repo:
        raise ValueError(
            f"badge targets {found_owner}/{found_repo}, expected {owner}/{repo}"
        )
    if re.search(
        r"\[!\[version\]\(https://img\.shields\.io/badge/version-[^)]+\)\]\(version\.txt\)",
        text,
    ):
        raise ValueError("README.md still uses retired version.txt static badge SoT")
    return found_owner, found_repo


def main(argv: list[str] | None = None) -> int:
    root_parser = argparse.ArgumentParser(add_help=False)
    root_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    root_parser.add_argument("--owner", default=DEFAULT_OWNER)
    root_parser.add_argument("--repo", default=DEFAULT_REPO)
    parser = argparse.ArgumentParser(
        description="Check README GitHub-release shields.io badge authority",
        parents=[root_parser],
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="Fail when README lacks GitHub-release badge SoT")
    sub.add_parser(
        "sync",
        help="Retired — GitHub-release badge is dynamic (no version.txt sync)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    owner = args.owner
    repo = args.repo
    remote = github_remote_slug(root)
    if remote is not None:
        owner, repo = remote

    if args.cmd == "sync":
        print(
            "readme-version-badge: sync retired — GitHub-release shields.io badge is authoritative",
            file=sys.stderr,
        )
        return 0

    try:
        found_owner, found_repo = check_readme_badge(root, owner, repo)
    except ValueError as exc:
        print(f"readme-version-badge: {exc}", file=sys.stderr)
        return 1
    print(f"readme-version-badge: ok ({found_owner}/{found_repo})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
