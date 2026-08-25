#!/usr/bin/env python3
"""Documented-default parity checker (PRD 330 R1/R2).

Validates bounded drift-prone operator claims against effective config/default
projections and selected documentation surfaces. Emits machine-readable verdict JSON.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _sw.cli import run_module_main

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

EFFECTIVE_CONFIG_REL = Path("core/sw-reference/generated/effective-config.json")
PROVENANCE_REL = Path("PROVENANCE.md")

# Bounded drift-prone claims — extend only with PRD/task coverage.
BOUNDED_CLAIMS: tuple[dict[str, str], ...] = (
    {
        "id": "review-provider-effective-default",
        "configKey": "review.provider",
        "expectedDefault": "none",
    },
)


@dataclass(frozen=True)
class DocRule:
    rule_id: str
    pattern: re.Pattern[str]
    message: str


def _load_effective_setting(root: Path, key: str) -> dict[str, Any] | None:
    path = root / EFFECTIVE_CONFIG_REL
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    settings = doc.get("settings")
    if not isinstance(settings, dict):
        return None
    row = settings.get(key)
    return row if isinstance(row, dict) else None


def _effective_default_matches(root: Path, key: str, expected: str) -> tuple[bool, str | None]:
    row = _load_effective_setting(root, key)
    if row is None:
        return False, f"missing effective-config row for {key}"
    for field in ("schemaDefault", "greenfieldDefault", "migrationDefault", "runtimeFallback"):
        value = row.get(field)
        if value != expected:
            return False, f"{key}.{field}={value!r} expected {expected!r}"
    return True, None


def _provenance_rules() -> tuple[DocRule, ...]:
    return (
        DocRule(
            "provenance-coderabbit-opt-in",
            re.compile(r"review\.provider:\s*`?coderabbit`?.*opt-in|opt-in.*review\.provider:\s*`?coderabbit`?", re.I),
            "PROVENANCE.md must describe CodeRabbit as opt-in under review.provider: coderabbit",
        ),
        DocRule(
            "provenance-review-default-none",
            re.compile(
                r"(effective default|default).{0,40}`?none`?|"
                r"`review\.provider`.*default.*`?none`?|"
                r"default\s+`?\*\*none\*\*`?",
                re.I,
            ),
            "PROVENANCE.md must state review.provider effective default is none",
        ),
        DocRule(
            "provenance-init-primary",
            re.compile(r"/sw-init"),
            "PROVENANCE.md must name /sw-init for setup guidance",
        ),
        DocRule(
            "provenance-setup-deprecated",
            re.compile(r"/sw-setup.*deprecated|deprecated.*`/sw-setup`", re.I),
            "PROVENANCE.md must identify /sw-setup only as a deprecated alias",
        ),
    )


def _has_unqualified_sw_setup(text: str) -> bool:
    if "/sw-setup" not in text:
        return False
    if re.search(r"/sw-setup.*deprecated|deprecated.*`/sw-setup`|deprecated alias", text, re.I):
        return False
    return True


def _forbidden_provenance_rules() -> tuple[DocRule, ...]:
    return (
        DocRule(
            "stale-coderabbit-default",
            re.compile(r"review\.provider:\s*`?coderabbit`?\s*\(default\)", re.I),
            "stale claim: CodeRabbit marked as review.provider default",
        ),
    )


def _validate_provenance_text(text: str) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for rule in _forbidden_provenance_rules():
        if rule.pattern.search(text):
            failures.append({"rule": rule.rule_id, "message": rule.message})
    for rule in _provenance_rules():
        if not rule.pattern.search(text):
            failures.append({"rule": rule.rule_id, "message": rule.message})
    return failures


def run_check(root: Path, *, provenance_text: str | None = None) -> dict[str, Any]:
    """Evaluate bounded claims; return machine-readable verdict payload."""
    root = root.resolve()
    claim_results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for claim in BOUNDED_CLAIMS:
        ok, err = _effective_default_matches(root, claim["configKey"], claim["expectedDefault"])
        claim_results.append(
            {
                "id": claim["id"],
                "configKey": claim["configKey"],
                "expectedDefault": claim["expectedDefault"],
                "verdict": "pass" if ok else "fail",
                "detail": err,
            }
        )
        if not ok and err:
            failures.append({"rule": claim["id"], "message": err})

    provenance_path = root / PROVENANCE_REL
    if provenance_text is None:
        if not provenance_path.is_file():
            failures.append({"rule": "provenance-missing", "message": f"missing {PROVENANCE_REL}"})
        else:
            provenance_text = provenance_path.read_text(encoding="utf-8")
    if provenance_text is not None:
        failures.extend(_validate_provenance_text(provenance_text))
        if _has_unqualified_sw_setup(provenance_text):
            failures.append(
                {
                    "rule": "unqualified-sw-setup-primary",
                    "message": "unqualified /sw-setup as primary setup guidance",
                }
            )

    verdict = "pass" if not failures else "fail"
    return {
        "verdict": verdict,
        "claims": claim_results,
        "failures": failures,
        "surfaces": [str(PROVENANCE_REL)],
    }


def validate_documented_defaults(root: Path) -> str | None:
    """Fail-closed gate hook — first failure message or None when green."""
    result = run_check(root)
    if result.get("verdict") == "pass":
        return None
    failures = result.get("failures") or []
    if failures:
        first = failures[0]
        return f"{first.get('rule')}: {first.get('message')}"
    return "documented-defaults-check-failed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="documented_defaults_check.py")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Run parity check and emit JSON verdict")
    ns = parser.parse_args(argv)
    root = Path(ns.root).resolve()
    if ns.cmd == "run":
        payload = run_check(root)
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("verdict") == "pass" else 1
    return 2


if __name__ == "__main__":
    run_module_main(main)
