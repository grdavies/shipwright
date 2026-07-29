#!/usr/bin/env python3
"""Backend write entry-point lint — no substituted backend ids (PRD 082 phase 4 / R26)."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

BACKEND_WRITE_ENTRY_POINTS: dict[str, dict[str, object]] = {
    "record_backend_write": {"backend_arg": 0, "configured_kw": "configured"},
    "apply_write_disposition": {"backend_kw": "target_backend", "configured_attr": "configured"},
}

LINT_SKIP_PREFIXES = (
    "scripts/unit_tests/",
    "scripts/test/",
    "scripts/_sw/vendor/",
    "scripts/fixture_backend_write_lint/",
)

LINT_SKIP_FILES = frozenset(
    {
        "planning_backend_write_lint.py",
        "planning_authority.py",
    }
)

SAFE_BACKEND_EXPRS = frozenset(
    {
        "decision.configured",
        "configured",
        "decision.configured",
        "target_backend",
        "None",
    }
)


@dataclass(frozen=True)
class LintFinding:
    file: str
    line: int
    entry_point: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "entryPoint": self.entry_point,
            "detail": self.detail,
        }


def _expr_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expr_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return repr(node.value)
    return None


def _is_safe_backend_expr(node: ast.expr | None) -> bool:
    if node is None:
        return True
    name = _expr_name(node)
    if name in SAFE_BACKEND_EXPRS:
        return True
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.Attribute) and node.attr == "configured":
        return True
    return False


def _scan_call(node: ast.Call, *, rel: str) -> list[LintFinding]:
    func_name: str | None = None
    if isinstance(node.func, ast.Name):
        func_name = node.func.id
    elif isinstance(node.func, ast.Attribute):
        func_name = node.func.attr
    if not func_name or func_name not in BACKEND_WRITE_ENTRY_POINTS:
        return []

    spec = BACKEND_WRITE_ENTRY_POINTS[func_name]
    findings: list[LintFinding] = []

    if "backend_arg" in spec:
        index = int(spec["backend_arg"])
        if len(node.args) > index:
            arg = node.args[index]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                findings.append(
                    LintFinding(
                        file=rel,
                        line=node.lineno,
                        entry_point=func_name,
                        detail=f"literal backend id {arg.value!r} at positional arg {index}",
                    )
                )
            elif not _is_safe_backend_expr(arg):
                name = _expr_name(arg) or type(arg).__name__
                if name not in SAFE_BACKEND_EXPRS:
                    findings.append(
                        LintFinding(
                            file=rel,
                            line=node.lineno,
                            entry_point=func_name,
                            detail=f"non-configured backend expression {name!r}",
                        )
                    )

    configured_kw = str(spec.get("configured_kw") or "")
    if configured_kw:
        for kw in node.keywords:
            if kw.arg != configured_kw:
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                for other in node.args:
                    if isinstance(other, ast.Constant) and isinstance(other.value, str):
                        if other.value != kw.value.value:
                            findings.append(
                                LintFinding(
                                    file=rel,
                                    line=node.lineno,
                                    entry_point=func_name,
                                    detail=(
                                        f"backend id {other.value!r} != configured "
                                        f"{kw.value.value!r}"
                                    ),
                                )
                            )
    backend_kw = str(spec.get("backend_kw") or "")
    if backend_kw:
        for kw in node.keywords:
            if kw.arg == backend_kw and not _is_safe_backend_expr(kw.value):
                name = _expr_name(kw.value) or type(kw.value).__name__
                findings.append(
                    LintFinding(
                        file=rel,
                        line=node.lineno,
                        entry_point=func_name,
                        detail=f"substituted target_backend expression {name!r}",
                    )
                )
    return findings


def scan_file(path: Path, *, rel: str) -> list[LintFinding]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    findings: list[LintFinding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            findings.extend(_scan_call(node, rel=rel))
    return findings


def lint_repo(repo_root: Path) -> dict[str, object]:
    scripts_dir = repo_root / "scripts"
    findings: list[LintFinding] = []
    if not scripts_dir.is_dir():
        return {"verdict": "pass", "findings": []}
    for path in sorted(scripts_dir.rglob("*.py")):
        rel = path.relative_to(repo_root).as_posix()
        if any(rel.startswith(prefix) for prefix in LINT_SKIP_PREFIXES):
            continue
        if path.name in LINT_SKIP_FILES:
            continue
        findings.extend(scan_file(path, rel=rel))
    payload: dict[str, object] = {
        "verdict": "pass" if not findings else "fail",
        "findings": [item.to_dict() for item in findings],
        "entryPoints": sorted(BACKEND_WRITE_ENTRY_POINTS),
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint planning backend write entry points")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true", help="Exit non-zero on findings")
    args = parser.parse_args(argv)
    result = lint_repo(args.root.resolve())
    print(json.dumps(result, indent=2))
    if args.check and result.get("verdict") != "pass":
        return 20
    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
