#!/usr/bin/env python3
"""Rewrite install-root documentation links for packaged dist validity (PRD 345 R15)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

# Repo-authoring prefixes (from core/documentation/) → install-root relatives.
_PREFIX_REWRITES: tuple[tuple[str, str], ...] = (
    ("../../core/commands/", "../commands/"),
    ("../../core/skills/", "../skills/"),
    ("../../core/providers/", "../providers/"),
    ("../../core/sw-reference/", "../core/sw-reference/"),
    ("../../core/hooks/", "../core/hooks/"),
    ("../../README.md", "README.md"),
    ("core/commands/", "../commands/"),
    ("core/skills/", "../skills/"),
    ("core/providers/", "../providers/"),
    ("core/sw-reference/", "../core/sw-reference/"),
)

# Targets with no install-root equivalent — unlink (keep visible text).
_STRIP_PREFIXES: tuple[str, ...] = (
    "../../INVARIANTS.md",
    "../../CAPABILITIES.md",
    "../../core/sw-reference/capability-family-matrices",
    "../../scripts/",
    "scripts/",
)


def normalize_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if "#" in target:
        path, anchor = target.split("#", 1)
        return f"{path.strip()}#{anchor.strip()}" if anchor else path.strip()
    return target


def should_strip_target(target: str) -> bool:
    path = target.split("#", 1)[0]
    return any(path.startswith(prefix) for prefix in _STRIP_PREFIXES)


def rewrite_target(target: str) -> str | None:
    normalized = normalize_target(target)
    if is_skipped_scheme(normalized):
        return normalized
    if should_strip_target(normalized):
        return None

    path, anchor = (normalized.split("#", 1) + [""])[:2]
    rewritten = path
    for old, new in _PREFIX_REWRITES:
        if rewritten.startswith(old):
            rewritten = new + rewritten[len(old) :]
            break

    if rewritten.startswith("../../"):
        return None

    if anchor:
        return f"{rewritten}#{anchor}"
    return rewritten


def is_skipped_scheme(target: str) -> bool:
    lowered = target.lower()
    return lowered.startswith(("http://", "https://", "mailto:", "tel:", "javascript:"))


def transform_markdown(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        label = match.group(1)
        raw_target = match.group(2)
        if is_skipped_scheme(raw_target.strip()):
            return match.group(0)
        new_target = rewrite_target(raw_target)
        if new_target is None:
            return label
        return f"[{label}]({new_target})"

    return LINK_RE.sub(_replace, text)


def transform_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    transformed = transform_markdown(original)
    if transformed == original:
        return False
    path.write_text(transformed, encoding="utf-8")
    return True


def transform_tree(docs_root: Path) -> dict[str, int]:
    changed = 0
    scanned = 0
    for path in sorted(docs_root.rglob("*.md")):
        if not path.is_file():
            continue
        scanned += 1
        if transform_file(path):
            changed += 1
    return {"scanned": scanned, "changed": changed}


def default_install_roots(repo: Path) -> list[Path]:
    roots: list[Path] = []
    for platform in ("cursor", "claude-code"):
        candidate = repo / "dist" / platform
        if (candidate / "documentation").is_dir():
            roots.append(candidate)
    return roots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transform install-root documentation links")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument(
        "--install-root",
        type=Path,
        action="append",
        default=[],
        help="Packaged install root (repeatable); default: dist/cursor and dist/claude-code",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read markdown from stdin and write transformed markdown to stdout",
    )
    args = parser.parse_args(argv)

    if args.stdin:
        sys.stdout.write(transform_markdown(sys.stdin.read()))
        return 0

    repo = args.root.resolve()
    install_roots = [p.resolve() for p in args.install_root] if args.install_root else default_install_roots(repo)
    if not install_roots:
        print(
            json.dumps({"verdict": "error", "error": "no install roots with documentation/ found"}),
            file=sys.stderr,
        )
        return 2

    summary: list[dict[str, int | str]] = []
    for install_root in install_roots:
        docs_root = install_root / "documentation"
        if not docs_root.is_dir():
            continue
        stats = transform_tree(docs_root)
        summary.append({"installRoot": install_root.as_posix(), **stats})

    print(json.dumps({"verdict": "pass", "roots": summary}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
