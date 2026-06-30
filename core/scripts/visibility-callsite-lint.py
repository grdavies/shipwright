#!/usr/bin/env python3
"""Machine-checked call-site map for planning visibility emission points (PRD 034 R14)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from planning_visibility import EMISSION_POINTS, REDACTED_BODY_MARKER  # noqa: E402

# Phase 2 wired consumers — must import planning_visibility or call visibility-resolve.py
WIRED_POINT_SCRIPTS: dict[str, str] = {
    "index-active": "scripts/planning_index_gen.py",
    "index-archive": "scripts/planning_reconcile.py",
    "legacy-gap-backlog": "scripts/planning_legacy_projection.py",
    "legacy-prd-index": "scripts/planning_legacy_projection.py",
    "spec-seed": "scripts/wave_spec_seed.py",
}

RESOLVER_MARKERS = (
    "planning_visibility",
    "visibility-resolve.py",
    "visibility_resolve",
)

BYPASS_PATTERN = re.compile(
    r"\.read_text\s*\(|open\s*\([^)]+\)\.read\s*\(",
    re.MULTILINE,
)


def parse_map_points(map_path: Path) -> dict[str, str]:
    if not map_path.is_file():
        return {}
    rows: dict[str, str] = {}
    for line in map_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 3:
            continue
        point = parts[0].strip("`")
        script = parts[1].strip("`")
        if point in EMISSION_POINTS and script.startswith("scripts/"):
            rows[point] = script
    return rows


def lint_map_exhaustiveness(map_path: Path) -> list[str]:
    errors: list[str] = []
    mapped = parse_map_points(map_path)
    for point_id in sorted(EMISSION_POINTS):
        if point_id not in mapped:
            errors.append(f"call-site map missing emission point: {point_id}")
    for point_id, script in mapped.items():
        expected = WIRED_POINT_SCRIPTS.get(point_id)
        if expected and script != expected:
            errors.append(f"{point_id}: map script {script!r} != wired {expected!r}")
    return errors


def script_uses_resolver(repo_root: Path, rel_script: str) -> bool:
    path = repo_root / rel_script
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return any(marker in text for marker in RESOLVER_MARKERS)


def lint_wired_scripts(repo_root: Path) -> list[str]:
    errors: list[str] = []
    seen_scripts = sorted(set(WIRED_POINT_SCRIPTS.values()))
    for rel in seen_scripts:
        if not script_uses_resolver(repo_root, rel):
            errors.append(f"wired script bypasses resolver (no planning_visibility import): {rel}")
    return errors


def lint_bypass_probe(probe_path: Path) -> list[str]:
    """Fixture probe: a script with body reads but no resolver import must fail."""
    if not probe_path.is_file():
        return [f"bypass probe missing: {probe_path}"]
    text = probe_path.read_text(encoding="utf-8")
    if any(marker in text for marker in RESOLVER_MARKERS):
        return [f"bypass probe incorrectly imports resolver: {probe_path}"]
    if not BYPASS_PATTERN.search(text):
        return [f"bypass probe missing body read pattern: {probe_path}"]
    return []


def scan_golden_markers(content: str) -> list[str]:
    errors: list[str] = []
    if REDACTED_BODY_MARKER in content:
        return errors
    golden_private = ("TOP_SECRET_CODENAME_XYZ", "PRIVATE_BODY_GOLDEN_MARKER")
    for marker in golden_private:
        if marker in content:
            errors.append(f"private-body golden marker leaked: {marker}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Visibility call-site map lint (PRD 034 R14)")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--map", required=True, help="call-site-map.md path")
    parser.add_argument("--probe-bypass", default=None, help="Fixture bypass probe script")
    parser.add_argument("--scan-content", default=None, help="Scan generated artifact for golden markers")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    map_path = Path(args.map)
    if not map_path.is_absolute():
        map_path = root / map_path

    errors: list[str] = []
    errors.extend(lint_map_exhaustiveness(map_path))
    errors.extend(lint_wired_scripts(root))

    if args.probe_bypass:
        probe = Path(args.probe_bypass)
        if not probe.is_absolute():
            probe = root / probe
        bypass_errors = lint_bypass_probe(probe)
        if not bypass_errors:
            errors.append("bypass probe passed lint — expected failure for unwrapped body read")
        else:
            # Expected: probe fails resolver check (first error is the signal)
            pass

    if args.scan_content:
        content_path = Path(args.scan_content)
        if not content_path.is_absolute():
            content_path = root / content_path
        if content_path.is_file():
            errors.extend(scan_golden_markers(content_path.read_text(encoding="utf-8")))

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 20

    print(
        json.dumps(
            {
                "verdict": "pass",
                "emissionPoints": len(EMISSION_POINTS),
                "wiredScripts": sorted(set(WIRED_POINT_SCRIPTS.values())),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
