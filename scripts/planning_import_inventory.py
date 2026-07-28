#!/usr/bin/env python3
"""Published planning_store symbol and CLI inventory (PRD 082 phase 10 / R27).

Scans script, core, distribution, and test trees for planning_store imports and CLI
surface usage; emits a versioned inventory and evaluates the compat-removal condition.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

INVENTORY_VERSION = 1
INVENTORY_SCHEMA = "planning-import-inventory/v1"
INVENTORY_REL = Path("core/sw-reference/planning-import-inventory.json")
CANONICAL_REL = "scripts/planning_store.py"

SCAN_TREES: tuple[str, ...] = (
    "scripts",
    "core",
    "dist/cursor",
    "dist/claude-code",
    "scripts/unit_tests",
)
SKIP_PARTS = frozenset({"_sw", "vendor", ".git", "__pycache__"})
MODULE_ALIAS_RE = re.compile(r"\b(?:ps|planning_store)\.([A-Za-z_][A-Za-z0-9_]*)")
FLAG_RE = re.compile(r'["\'](--[a-z0-9][a-z0-9-]*)["\']')


def repo_root(start: Path | None = None) -> Path:
    root = (start or Path.cwd()).resolve()
    if (root / CANONICAL_REL).is_file():
        return root
    raise FileNotFoundError(f"missing canonical module: {CANONICAL_REL}")


def should_skip(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def rel_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def canonical_path(root: Path) -> Path:
    path = root / CANONICAL_REL
    if not path.is_file():
        raise FileNotFoundError(f"missing canonical module: {CANONICAL_REL}")
    return path


def scan_import_sites(root: Path) -> dict[str, list[dict[str, Any]]]:
    symbols: dict[str, list[dict[str, Any]]] = {}
    for tree_rel in SCAN_TREES:
        base = root / tree_rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if should_skip(path):
                continue
            rel = rel_path(root, path)
            if rel == CANONICAL_REL:
                continue
            try:
                src = path.read_text(encoding="utf-8")
                tree = ast.parse(src, filename=rel)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "planning_store":
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        name = alias.asname or alias.name
                        symbols.setdefault(name, []).append(
                            {"file": rel, "line": node.lineno, "kind": "import-from"}
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name != "planning_store":
                            continue
                        name = alias.asname or "planning_store"
                        symbols.setdefault(name, []).append(
                            {"file": rel, "line": node.lineno, "kind": "import-module"}
                        )
            for match in MODULE_ALIAS_RE.finditer(src):
                name = match.group(1)
                line = src.count("\n", 0, match.start()) + 1
                symbols.setdefault(name, []).append(
                    {"file": rel, "line": line, "kind": "attribute-access"}
                )
    for name, sites in list(symbols.items()):
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, int, str]] = set()
        for site in sites:
            key = (site["file"], site["line"], site["kind"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(site)
        symbols[name] = sorted(deduped, key=lambda row: (row["file"], row["line"], row["kind"]))
    return symbols


def scan_cli_surface(root: Path) -> dict[str, Any]:
    src = canonical_path(root).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=CANONICAL_REL)
    subcommands: list[str] = []
    flags: set[str] = {"--root"}
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and node.target.id == "name":
            if isinstance(node.iter, ast.Tuple):
                for elt in node.iter.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        subcommands.append(elt.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "parser"
                and node.func.attr == "add_argument"
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("--"):
                        flags.add(arg.value)
    for match in FLAG_RE.finditer(src):
        flags.add(match.group(1))
    return {
        "subcommands": sorted(set(subcommands)),
        "flags": sorted(flags),
    }


def build_inventory(root: Path, *, generated_by: str | None = None) -> dict[str, Any]:
    symbols = scan_import_sites(root)
    cli = scan_cli_surface(root)
    symbol_rows = [
        {
            "name": name,
            "sites": sites,
            "siteCount": len(sites),
        }
        for name, sites in sorted(symbols.items())
    ]
    return {
        "version": INVENTORY_VERSION,
        "schema": INVENTORY_SCHEMA,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "generatedBy": generated_by or "planning_import_inventory.py",
        "canonicalModule": CANONICAL_REL,
        "trees": list(SCAN_TREES),
        "symbols": symbol_rows,
        "symbolCount": len(symbol_rows),
        "cli": cli,
    }


def evaluate_compat_removal(inventory: dict[str, Any]) -> dict[str, Any]:
    symbols = inventory.get("symbols")
    if not isinstance(symbols, list):
        raise ValueError("inventory.symbols must be a list")
    import_sites = 0
    for row in symbols:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        if name == "planning_store":
            continue
        import_sites += int(row.get("siteCount") or 0)
    removable = import_sites == 0
    return {
        "verdict": "ready" if removable else "blocked",
        "importSiteCount": import_sites,
        "removable": removable,
        "condition": "zero-inventoried-imports-across-enforced-trees",
    }


def write_inventory(root: Path, inventory: dict[str, Any]) -> Path:
    path = root / INVENTORY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    return path


def load_inventory(root: Path) -> dict[str, Any]:
    path = root / INVENTORY_REL
    if not path.is_file():
        raise FileNotFoundError(f"missing inventory: {INVENTORY_REL}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("inventory must be a JSON object")
    return data


def cmd_generate(root: Path) -> int:
    inventory = build_inventory(root)
    out = write_inventory(root, inventory)
    probe = evaluate_compat_removal(inventory)
    print(
        json.dumps(
            {
                "verdict": "pass",
                "action": "generate",
                "path": rel_path(root, out),
                "symbolCount": inventory["symbolCount"],
                "subcommandCount": len(inventory["cli"]["subcommands"]),
                "compatRemoval": probe,
            },
            indent=2,
        )
    )
    return 0


def cmd_scan(root: Path) -> int:
    inventory = build_inventory(root)
    print(
        json.dumps(
            {
                "verdict": "ok",
                "action": "scan",
                "symbolCount": inventory["symbolCount"],
                "symbols": inventory["symbols"],
                "cli": inventory["cli"],
            },
            indent=2,
        )
    )
    return 0


def cmd_compat_removal_probe(root: Path) -> int:
    inventory = load_inventory(root) if (root / INVENTORY_REL).is_file() else build_inventory(root)
    probe = evaluate_compat_removal(inventory)
    print(json.dumps({"verdict": "ok", "action": "compat-removal-probe", **probe}, indent=2))
    return 0 if probe["removable"] else 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planning_import_inventory.py")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate", help="Scan trees and write versioned inventory JSON")
    sub.add_parser("scan", help="Scan trees and print inventory (stdout JSON)")
    sub.add_parser("compat-removal-probe", help="Evaluate measurable compat-removal condition")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        root = repo_root(Path(args.root))
    except FileNotFoundError as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}), file=sys.stderr)
        return 20
    try:
        if args.cmd == "generate":
            return cmd_generate(root)
        if args.cmd == "scan":
            return cmd_scan(root)
        if args.cmd == "compat-removal-probe":
            return cmd_compat_removal_probe(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}), file=sys.stderr)
        return 20
    return 2


if __name__ == "__main__":
    run_module_main(main)
