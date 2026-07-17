#!/usr/bin/env python3
"""Trusted mutation wrapper — enforces memory-prework before tracked-file writes (PRD 072 R8, KD7)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
HOOKS_DIR = SCRIPT_DIR.parent / "core" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

from memory_prework_gate import (  # noqa: E402
    consume_mutation,
    load_record,
    validate_fresh_record,
)

_SHELL_REDIRECT_RE = re.compile(
    r"(?:^|[\s;|&])(?:\d?>>?)\s*([^\s;|&]+)"
)
_SHELL_TEE_RE = re.compile(r"\btee\b(?:\s+-[a-zA-Z]+)*\s+([^\s;|&]+)")
_SHELL_SED_INPLACE_RE = re.compile(r"\bsed\s+-[^ \t]*i[^ \t]*\b")
_SHELL_PYTHON_WRITE_RE = re.compile(
    r"""(?:open\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"][wa]['"]|"""
    r"""Path\s*\(\s*['"]([^'"]+)['"]\s*\)\.write)""",
    re.IGNORECASE,
)
_SHELL_MV_CP_RM_RE = re.compile(r"\b(mv|cp|rm)\b(?:\s+-[a-zA-Z]+)*\s+([^\s;|&]+)")


@dataclass(frozen=True)
class PreworkVerdict:
    verdict: str  # pass | fail
    cause: str | None = None
    remediation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"verdict": self.verdict}
        if self.cause:
            out["cause"] = self.cause
        if self.remediation:
            out["remediation"] = self.remediation
        return out


def git_toplevel(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ValueError("not a git repository")
    return Path(proc.stdout.strip()).resolve()


def is_git_tracked(root: Path, rel: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", rel],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def resolve_repo_path(root: Path, raw: str) -> tuple[Path | None, str | None]:
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            rel = candidate.resolve().relative_to(root)
        except ValueError:
            return None, None
    else:
        rel = Path(raw)
    rel_posix = rel.as_posix()
    if rel_posix.startswith("../") or rel_posix == "..":
        return None, None
    return root / rel, rel_posix


def validate_prework_for_mutation(root: Path) -> PreworkVerdict:
    cause = validate_fresh_record(load_record(root))
    if cause:
        return PreworkVerdict(
            verdict="fail",
            cause=cause,
            remediation=(
                "run pre-work memory search and record before mutation: "
                "python3 scripts/wave.py memory prework record --surface <sw-command> "
                "[--scope paths] [--hit-count N]"
            ),
        )
    return PreworkVerdict(verdict="pass")


def _candidate_paths_from_shell(command: str) -> list[str]:
    paths: list[str] = []
    for match in _SHELL_REDIRECT_RE.finditer(command):
        paths.append(match.group(1).strip("\"'"))
    for match in _SHELL_TEE_RE.finditer(command):
        paths.append(match.group(1).strip("\"'"))
    for match in _SHELL_PYTHON_WRITE_RE.finditer(command):
        for group in match.groups():
            if group:
                paths.append(group.strip("\"'"))
    for match in _SHELL_MV_CP_RM_RE.finditer(command):
        paths.append(match.group(2).strip("\"'"))
    if _SHELL_SED_INPLACE_RE.search(command):
        tokens = re.split(r"\s+", command)
        if tokens:
            paths.append(tokens[-1].strip("\"'"))
    return paths


def shell_tracked_mutation_cause(command: str, root: Path) -> str | None:
    """Return a machine cause when Shell would mutate a tracked file; else None."""
    if not command.strip():
        return None
    for raw in _candidate_paths_from_shell(command):
        _abs, rel = resolve_repo_path(root, raw)
        if rel and is_git_tracked(root, rel):
            return "shell-tracked-mutation-unsupported"
    return None


def _read_content(args: argparse.Namespace) -> str:
    if args.content is not None:
        return args.content
    if args.content_file is not None:
        return Path(args.content_file).read_text(encoding="utf-8")
    raise ValueError("write requires --content or --content-file")


def apply_write(root: Path, rel: str, content: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def apply_str_replace(root: Path, rel: str, old: str, new: str) -> None:
    target = root / rel
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise ValueError(f"old_string not found in {rel}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def apply_delete(root: Path, rel: str) -> None:
    target = root / rel
    if target.is_file():
        target.unlink()


def cmd_apply(root: Path, action: str, **kwargs: Any) -> dict[str, Any]:
    prework = validate_prework_for_mutation(root)
    if prework.verdict != "pass":
        return prework.to_dict()

    rel = str(kwargs.get("path") or "")
    if not rel:
        return {"verdict": "fail", "cause": "missing-path"}
    if not is_git_tracked(root, rel):
        return {
            "verdict": "fail",
            "cause": "path-not-tracked",
            "remediation": "sw_mutate applies only to git-tracked paths",
        }

    try:
        if action == "write":
            apply_write(root, rel, str(kwargs.get("content") or ""))
        elif action == "str-replace":
            apply_str_replace(
                root,
                rel,
                str(kwargs.get("old_string") or ""),
                str(kwargs.get("new_string") or ""),
            )
        elif action == "delete":
            apply_delete(root, rel)
        else:
            return {"verdict": "fail", "cause": f"unknown-action:{action}"}
    except (OSError, ValueError) as exc:
        return {"verdict": "fail", "cause": "mutation-failed", "error": str(exc)}

    consume_mutation(root)
    return {"verdict": "pass", "action": action, "path": rel}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shipwright trusted mutation wrapper (PRD 072 R8)")
    sub = parser.add_subparsers(dest="command", required=True)

    write_p = sub.add_parser("write", help="Write content to a tracked file")
    write_p.add_argument("--path", required=True)
    write_p.add_argument("--content")
    write_p.add_argument("--content-file")

    replace_p = sub.add_parser("str-replace", help="Replace once in a tracked file")
    replace_p.add_argument("--path", required=True)
    replace_p.add_argument("--old", dest="old_string", required=True)
    replace_p.add_argument("--new", dest="new_string", required=True)

    delete_p = sub.add_parser("delete", help="Delete a tracked file")
    delete_p.add_argument("--path", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        root = git_toplevel(Path.cwd())
    except ValueError:
        print(json.dumps({"verdict": "fail", "cause": "not-a-git-repository"}))
        return 2

    if args.command == "write":
        try:
            content = _read_content(args)
        except ValueError as exc:
            print(json.dumps({"verdict": "fail", "cause": str(exc)}))
            return 2
        result = cmd_apply(root, "write", path=args.path, content=content)
    elif args.command == "str-replace":
        result = cmd_apply(
            root,
            "str-replace",
            path=args.path,
            old_string=args.old_string,
            new_string=args.new_string,
        )
    elif args.command == "delete":
        result = cmd_apply(root, "delete", path=args.path)
    else:
        result = {"verdict": "fail", "cause": f"unknown-command:{args.command}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
