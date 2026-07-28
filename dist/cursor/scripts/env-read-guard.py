#!/usr/bin/env python3
"""AST module-boundary environment-read lint (PRD 080 R4)."""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import NamedTuple

from _sw.cli import build_parser, run_module_main

ENFORCED_TREES = (
    "scripts",
    "core/scripts",
    "core/hooks",
    "core/providers",
    "hooks",
    "dist/cursor",
    "dist/claude-code",
)

MANIFEST_REL = "scripts/_sw/env-read-exemptions.json"
GUARD_BASENAME = "env-read-guard.py"


class ExemptionManifest(NamedTuple):
    broker_paths: tuple[str, ...]
    exempt_modules: tuple[str, ...]
    allowlisted_control_variables: frozenset[str]


class EnvReadFinding(NamedTuple):
    rel_path: str
    line: int
    kind: str
    detail: str


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def manifest_path(root: Path) -> Path:
    return root / MANIFEST_REL


def load_manifest(root: Path | None = None) -> ExemptionManifest:
    path = manifest_path(root or repo_root())
    data = json.loads(path.read_text(encoding="utf-8"))
    return ExemptionManifest(
        broker_paths=tuple(str(x) for x in data.get("brokerPaths", [])),
        exempt_modules=tuple(str(x) for x in data.get("exemptModules", [])),
        allowlisted_control_variables=frozenset(str(x) for x in data.get("allowlistedControlVariables", [])),
    )


