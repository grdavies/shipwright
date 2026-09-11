#!/usr/bin/env python3
"""Validate sw-run.py documentation examples for syntax malformations (PRD 345 R18–R20)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EXIT_PASS = 0
EXIT_FAIL = 20
EXIT_ERROR = 2

FENCE_RE = re.compile(r"^```(\w*)$")
SW_RUN_LINE_RE = re.compile(
    r'sw-run\.py"\s+([^\s#]+)',
)
PLACEHOLDER_HELPER_RE = re.compile(r"^<[a-zA-Z][\w.-]*>$")
# script.py. subcommand — period glued to helper name
SCRIPT_DOT_SUBCOMMAND_RE = re.compile(r"([a-z_][\w-]*\.py)\.\s+")
# script.py<placeholder> — concatenated angle-bracket token
SCRIPT_ANGLE_PLACEHOLDER_RE = re.compile(r"([a-z_][\w-]*\.py)<[a-zA-Z][\w-]*>")
# wave_deliver help without argparse passthrough separator
WAVE_DELIVER_HELP_RE = re.compile(
    r'sw-run\.py"\s+wave_deliver\.py\s+--help\b',
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def scan_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    readme = root / "README.md"
    if readme.is_file():
        paths.append(readme)
    docs = root / "core" / "documentation"
    if docs.is_dir():
        paths.extend(sorted(docs.rglob("*.md")))
    return paths


def extract_bash_blocks(text: str) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    in_fence = False
    fence_lang = ""
    start_line = 0
    buf: list[str] = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        match = FENCE_RE.match(line.strip())
        if match:
            lang = match.group(1).lower()
            if not in_fence:
                in_fence = True
                fence_lang = lang
                start_line = lineno
                buf = []
            else:
                if fence_lang in ("", "bash", "sh", "shell", "text"):
                    blocks.append((start_line, "\n".join(buf)))
                in_fence = False
                fence_lang = ""
            continue
        if in_fence:
            buf.append(line)
    return blocks


def fence_balance_errors(text: str, rel_source: str) -> list[dict[str, str]]:
    in_fence = False
    findings: list[dict[str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not FENCE_RE.match(line.strip()):
            continue
        if not in_fence:
            in_fence = True
        else:
            in_fence = False
    if in_fence:
        findings.append(
            {
                "file": rel_source,
                "line": str(lineno),
                "reason": "unbalanced markdown code fence",
            }
        )
    return findings


def check_sw_run_line(line: str, rel_source: str, line_no: int) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if "sw-run.py" not in line:
        return findings

    for match in SCRIPT_DOT_SUBCOMMAND_RE.finditer(line):
        findings.append(
            {
                "file": rel_source,
                "line": str(line_no),
                "reason": f"concatenated helper name: {match.group(1)}. (use space before subcommand)",
            }
        )

    for match in SCRIPT_ANGLE_PLACEHOLDER_RE.finditer(line):
        findings.append(
            {
                "file": rel_source,
                "line": str(line_no),
                "reason": f"concatenated placeholder after helper: {match.group(1)}<…>",
            }
        )

    if WAVE_DELIVER_HELP_RE.search(line):
        findings.append(
            {
                "file": rel_source,
                "line": str(line_no),
                "reason": "wave_deliver.py --help requires passthrough: wave_deliver.py -- --help",
            }
        )

    for match in SW_RUN_LINE_RE.finditer(line):
        helper = match.group(1)
        if PLACEHOLDER_HELPER_RE.match(helper):
            continue
        if helper.endswith(".") or ("<" in helper and not helper.startswith("<")):
            findings.append(
                {
                    "file": rel_source,
                    "line": str(line_no),
                    "reason": f"malformed sw-run helper token: {helper}",
                }
            )
    return findings


def check_file(source: Path, root: Path) -> list[dict[str, str]]:
    rel_source = source.relative_to(root).as_posix()
    text = source.read_text(encoding="utf-8")
    findings = fence_balance_errors(text, rel_source)

    for start_line, block in extract_bash_blocks(text):
        for offset, line in enumerate(block.splitlines()):
            findings.extend(check_sw_run_line(line, rel_source, start_line + offset + 1))
    return findings


def run_check(*, root: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for path in scan_paths(root):
        findings.extend(check_file(path, root))
    verdict = "pass" if not findings else "malformed-examples"
    return {"verdict": verdict, "findings": findings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate sw-run.py documentation examples")
    parser.add_argument(
        "--root",
        type=Path,
        default=repo_root(),
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 20 when malformed examples are found (default: advisory exit 0)",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(json.dumps({"verdict": "error", "error": f"root not found: {root}"}), file=sys.stderr)
        return EXIT_ERROR

    result = run_check(root=root)
    print(json.dumps(result, separators=(",", ":")))
    if result["verdict"] == "malformed-examples" and args.strict:
        return EXIT_FAIL
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
