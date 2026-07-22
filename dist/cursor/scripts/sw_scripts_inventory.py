#!/usr/bin/env python3
"""Versioned call-site inventory for shipped helper literals (PRD 078 TR9, R7, KD6).

Scans command/skill/reference/hook/CI/guide trees (and dist mirrors), classifies each
``python3 scripts/<helper>`` literal as ``self-repo-only`` or ``consumer-capable``,
and emits a closed inventory artifact for ``check_scripts_inventory.py``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

INVENTORY_VERSION = 1
INVENTORY_SCHEMA = "scripts-call-site-inventory/v1"
INVENTORY_REL = Path("core/sw-reference/scripts-call-site-inventory.json")

SCAN_TREE_ROOTS: tuple[str, ...] = (
    "core/commands",
    "core/skills",
    "core/providers",
    "core/rules",
    "core/sw-reference",
    "core/hooks",
    "docs/guides",
    ".github/workflows",
    "dist/cursor/commands",
    "dist/cursor/skills",
    "dist/claude-code/commands",
    "dist/claude-code/skills",
)

SCAN_SUFFIXES = frozenset({".md", ".mdc", ".py", ".yml", ".yaml"})

CLASS_SELF_REPO_ONLY = "self-repo-only"
CLASS_CONSUMER_CAPABLE = "consumer-capable"
VALID_CLASSIFICATIONS = frozenset({CLASS_SELF_REPO_ONLY, CLASS_CONSUMER_CAPABLE})

SCRIPT_LITERAL_RE = re.compile(
    r"(?:^|[^\w])python3\s+scripts/([^\s`\"']+)",
    re.MULTILINE,
)
PYTHONPATH_LITERAL_RE = re.compile(
    r"PYTHONPATH=scripts\s+python3\s+scripts/([^\s`\"']+)",
    re.MULTILINE,
)

# Helpers that must remain invocable from consumer workspaces (bootstrap migration targets).
CONSUMER_CAPABLE_SCRIPTS = frozenset(
    {
        "context_compress.py",
        "doctor.py",
        "git-push.py",
        "host.py",
        "init_scripts_facade.py",
        "memory-preflight.py",
        "memory-redact.py",
        "memory_redact.py",
        "planning-init-seed.py",
        "planning_gap_capture.py",
        "reconcile-status.py",
        "resolve-model-tier.py",
        "sw_scripts_resolve.py",
        "sw-tmp.py",
    }
)

DIST_CORE_PAIRS: tuple[tuple[str, str], ...] = (
    ("dist/cursor/commands", "core/commands"),
    ("dist/claude-code/commands", "core/commands"),
    ("dist/cursor/skills", "core/skills"),
    ("dist/claude-code/skills", "core/skills"),
)


@dataclass(frozen=True)
class CallSite:
    file: str
    line: int
    column: int
    literal: str
    script: str
    tree: str

    @property
    def entry_id(self) -> str:
        return f"{self.file}:{self.line}:{self.script}"

    def to_inventory_entry(self, classification: str) -> dict[str, Any]:
        return {
            "id": self.entry_id,
            "tree": self.tree,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "literal": self.literal,
            "script": self.script,
            "classification": classification,
        }


def repo_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def normalize_script_name(raw: str) -> str:
    name = raw.strip().rstrip(")`.,;")
    if not name.endswith(".py") and "/" not in name:
        name = f"{name}.py"
    return name


def extract_literals(text: str) -> list[tuple[int, int, str, str]]:
    """Return (line, column, literal, script) tuples from file text."""
    hits: list[tuple[int, int, str, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in SCRIPT_LITERAL_RE.finditer(line):
            script = normalize_script_name(match.group(1))
            hits.append((line_no, match.start(1) - len("scripts/"), match.group(0).strip(), script))
        for match in PYTHONPATH_LITERAL_RE.finditer(line):
            script = normalize_script_name(match.group(1))
            literal = match.group(0).strip()
            hits.append((line_no, line.find(literal), literal, script))
    return hits


def classify_script(script: str) -> str:
    base = Path(script).name
    if base in CONSUMER_CAPABLE_SCRIPTS or script in CONSUMER_CAPABLE_SCRIPTS:
        return CLASS_CONSUMER_CAPABLE
    return CLASS_SELF_REPO_ONLY


def iter_scan_files(root: Path, tree_rel: str) -> Iterable[Path]:
    tree = root / tree_rel
    if not tree.is_dir():
        return
    for path in sorted(tree.rglob("*")):
        if path.is_file() and path.suffix in SCAN_SUFFIXES:
            yield path


def scan_tree(root: Path, tree_rel: str) -> list[CallSite]:
    sites: list[CallSite] = []
    for path in iter_scan_files(root, tree_rel):
        rel_file = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"parse error: {rel_file}: {exc}") from exc
        for line_no, column, literal, script in extract_literals(text):
            sites.append(
                CallSite(
                    file=rel_file,
                    line=line_no,
                    column=column,
                    literal=literal,
                    script=script,
                    tree=tree_rel,
                )
            )
    return sites


def scan_all(root: Path) -> list[CallSite]:
    sites: list[CallSite] = []
    for tree_rel in SCAN_TREE_ROOTS:
        sites.extend(scan_tree(root, tree_rel))
    return sites


def build_inventory(root: Path, *, generated_by: str | None = None) -> dict[str, Any]:
    sites = scan_all(root)
    entries = [
        site.to_inventory_entry(classify_script(site.script))
        for site in sorted(sites, key=lambda s: (s.file, s.line, s.script))
    ]
    return {
        "version": INVENTORY_VERSION,
        "schema": INVENTORY_SCHEMA,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "generatedBy": generated_by or "sw_scripts_inventory.py",
        "trees": list(SCAN_TREE_ROOTS),
        "entries": entries,
    }


def load_inventory(root: Path) -> dict[str, Any]:
    path = root / INVENTORY_REL
    if not path.is_file():
        raise FileNotFoundError(f"missing inventory: {INVENTORY_REL}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("inventory must be a JSON object")
    return data


def inventory_index(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = inventory.get("entries")
    if not isinstance(entries, list):
        raise ValueError("inventory.entries must be a list")
    index: dict[str, dict[str, Any]] = {}
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError("inventory entry must be an object")
        entry_id = str(row.get("id") or "")
        if not entry_id:
            raise ValueError("inventory entry missing id")
        classification = str(row.get("classification") or "")
        if classification not in VALID_CLASSIFICATIONS:
            raise ValueError(f"invalid classification for {entry_id}: {classification}")
        index[entry_id] = row
    return index


def find_unclassified(root: Path, inventory: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    inv = inventory if inventory is not None else load_inventory(root)
    known = inventory_index(inv)
    violations: list[dict[str, Any]] = []
    for site in scan_all(root):
        row = known.get(site.entry_id)
        if row is None:
            violations.append(
                {
                    "code": "unclassified-literal",
                    "file": site.file,
                    "line": site.line,
                    "literal": site.literal,
                    "script": site.script,
                }
            )
            continue
        if str(row.get("classification") or "") not in VALID_CLASSIFICATIONS:
            violations.append(
                {
                    "code": "invalid-classification",
                    "file": site.file,
                    "line": site.line,
                    "id": site.entry_id,
                }
            )
    return violations


def _literal_set_for_file(root: Path, rel_file: str) -> set[str]:
    path = root / rel_file
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8")
    return {script for _, _, _, script in extract_literals(text)}


def find_dist_mismatches(root: Path) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for dist_tree, core_tree in DIST_CORE_PAIRS:
        dist_dir = root / dist_tree
        if not dist_dir.is_dir():
            continue
        for dist_path in sorted(dist_dir.rglob("*")):
            if not dist_path.is_file() or dist_path.suffix not in SCAN_SUFFIXES:
                continue
            rel_under_dist = dist_path.relative_to(dist_dir).as_posix()
            core_file = f"{core_tree}/{rel_under_dist}"
            core_path = root / core_file
            if not core_path.is_file():
                continue
            dist_literals = _literal_set_for_file(root, dist_path.relative_to(root).as_posix())
            core_literals = _literal_set_for_file(root, core_file)
            if dist_literals != core_literals:
                violations.append(
                    {
                        "code": "dist-mismatch",
                        "coreFile": core_file,
                        "distFile": dist_path.relative_to(root).as_posix(),
                        "coreOnly": sorted(core_literals - dist_literals),
                        "distOnly": sorted(dist_literals - core_literals),
                    }
                )
    return violations


def write_inventory(root: Path, inventory: dict[str, Any]) -> Path:
    path = root / INVENTORY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(inventory, indent=2, sort_keys=False)
    path.write_text(payload + "\n", encoding="utf-8")
    return path


def cmd_generate(root: Path) -> int:
    inventory = build_inventory(root)
    out = write_inventory(root, inventory)
    print(
        json.dumps(
            {
                "verdict": "pass",
                "action": "generate",
                "path": str(out.relative_to(root)),
                "entryCount": len(inventory.get("entries") or []),
            },
            indent=2,
        )
    )
    return 0


def cmd_scan(root: Path) -> int:
    sites = scan_all(root)
    print(
        json.dumps(
            {
                "verdict": "ok",
                "action": "scan",
                "callSiteCount": len(sites),
                "sites": [
                    {
                        "id": site.entry_id,
                        "file": site.file,
                        "line": site.line,
                        "script": site.script,
                        "classification": classify_script(site.script),
                    }
                    for site in sites
                ],
            },
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sw_scripts_inventory.py")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate", help="Scan trees and write versioned inventory JSON")
    sub.add_parser("scan", help="Scan trees and print call sites (stdout JSON)")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = repo_root(Path(args.root))
    try:
        if args.cmd == "generate":
            return cmd_generate(root)
        if args.cmd == "scan":
            return cmd_scan(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}), file=sys.stderr)
        return 20
    return 2


if __name__ == "__main__":
    run_module_main(main)
