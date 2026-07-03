#!/usr/bin/env python3
"""Root-level project-type detector + verify proposal helper (PRD 018 R1/R20)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from _sw.cli import run_module_main

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent


def _resolve_presets(root: Path) -> Path:
    presets_path = root / "core/sw-reference/verify-presets.json"
    if presets_path.is_file():
        return presets_path
    for env_key in ("CURSOR_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT"):
        candidate = Path(os.environ.get(env_key, "")) / "core/sw-reference/verify-presets.json"
        if candidate.is_file():
            return candidate
    return presets_path


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    root = REPO_ROOT
    propose = False
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--root" and i + 1 < len(args):
            root = Path(args[i + 1]).resolve()
            i += 2
            continue
        if token == "--propose":
            propose = True
            i += 1
            continue
        if token in ("-h", "--help"):
            print("usage: detect-project-type.py [--root DIR] [--propose]")
            return 0
        print(json.dumps({"verdict": "fail", "error": "unknown argument"}), file=sys.stderr)
        return 2

    presets_path = _resolve_presets(root)

    markers = [
        ("node", ["package.json"], "high"),
        ("python", ["pyproject.toml", "setup.py", "setup.cfg"], "high"),
        ("go", ["go.mod"], "high"),
        ("rust", ["Cargo.toml"], "high"),
        ("ruby", ["Gemfile"], "high"),
        ("jvm", ["pom.xml", "build.gradle", "build.gradle.kts"], "high"),
        ("make", ["Makefile"], "medium"),
        ("ansible", ["ansible.cfg", "galaxy.yml"], "high"),
    ]

    matches = []
    for ptype, files, confidence in markers:
        for name in files:
            if (root / name).is_file():
                matches.append({"type": ptype, "confidence": confidence, "marker": name})
                break

    ambiguous = len({m["type"] for m in matches}) > 1
    out: dict = {"matches": matches, "ambiguous": ambiguous}

    if not propose:
        print(json.dumps(out, indent=2))
        return 0

    presets_doc = {}
    if presets_path.is_file():
        presets_doc = json.loads(presets_path.read_text(encoding="utf-8"))

    preset_table = presets_doc.get("presets", {})
    allowlisted = presets_doc.get("nodeAllowlistedKeys", ["lint", "test", "build", "typecheck"])
    key_pattern = re.compile(presets_doc.get("nodeKeyPattern", r"^[a-zA-Z0-9_-]+$"))
    unsafe_re = re.compile(r"[;&|`$()]")
    destructive_re = re.compile(r"\b(rm\s+-rf|mkfs|dd\s+if=|:\(\)\{|fork\s+bomb)\b", re.I)

    def is_unsafe(cmd: str) -> bool:
        if not cmd or not cmd.strip():
            return True
        if unsafe_re.search(cmd) or destructive_re.search(cmd):
            return True
        stripped = cmd.strip()
        if stripped in (":", "true", "exit 0"):
            return True
        return stripped.startswith("echo ")

    def node_proposals() -> tuple[dict, list, list]:
        proposals: dict = {}
        gaps: list = []
        unsafe: list = []
        pkg = root / "package.json"
        scripts: dict = {}
        if pkg.is_file():
            try:
                scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}
            except json.JSONDecodeError:
                scripts = {}
        node_presets = preset_table.get("node", {})
        for key in allowlisted:
            cmd = None
            source = "preset"
            if key in scripts and key_pattern.match(key):
                cmd = f"npm run {key}"
                source = "package.json"
            elif key in node_presets:
                cmd = node_presets[key]
                source = "preset"
            if not cmd:
                gaps.append(key)
                continue
            entry = {"command": cmd, "source": source, "key": key}
            if is_unsafe(cmd) or (key in scripts and is_unsafe(str(scripts.get(key, "")))):
                entry["safe"] = False
                unsafe.append(key)
            else:
                entry["safe"] = True
            proposals[key] = entry
        return proposals, gaps, unsafe

    def preset_proposals(ptype: str) -> tuple[dict, list, list]:
        proposals: dict = {}
        gaps: list = []
        unsafe: list = []
        table = preset_table.get(ptype, {})
        for key, cmd in table.items():
            entry = {"command": cmd, "source": "preset", "key": key}
            if is_unsafe(cmd):
                entry["safe"] = False
                unsafe.append(key)
            else:
                entry["safe"] = True
            proposals[key] = entry
        if not table:
            gaps.extend(["lint", "test", "build"])
        return proposals, gaps, unsafe

    types = [m["type"] for m in matches]
    primary = types[0] if len(types) == 1 else None
    proposals: dict = {}
    gaps: list = []
    unsafe: list = []
    if primary == "node":
        proposals, gaps, unsafe = node_proposals()
    elif primary:
        proposals, gaps, unsafe = preset_proposals(primary)

    out["proposals"] = proposals
    out["verifyGaps"] = sorted(set(gaps))
    out["unsafe"] = sorted(set(unsafe))
    out["primaryType"] = primary
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    run_module_main(main)
