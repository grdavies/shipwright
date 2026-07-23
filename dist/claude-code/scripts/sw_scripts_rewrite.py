#!/usr/bin/env python3
"""Mechanical rewriter for consumer-capable script literals to bootstrap argv (PRD 078 TR3, R3, R7, R13).

Rewrites classified consumer-capable ``python3 scripts/<helper>`` literals to the canonical
``python3 scripts/sw_bootstrap.py <helper> [-- ARGS]`` form. Leaves ``self-repo-only`` sites
unchanged. Supports dry-run and apply modes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from sw_scripts_inventory import (
    CLASS_CONSUMER_CAPABLE,
    CLASS_SELF_REPO_ONLY,
    CONSUMER_CAPABLE_SCRIPTS,
    SCAN_SUFFIXES,
    classify_script,
    inventory_index,
    load_inventory,
    normalize_script_name,
    repo_root,
)

BOOTSTRAP_HELPER = "sw_bootstrap.py"

DEFAULT_TREE_ROOTS: tuple[str, ...] = (
    "core/commands",
    "dist/cursor/commands",
    "dist/claude-code/commands",
)

PROSE_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "before",
        "by",
        "for",
        "from",
        "if",
        "in",
        "into",
        "must",
        "never",
        "not",
        "once",
        "only",
        "or",
        "should",
        "the",
        "then",
        "to",
        "via",
        "when",
        "with",
    }
)

PYTHONPATH_INVOKE_RE = re.compile(
    r"PYTHONPATH=scripts\s+python3\s+scripts/([^\s`\"']+)",
)
DIRECT_INVOKE_RE = re.compile(
    r"python3\s+scripts/([^\s`\"']+)",
)


@dataclass(frozen=True)
class Rewrite:
    file: str
    line: int
    before: str
    after: str
    script: str


def is_consumer_capable(script: str) -> bool:
    base = Path(script).name
    if base == BOOTSTRAP_HELPER or script == BOOTSTRAP_HELPER:
        return False
    return classify_script(script) == CLASS_CONSUMER_CAPABLE


def _strip_trailing_punctuation(token: str) -> str:
    return token.rstrip(".,;)]}")


def _extract_args(segment: str, start: int, *, conservative: bool) -> tuple[str, int]:
    pos = start
    while pos < len(segment) and segment[pos].isspace():
        pos += 1
    if pos >= len(segment):
        return "", pos

    tokens: list[str] = []
    i = pos
    while i < len(segment):
        while i < len(segment) and segment[i].isspace():
            i += 1
        if i >= len(segment):
            break

        ch = segment[i]
        if ch == "`":
            break

        if ch in '"\'':
            quote = ch
            j = i + 1
            while j < len(segment) and segment[j] != quote:
                j += 1
            if j < len(segment):
                j += 1
            token = segment[i:j]
            i = j
        elif ch == "$":
            j = i + 1
            while j < len(segment) and segment[j] not in " \t`":
                j += 1
            token = segment[i:j]
            i = j
        elif ch == "<":
            j = segment.find(">", i)
            if j == -1:
                break
            token = segment[i : j + 1]
            i = j + 1
        else:
            j = i
            while j < len(segment) and segment[j] not in " \t`":
                j += 1
            token = segment[i:j]
            i = j

        bare = _strip_trailing_punctuation(token)
        if conservative and not tokens and bare.lower() in PROSE_STOP_WORDS:
            break
        if conservative and tokens and bare.lower() in PROSE_STOP_WORDS:
            break
        if conservative and not bare:
            break
        tokens.append(token)
        if conservative and i < len(segment) and segment[i] in ".,;":
            break

    return " ".join(tokens), i


def _format_bootstrap(script: str, args: str) -> str:
    normalized = normalize_script_name(Path(script).name)
    base = f"python3 scripts/{BOOTSTRAP_HELPER} {normalized}"
    args = args.strip()
    if args:
        return f"{base} -- {args}"
    return base


def _rewrite_pythonpath(segment: str, *, conservative: bool) -> tuple[str, list[Rewrite]]:
    rewrites: list[Rewrite] = []
    out: list[str] = []
    last = 0
    for match in PYTHONPATH_INVOKE_RE.finditer(segment):
        script = normalize_script_name(match.group(1))
        if not is_consumer_capable(script):
            continue
        args, end = _extract_args(segment, match.end(), conservative=conservative)
        replacement = _format_bootstrap(script, args)
        rewrites.append(
            Rewrite(
                file="",
                line=0,
                before=segment[match.start() : end],
                after=replacement,
                script=script,
            )
        )
        out.append(segment[last:match.start()])
        out.append(replacement)
        last = end
    out.append(segment[last:])
    return "".join(out), rewrites


def _rewrite_direct(segment: str, *, conservative: bool) -> tuple[str, list[Rewrite]]:
    rewrites: list[Rewrite] = []
    out: list[str] = []
    last = 0
    for match in DIRECT_INVOKE_RE.finditer(segment):
        script = normalize_script_name(match.group(1))
        if not is_consumer_capable(script):
            continue
        args, end = _extract_args(segment, match.end(), conservative=conservative)
        replacement = _format_bootstrap(script, args)
        rewrites.append(
            Rewrite(
                file="",
                line=0,
                before=segment[match.start() : end],
                after=replacement,
                script=script,
            )
        )
        out.append(segment[last:match.start()])
        out.append(replacement)
        last = end
    out.append(segment[last:])
    return "".join(out), rewrites


def rewrite_segment(segment: str, *, conservative: bool) -> tuple[str, list[Rewrite]]:
    updated, rewrites = _rewrite_pythonpath(segment, conservative=conservative)
    updated, more = _rewrite_direct(updated, conservative=conservative)
    rewrites.extend(more)
    return updated, rewrites


def rewrite_line(line: str, *, in_code_block: bool) -> tuple[str, list[Rewrite]]:
    if "`" not in line and not in_code_block:
        return rewrite_segment(line, conservative=True)

    parts = line.split("`")
    if len(parts) == 1:
        return rewrite_segment(line, conservative=not in_code_block)

    out: list[str] = []
    rewrites: list[Rewrite] = []
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            updated, part_rewrites = rewrite_segment(part, conservative=False)
        else:
            updated, part_rewrites = rewrite_segment(part, conservative=not in_code_block)
        out.append(updated)
        rewrites.extend(part_rewrites)
    return "`".join(out), rewrites


def rewrite_text(text: str) -> tuple[str, list[Rewrite]]:
    lines = text.splitlines(keepends=True)
    in_code = False
    all_rewrites: list[Rewrite] = []
    out_lines: list[str] = []

    for line_no, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code = not in_code
            out_lines.append(line)
            continue
        updated, rewrites = rewrite_line(line.rstrip("\n"), in_code_block=in_code)
        for rw in rewrites:
            all_rewrites.append(
                Rewrite(
                    file="",
                    line=line_no,
                    before=rw.before,
                    after=rw.after,
                    script=rw.script,
                )
            )
        if line.endswith("\n"):
            out_lines.append(updated + "\n")
        else:
            out_lines.append(updated)

    return "".join(out_lines), all_rewrites


def iter_tree_files(root: Path, tree_rel: str) -> Iterable[Path]:
    tree = root / tree_rel
    if not tree.is_dir():
        return
    for path in sorted(tree.rglob("*")):
        if path.is_file() and path.suffix in SCAN_SUFFIXES:
            yield path


def rewrite_file(path: Path, root: Path) -> list[Rewrite]:
    original = path.read_text(encoding="utf-8")
    updated, rewrites = rewrite_text(original)
    if updated == original:
        return []
    rel = path.relative_to(root).as_posix()
    path.write_text(updated, encoding="utf-8")
    return [
        Rewrite(file=rel, line=rw.line, before=rw.before, after=rw.after, script=rw.script)
        for rw in rewrites
    ]


def rewrite_trees(
    root: Path,
    tree_roots: Iterable[str],
    *,
    apply: bool,
) -> list[Rewrite]:
    all_rewrites: list[Rewrite] = []
    for tree_rel in tree_roots:
        for path in iter_tree_files(root, tree_rel):
            original = path.read_text(encoding="utf-8")
            updated, rewrites = rewrite_text(original)
            if updated == original:
                continue
            rel = path.relative_to(root).as_posix()
            if apply:
                path.write_text(updated, encoding="utf-8")
            all_rewrites.extend(
                Rewrite(file=rel, line=rw.line, before=rw.before, after=rw.after, script=rw.script)
                for rw in rewrites
            )
    return all_rewrites


def consumer_capable_literals_remain(root: Path, tree_roots: Iterable[str]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for tree_rel in tree_roots:
        for path in iter_tree_files(root, tree_rel):
            rel = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                for match in DIRECT_INVOKE_RE.finditer(line):
                    script = normalize_script_name(match.group(1))
                    if script == BOOTSTRAP_HELPER:
                        continue
                    if is_consumer_capable(script):
                        violations.append(
                            {
                                "file": rel,
                                "line": str(line_no),
                                "script": script,
                                "literal": match.group(0),
                            }
                        )
                for match in PYTHONPATH_INVOKE_RE.finditer(line):
                    script = normalize_script_name(match.group(1))
                    if is_consumer_capable(script):
                        violations.append(
                            {
                                "file": rel,
                                "line": str(line_no),
                                "script": script,
                                "literal": match.group(0),
                            }
                        )
    return violations


def cmd_rewrite(root: Path, *, apply: bool, trees: list[str]) -> int:
    rewrites = rewrite_trees(root, trees, apply=apply)
    remaining = consumer_capable_literals_remain(root, trees) if apply else []
    payload = {
        "verdict": "pass" if apply and not remaining else ("dry-run" if not apply else "fail"),
        "action": "apply" if apply else "dry-run",
        "rewriteCount": len(rewrites),
        "trees": trees,
        "rewrites": [
            {
                "file": rw.file,
                "line": rw.line,
                "script": rw.script,
                "before": rw.before,
                "after": rw.after,
            }
            for rw in rewrites[:200]
        ],
        "remainingConsumerLiterals": remaining[:50],
    }
    if apply and remaining:
        payload["verdict"] = "fail"
        payload["reason"] = "consumer-capable-direct-literals-remain"
    print(json.dumps(payload, indent=2))
    return 0 if payload["verdict"] in {"pass", "dry-run"} else 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sw_scripts_rewrite.py")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="cmd", required=True)
    dry = sub.add_parser("dry-run", help="Print planned rewrites without writing files")
    apply = sub.add_parser("apply", help="Rewrite files in place")
    for p in (dry, apply):
        p.add_argument(
            "--tree",
            action="append",
            default=[],
            help="Tree root to rewrite (repeatable; default: command trees)",
        )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = repo_root(Path(args.root))
    trees = args.tree or list(DEFAULT_TREE_ROOTS)
    try:
        if args.cmd == "dry-run":
            return cmd_rewrite(root, apply=False, trees=trees)
        if args.cmd == "apply":
            return cmd_rewrite(root, apply=True, trees=trees)
    except (OSError, ValueError) as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}), file=sys.stderr)
        return 20
    return 2


if __name__ == "__main__":
    run_module_main(main)
