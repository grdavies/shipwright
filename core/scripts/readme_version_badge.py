#!/usr/bin/env python3
"""README version badge sync/check against version.txt (PRD 068 R10)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BADGE_RE = re.compile(
    r"\[!\[version\]\(https://img\.shields\.io/badge/version-([^-\]]+)-blue\)\]\(version\.txt\)"
)


def read_version_txt(root: Path) -> str:
    text = (root / "version.txt").read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("version.txt is empty")
    return text


def badge_version(readme_text: str) -> str | None:
    match = BADGE_RE.search(readme_text)
    return match.group(1) if match else None


def sync_readme_badge(root: Path) -> tuple[str, str | None]:
    readme_path = root / "README.md"
    version = read_version_txt(root)
    text = readme_path.read_text(encoding="utf-8")
    previous = badge_version(text)
    if previous == version:
        return version, previous
    if previous is None:
        raise ValueError("README.md missing version badge anchor")
    updated = BADGE_RE.sub(
        f"[![version](https://img.shields.io/badge/version-{version}-blue)](version.txt)",
        text,
        count=1,
    )
    readme_path.write_text(updated, encoding="utf-8")
    return version, previous


def check_readme_badge(root: Path) -> tuple[str, str | None]:
    version = read_version_txt(root)
    readme_text = (root / "README.md").read_text(encoding="utf-8")
    badge = badge_version(readme_text)
    return version, badge


def main(argv: list[str] | None = None) -> int:
    root_parser = argparse.ArgumentParser(add_help=False)
    root_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser = argparse.ArgumentParser(description="Sync or check README version badge vs version.txt", parents=[root_parser])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="Fail when badge semver drifts from version.txt")
    sub.add_parser("sync", help="Rewrite README badge to match version.txt")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.cmd == "sync":
        version, previous = sync_readme_badge(root)
        if previous == version:
            print(f"readme-version-badge: already synced ({version})")
        else:
            print(f"readme-version-badge: synced {previous!r} -> {version!r}")
        return 0

    version, badge = check_readme_badge(root)
    if badge is None:
        print("readme-version-badge: missing badge in README.md", file=sys.stderr)
        return 1
    if badge != version:
        print(
            f"readme-version-badge: drift badge={badge!r} version.txt={version!r}",
            file=sys.stderr,
        )
        return 1
    print(f"readme-version-badge: ok ({version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
