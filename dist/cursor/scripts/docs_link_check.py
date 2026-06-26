#!/usr/bin/env python3
"""Offline repo-relative markdown link checker (PRD 011 — R11–R13)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote

EXIT_PASS = 0
EXIT_FAIL = 20
EXIT_ERROR = 2

SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "javascript:")
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def github_heading_slug(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"[*_~]", "", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def collect_heading_slugs(content: str) -> set[str]:
    seen: dict[str, int] = defaultdict(int)
    slugs: set[str] = set()
    for line in content.splitlines():
        match = HEADING_RE.match(line)
        if not match:
            continue
        base = github_heading_slug(match.group(2))
        if not base:
            continue
        count = seen[base]
        slug = base if count == 0 else f"{base}-{count}"
        seen[base] += 1
        slugs.add(slug)
    return slugs


def normalize_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    target = re.sub(r'\s+["\'].*$', "", target)
    return unquote(target.strip())


def is_skipped_scheme(target: str) -> bool:
    lowered = target.lower()
    return any(lowered.startswith(scheme) for scheme in SKIP_SCHEMES)


def scan_files(root: Path, *, include_prds: bool) -> list[Path]:
    paths: list[Path] = []
    readme = root / "README.md"
    if readme.is_file():
        paths.append(readme)
    guides = root / "docs" / "guides"
    if guides.is_dir():
        paths.extend(sorted(guides.rglob("*.md")))
    if include_prds:
        prds = root / "docs" / "prds"
        if prds.is_dir():
            paths.extend(sorted(prds.rglob("*.md")))
    return paths


def resolve_target(source: Path, target: str, root: Path) -> tuple[Path | None, str | None, str | None]:
    if not target:
        return None, None, "empty link target"
    if target.startswith("#"):
        return source, target[1:] or None, None

    path_part, anchor = (target.split("#", 1) + [None])[:2]
    if path_part is None:
        path_part = ""
    if not path_part:
        return source, anchor, None

    candidate = (source.parent / path_part).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None, anchor, "link escapes repository root"

    if candidate.is_dir():
        return None, anchor, "target is a directory, not a file"
    if not candidate.is_file():
        return None, anchor, "file not found"
    return candidate, anchor, None


def check_anchor(target_file: Path, anchor: str | None) -> str | None:
    if not anchor:
        return None
    slugs = collect_heading_slugs(target_file.read_text(encoding="utf-8"))
    if anchor not in slugs:
        return f"heading anchor not found: #{anchor}"
    return None


def check_file(source: Path, root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    rel_source = source.relative_to(root).as_posix()
    text = source.read_text(encoding="utf-8")

    for match in LINK_RE.finditer(text):
        raw_target = normalize_target(match.group(2))
        if is_skipped_scheme(raw_target):
            continue

        target_file, anchor, resolve_error = resolve_target(source, raw_target, root)
        if resolve_error:
            findings.append(
                {
                    "file": rel_source,
                    "link": raw_target,
                    "reason": resolve_error,
                }
            )
            continue
        if target_file is None:
            findings.append(
                {
                    "file": rel_source,
                    "link": raw_target,
                    "reason": "unable to resolve link",
                }
            )
            continue

        anchor_error = check_anchor(target_file, anchor)
        if anchor_error:
            findings.append(
                {
                    "file": rel_source,
                    "link": raw_target,
                    "reason": anchor_error,
                }
            )

    return findings


def run_check(*, root: Path, include_prds: bool) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for path in scan_files(root, include_prds=include_prds):
        findings.extend(check_file(path, root))
    verdict = "pass" if not findings else "broken-links"
    return {"verdict": verdict, "findings": findings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline markdown link checker")
    parser.add_argument(
        "--root",
        type=Path,
        default=repo_root(),
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--include-prds",
        action="store_true",
        help="Also scan docs/prds/**/*.md",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 20 when broken links are found (default: advisory exit 0)",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(json.dumps({"verdict": "error", "error": f"root not found: {root}"}), file=sys.stderr)
        return EXIT_ERROR

    result = run_check(root=root, include_prds=args.include_prds)
    print(json.dumps(result, separators=(",", ":")))
    if result["verdict"] == "broken-links" and args.strict:
        return EXIT_FAIL
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
