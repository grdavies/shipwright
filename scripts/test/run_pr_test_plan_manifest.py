#!/usr/bin/env python3
"""Run pr-test-plan manifest fixtures (PRD 016 R1-R3)."""
from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent


def run_suite(path: Path) -> int:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return int(mod.main()) if hasattr(mod, "main") else 1


def main() -> int:
    manifest_path = Path(
        __import__("os").environ.get(
            "PR_TEST_PLAN_MANIFEST",
            str(ROOT / "core/sw-reference/pr-test-plan.manifest.json"),
        )
    )
    if not manifest_path.is_file():
        print(f"FAIL pr-test-plan-manifest: missing manifest at {manifest_path}", file=sys.stderr)
        return 1
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = data.get("fixtures") or []
    if not fixtures:
        print("FAIL pr-test-plan-manifest: empty fixtures list", file=sys.stderr)
        return 1
    valid = {"required", "advisory"}
    for entry in fixtures:
        for key in ("id", "script", "classification", "ciJobName"):
            if key not in entry or not str(entry[key]).strip():
                print(f"FAIL pr-test-plan-manifest: fixture missing {key!r}: {entry!r}", file=sys.stderr)
                return 1
        if entry["classification"] not in valid:
            print(
                f"FAIL pr-test-plan-manifest: invalid classification {entry['classification']!r} for {entry['id']}",
                file=sys.stderr,
            )
            return 1
    print(f"OK  pr-test-plan-manifest: {len(fixtures)} fixtures loaded from {manifest_path}")
    failures = 0
    for entry in fixtures:
        rel = entry["script"]
        path = ROOT / rel
        if not path.is_file():
            print(f"FAIL pr-test-plan/{entry['id']}: missing {path}")
            failures += 1
            continue
        print(f"==> pr-test-plan/{entry['id']}: {rel}")
        if run_suite(path) != 0:
            failures += 1
    if failures:
        print(f"FAIL pr-test-plan-manifest: {failures} suite(s) failed", file=sys.stderr)
        return 1
    print("OK  pr-test-plan-manifest: all fixtures passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
