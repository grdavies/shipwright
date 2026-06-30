#!/usr/bin/env python3
"""Root-level project-type detector + verify proposal helper (PRD 018 R1/R20). """
from __future__ import annotations

import sys

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    import json
    import re
    import sys
    from pathlib import Path

    root = Path(sys.argv[1])
    presets_path = Path(sys.argv[2])
    propose = sys.argv[3] == "1"

    MARKERS = [
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
    for ptype, files, confidence in MARKERS:
        for name in files:
            if (root / name).is_file():
                matches.append({"type": ptype, "confidence": confidence, "marker": name})
                break

    ambiguous = len({m["type"] for m in matches}) > 1

    out = {"matches": matches, "ambiguous": ambiguous}

    if not propose:
        print(json.dumps(out, indent=2))
        raise SystemExit(0)

    presets_doc = {}
    if presets_path.is_file():
        presets_doc = json.loads(presets_path.read_text(encoding="utf-8"))

    preset_table = presets_doc.get("presets", {})
    allowlisted = presets_doc.get("nodeAllowlistedKeys", ["lint", "test", "build", "typecheck"])
    key_pattern = re.compile(presets_doc.get("nodeKeyPattern", r"^[a-zA-Z0-9_-]+$"))

    UNSAFE_RE = re.compile(r"[;&|`$()]")
    DESTRUCTIVE_RE = re.compile(
        r"\b(rm\s+-rf|mkfs|dd\s+if=|:\(\)\{|fork\s+bomb)\b", re.I
    )


    def is_unsafe(cmd: str) -> bool:
        if not cmd or not cmd.strip():
            return True
        if UNSAFE_RE.search(cmd):
            return True
        if DESTRUCTIVE_RE.search(cmd):
            return True
        stripped = cmd.strip()
        if stripped in (":", "true", "exit 0"):
            return True
        if stripped.startswith("echo "):
            return True
        return False


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
