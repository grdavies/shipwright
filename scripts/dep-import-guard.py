#!/usr/bin/env python3
"""Fail-closed import guard for undeclared non-stdlib dependencies (R12)."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

from _sw.cli import build_parser, run_module_main

if hasattr(sys, "stdlib_module_names"):
    STDLIB = set(sys.stdlib_module_names)
else:
    STDLIB = {
        "abc", "argparse", "ast", "asyncio", "base64", "collections", "contextlib",
        "copy", "csv", "dataclasses", "datetime", "email", "enum", "fnmatch", "functools",
        "glob", "hashlib", "hmac", "html", "http", "importlib", "inspect", "io", "itertools",
        "json", "logging", "math", "os", "pathlib", "pickle", "platform", "queue", "random",
        "re", "shlex", "shutil", "signal", "socket", "sqlite3", "ssl", "stat", "string",
        "struct", "subprocess", "sys", "tempfile", "textwrap", "threading", "time",
        "traceback", "types", "typing", "unicodedata", "unittest", "urllib", "uuid", "warnings",
        "weakref", "xml", "zipfile",
    }

ENFORCED_ROOTS = (
    "scripts",
    "core/scripts",
    "core/hooks",
    "core/providers",
    "sw",
)

INTERNAL_PACKAGES = {"_sw", "sw"}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_manifest(root: Path) -> dict:
    path = root / "scripts" / "_sw" / "depmanifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def top_level_module(name: str) -> str:
    return name.split(".", 1)[0]


def build_local_roots(root: Path) -> dict[str, set[str]]:
    local: dict[str, set[str]] = {}
    scripts_names: set[str] = set()
    scripts_base = root / "scripts"
    if scripts_base.is_dir():
        for path in scripts_base.rglob("*.py"):
            if "/test/" in f"/{path.relative_to(scripts_base).as_posix()}/":
                continue
            scripts_names.add(path.stem)
    for rel in ENFORCED_ROOTS:
        base = root / rel
        if not base.is_dir():
            continue
        names: set[str] = set(INTERNAL_PACKAGES) | scripts_names
        for path in base.rglob("*.py"):
            if rel == "scripts" and "/test/" in f"/{path.relative_to(base).as_posix()}/":
                continue
            names.add(path.stem)
            if path.parent.name not in {"scripts", "hooks", "providers", "test"}:
                names.add(path.parent.name)
        local[rel] = names
    return local


def iter_python_files(root: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for rel in ENFORCED_ROOTS:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if rel == "scripts" and "/test/" in f"/{path.relative_to(base).as_posix()}/":
                continue
            files.append((rel, path))
    return files


def scan_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def is_local_import(module: str, tree_rel: str, local_roots: dict[str, set[str]]) -> bool:
    top = top_level_module(module)
    if top in INTERNAL_PACKAGES:
        return True
    allowed = local_roots.get(tree_rel, set())
    if top in allowed:
        return True
    # scripts and core/scripts share the scripts module namespace
    if tree_rel in {"scripts", "core/scripts"}:
        merged = local_roots.get("scripts", set()) | local_roots.get("core/scripts", set())
        return top in merged
    return False


def check(root: Path | None = None) -> list[str]:
    root = root or repo_root()
    manifest = load_manifest(root)
    allowed = {top_level_module(x) for x in manifest.get("allowed", [])}
    vendored = {top_level_module(x) for x in manifest.get("vendored", {}).keys()}
    permitted_external = allowed | vendored
    local_roots = build_local_roots(root)
    violations: list[str] = []
    for tree_rel, path in iter_python_files(root):
        rel = path.relative_to(root).as_posix()
        for name in scan_file(path):
            mod = top_level_module(name)
            if mod in STDLIB:
                continue
            if is_local_import(name, tree_rel, local_roots):
                continue
            if mod in permitted_external:
                continue
            violations.append(f"{rel}: undeclared third-party import {name}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="dep-import-guard",
        description="Fail closed on undeclared non-stdlib Python imports (R12).",
    )
    parser.parse_args(argv)
    violations = check()
    if violations:
        for line in violations:
            print(line, file=sys.stderr)
        return 1
    print("OK dep-import-guard: no undeclared imports")
    return 0


if __name__ == "__main__":
    run_module_main(lambda: main())
