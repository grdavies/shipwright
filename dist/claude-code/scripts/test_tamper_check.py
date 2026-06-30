#!/usr/bin/env python3
"""PRD 039 R9 — baseline-anchored test tamper check (Python entrypoint)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from _sw.cli import run_module_main

ASSERT_PATTERNS = (
    re.compile(r"\bassert\b"),
    re.compile(r"self\.assert\w+\s*\("),
    re.compile(r"\bexpect\s*\("),
    re.compile(r"assert_\w+\s*\("),
)
COVERAGE_FAIL_UNDER = re.compile(
    r"(fail_under|cov-fail-under|--cov-fail-under)\s*[=:]?\s*(\d+(?:\.\d+)?)",
    re.I,
)


def count_assertions(text: str) -> int:
    return sum(len(pat.findall(text)) for pat in ASSERT_PATTERNS)


def coverage_thresholds(text: str) -> list[float]:
    vals: list[float] = []
    for m in COVERAGE_FAIL_UNDER.finditer(text):
        try:
            vals.append(float(m.group(2)))
        except ValueError:
            continue
    return vals


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_root(baseline: dict, arg_root: str | None) -> Path:
    if arg_root:
        return Path(arg_root).resolve()
    root = baseline.get("root")
    if root:
        return Path(str(root)).resolve()
    return Path(".").resolve()


def enrich_baseline_meta(baseline: dict, root: Path) -> None:
    for rel, meta in (baseline.get("files") or {}).items():
        path = root / rel
        if path.is_file() and "assertionCount" not in meta:
            text = path.read_text(encoding="utf-8", errors="replace")
            meta["assertionCount"] = count_assertions(text)
    for ent in baseline.get("coverageConfig") or []:
        rel = ent.get("path", "")
        path = root / rel
        if path.is_file() and "coverageThresholds" not in ent:
            ent["coverageThresholds"] = coverage_thresholds(
                path.read_text(encoding="utf-8", errors="replace")
            )


def compare_baseline(
    baseline: dict,
    root: Path,
    *,
    test_weakened: bool | None,
) -> tuple[list[dict], list[dict]]:
    blocking: list[dict] = []
    advisory: list[dict] = []

    for rel, meta in (baseline.get("files") or {}).items():
        path = root / rel
        if not path.is_file():
            blocking.append({"code": "test_file_deleted", "path": rel, "tier": "R9a"})
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if meta.get("recreated"):
            blocking.append({"code": "delete_recreate", "path": rel, "tier": "R9a"})
        if meta.get("sha256") and digest != meta["sha256"]:
            cur_asserts = count_assertions(text)
            base_asserts = int(meta.get("assertionCount", cur_asserts))
            if cur_asserts < base_asserts:
                blocking.append(
                    {
                        "code": "assertion_count_drop",
                        "path": rel,
                        "before": base_asserts,
                        "after": cur_asserts,
                        "tier": "R9a",
                    }
                )

    for ent in baseline.get("coverageConfig") or []:
        rel = ent.get("path", "")
        path = root / rel
        if not path.is_file():
            advisory.append({"code": "coverage_config_missing", "path": rel, "tier": "R9b"})
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        cur = coverage_thresholds(text)
        base = [float(x) for x in (ent.get("coverageThresholds") or [])]
        if base and cur and max(cur) < min(base):
            blocking.append(
                {
                    "code": "coverage_threshold_drop",
                    "path": rel,
                    "before": base,
                    "after": cur,
                    "tier": "R9a",
                }
            )

    detected = bool(blocking)
    if test_weakened is not None:
        if test_weakened and not detected:
            blocking.append(
                {
                    "code": "testWeakened_disagreement",
                    "detail": "testWeakened true but no R9a baseline flags",
                    "tier": "R9a",
                }
            )
        if not test_weakened and detected:
            blocking.append(
                {
                    "code": "testWeakened_disagreement",
                    "detail": "testWeakened false but R9a baseline flags present",
                    "tier": "R9a",
                }
            )

    return blocking, advisory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="test_tamper_check")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--root", help="Repo root override")
    parser.add_argument("--status", help="Optional sw-tdd.status.json path")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    try:
        baseline = load_json(Path(args.baseline))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"verdict": "fail", "error": "invalid baseline"}))
        return 20

    root = resolve_root(baseline, args.root)
    test_weakened: bool | None = None
    if args.status:
        try:
            status = load_json(Path(args.status))
            if "testWeakened" in status:
                test_weakened = bool(status.get("testWeakened"))
        except (OSError, json.JSONDecodeError):
            print(json.dumps({"verdict": "fail", "error": "invalid status"}))
            return 20

    enrich_baseline_meta(baseline, root)
    blocking, advisory = compare_baseline(baseline, root, test_weakened=test_weakened)

    if blocking:
        verdict, code = "fail", 20
    elif advisory:
        verdict, code = "advisory", 10
    else:
        verdict, code = "pass", 0

    print(
        json.dumps(
            {
                "verdict": verdict,
                "blocking": blocking,
                "advisory": advisory,
                "authoritativeOverTestWeakened": True,
            }
        )
    )
    return code


if __name__ == "__main__":
    run_module_main(main)