def _literal_key(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class _EnvReadAnalyzer(ast.NodeVisitor):
    def __init__(self, *, allowlisted: frozenset[str]) -> None:
        self.allowlisted = allowlisted
        self.findings: list[tuple[int, str, str]] = []
        self._os_aliases: set[str] = {"os"}
        self._environ_aliases: set[str] = set()
        self._getenv_aliases: set[str] = set()
        self._environ_expr_ids: set[int] = set()

    def _record(self, node: ast.AST, kind: str, detail: str) -> None:
        line = getattr(node, "lineno", 1) or 1
        self.findings.append((line, kind, detail))

    def _is_environ_expr(self, node: ast.expr | None) -> bool:
        if node is None:
            return False
        if id(node) in self._environ_expr_ids:
            return True
        if isinstance(node, ast.Name) and node.id in self._environ_aliases:
            return True
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            if isinstance(node.value, ast.Name) and node.value.id in self._os_aliases:
                return True
        if isinstance(node, ast.Call):
            if self._is_environ_copy_call(node):
                return True
            if self._is_dict_environ_call(node):
                return True
        return False

    def _mark_environ_expr(self, node: ast.expr) -> None:
        self._environ_expr_ids.add(id(node))

    def _allowlisted_get(self, node: ast.AST, key_node: ast.expr | None) -> bool:
        key = _literal_key(key_node) if key_node is not None else None
        return key is not None and key in self.allowlisted

    def _is_environ_copy_call(self, node: ast.Call) -> bool:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "copy":
            return self._is_environ_expr(func.value)
        return False

    def _is_dict_environ_call(self, node: ast.Call) -> bool:
        if not isinstance(node.func, ast.Name) or node.func.id != "dict":
            return False
        if not node.args:
            return False
        return self._is_environ_expr(node.args[0])

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "os":
                self._os_aliases.add(alias.asname or "os")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module != "os":
            return
        for alias in node.names:
            bound = alias.asname or alias.name
            if alias.name == "environ":
                self._environ_aliases.add(bound)
            if alias.name == "getenv":
                self._getenv_aliases.add(bound)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._is_environ_expr(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._environ_aliases.add(target.id)
                    self._mark_environ_expr(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and self._is_environ_expr(node.value):
            if isinstance(node.target, ast.Name):
                self._environ_aliases.add(node.target.id)
                self._mark_environ_expr(node.value)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id in self._os_aliases:
            self._mark_environ_expr(node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_environ_expr(node.value):
            if not self._allowlisted_get(node, node.slice):
                self._record(node, "environ-subscript", "os.environ[...] access")
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        if self._is_environ_expr(node.iter):
            self._record(node, "environ-iteration", "iteration over process environment")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func

        if isinstance(func, ast.Attribute) and func.attr == "getenv":
            if isinstance(func.value, ast.Name) and func.value.id in self._os_aliases:
                if not self._allowlisted_get(node, node.args[0] if node.args else None):
                    self._record(node, "os-getenv", "os.getenv(...)")

        if isinstance(func, ast.Name) and func.id in self._getenv_aliases:
            if not self._allowlisted_get(node, node.args[0] if node.args else None):
                self._record(node, "getenv-alias", "getenv(...) via re-export alias")

        if isinstance(func, ast.Attribute) and func.attr == "get" and self._is_environ_expr(func.value):
            key_node = node.args[0] if node.args else None
            if key_node is not None and _literal_key(key_node) is None:
                self._record(node, "environ-get-dynamic", "os.environ.get(<dynamic>)")
            elif not self._allowlisted_get(node, key_node):
                self._record(node, "environ-get", "os.environ.get(...)")

        if self._is_environ_copy_call(node):
            self._record(node, "environ-copy", "os.environ.copy()")

        if self._is_dict_environ_call(node):
            self._record(node, "dict-environ", "dict(os.environ)")

        if isinstance(node.func, ast.Attribute) and node.func.attr in {"run", "call", "Popen"}:
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                for kw in node.keywords:
                    if kw.arg == "env" and self._is_environ_expr(kw.value):
                        self._record(node, "subprocess-env-copy", "subprocess env derived from os.environ")

        if isinstance(func, ast.Attribute) and func.attr == "copy":
            if isinstance(func.value, ast.Name) and func.value.id == "copy":
                if node.args and self._is_environ_expr(node.args[0]):
                    self._record(node, "copy-environ", "copy.copy(os.environ)")

        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=False):
            if value is None:
                continue
            if key is None and self._is_environ_expr(value):
                self._record(node, "dict-unpack-environ", "{**os.environ} unpacking")
                continue
            if isinstance(value, ast.Starred) and self._is_environ_expr(value.value):
                self._record(node, "dict-unpack-environ", "{**os.environ} unpacking")
            elif self._is_environ_expr(value):
                self._record(node, "dict-literal-environ", "dict literal containing os.environ")
        self.generic_visit(node)


def _skip_path(rel_posix: str) -> bool:
    if path_has_test_segment(rel_posix):
        return True
    if "/_sw/vendor/" in f"/{rel_posix}/":
        return True
    if rel_posix.endswith(f"/{GUARD_BASENAME}"):
        return True
    return False


def path_has_test_segment(rel_posix: str) -> bool:
    return "/test/" in f"/{rel_posix}/" or "/unit_tests/" in f"/{rel_posix}/"


def is_exempt_module(rel_posix: str, manifest: ExemptionManifest) -> bool:
    if rel_posix in manifest.exempt_modules:
        return True
    for broker in manifest.broker_paths:
        if rel_posix.startswith(broker):
            return True
    return False


def iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for rel in ENFORCED_TREES:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel_posix = path.relative_to(root).as_posix()
            if _skip_path(rel_posix):
                continue
            files.append(path)
    return files


def scan_file(path: Path, *, manifest: ExemptionManifest, rel_posix: str) -> list[EnvReadFinding]:
    if is_exempt_module(rel_posix, manifest):
        return []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return []
    analyzer = _EnvReadAnalyzer(allowlisted=manifest.allowlisted_control_variables)
    analyzer.visit(tree)
    return [
        EnvReadFinding(rel_path=rel_posix, line=line, kind=kind, detail=detail)
        for line, kind, detail in analyzer.findings
    ]


def check(root: Path | None = None) -> list[EnvReadFinding]:
    root = root or repo_root()
    manifest = load_manifest(root)
    findings: list[EnvReadFinding] = []
    for path in iter_python_files(root):
        rel_posix = path.relative_to(root).as_posix()
        findings.extend(scan_file(path, manifest=manifest, rel_posix=rel_posix))
    return findings


def mode() -> str:
    return os.environ.get("SW_ENV_READ_MODE", "warn").strip().lower()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="env-read-guard",
        description="Warn/fail on process-environment reads outside the credential broker (R4).",
    )
    parser.add_argument("--mode", choices=["warn", "fail"], default=None)
    args = parser.parse_args(argv)
    active_mode = (args.mode or mode()).lower()
    findings = check()
    if not findings:
        print("OK env-read-guard: no issues")
        return 0
    for finding in findings:
        line = (
            f"{'WARN' if active_mode == 'warn' else 'FAIL'} env-read-guard: "
            f"{finding.rel_path}:{finding.line}: {finding.kind}: {finding.detail}"
        )
        print(line, file=sys.stderr)
    print(f"env-read-guard: {len(findings)} issue(s) mode={active_mode}", file=sys.stderr)
    return 0 if active_mode == "warn" else 1


if __name__ == "__main__":
    run_module_main(lambda: main())
