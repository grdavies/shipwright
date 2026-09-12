#!/usr/bin/env python3
"""PRD 339 R32 — planning visibility nomenclature consistency checker.

Validates that configuration surfaces use distinct operator terms for content
redaction tier vs backend storage placement, with migration guidance for the
deprecated ``planning.visibilityProfile`` alias.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_GUIDE_REL = Path("core/documentation/configuration.md")
CONFIG_README_REL = Path("core/documentation/README.md")
CONFIG_STUB_REL = Path("docs/guides/configuration.md")
WORKFLOW_EXAMPLES = (
    Path("core/sw-reference/workflow.config.example.json"),
    Path(".sw/workflow.config.example.json"),
)

REDACTION_TIER_KEY = "planning.visibilityTier"
DEPRECATED_PROFILE_KEY = "planning.visibilityProfile"
STORAGE_PLACEMENT_KEY = "planning.store.storeLocation"

REQUIRED_GUIDE_MARKERS: tuple[str, ...] = (
    "redaction tier",
    "storage placement",
    REDACTION_TIER_KEY,
    STORAGE_PLACEMENT_KEY,
    DEPRECATED_PROFILE_KEY,
    "migration",
)

CONFLATED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "visibility-profile-controls-storage",
        re.compile(
            r"visibility\s+profile[\s\S]{0,160}(?:choose|control|select|set|live)[\s\S]{0,120}"
            r"(?:store\s*location|storage\s+placement|storeLocation)",
            re.I,
        ),
    ),
    (
        "visibility-profile-json-store-location",
        re.compile(
            r'"visibilityProfile"\s*:\s*"[^"]+"\s*,\s*"storeLocation"',
            re.I,
        ),
    ),
)

@dataclass(frozen=True)
class NomenclatureFailure:
    rule: str
    path: str
    message: str


def _read_text(root: Path, rel: Path) -> str | None:
    path = root / rel
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _extract_planning_visibility_section(text: str) -> str:
    start = text.find("### Planning visibility")
    if start < 0:
        return ""
    end = text.find("\n### ", start + 1)
    return text[start:end] if end >= 0 else text[start:]


def _check_guide_vocabulary(root: Path) -> list[NomenclatureFailure]:
    failures: list[NomenclatureFailure] = []
    text = _read_text(root, CONFIG_GUIDE_REL)
    if text is None:
        return [
            NomenclatureFailure(
                "missing-config-guide",
                str(CONFIG_GUIDE_REL),
                "canonical configuration guide is required",
            )
        ]
    section = _extract_planning_visibility_section(text)
    if not section:
        failures.append(
            NomenclatureFailure(
                "missing-planning-visibility-section",
                str(CONFIG_GUIDE_REL),
                "planning visibility section is required",
            )
        )
        return failures
    for marker in REQUIRED_GUIDE_MARKERS:
        if marker.lower() not in section.lower():
            failures.append(
                NomenclatureFailure(
                    "missing-operator-term",
                    str(CONFIG_GUIDE_REL),
                    f"planning visibility section must mention {marker!r}",
                )
            )
    if REDACTION_TIER_KEY not in section:
        failures.append(
            NomenclatureFailure(
                "missing-redaction-tier-key",
                str(CONFIG_GUIDE_REL),
                f"{REDACTION_TIER_KEY} must be documented as the redaction-tier key",
            )
        )
    if "does not control" not in section.lower() and "never controlled" not in section.lower():
        failures.append(
            NomenclatureFailure(
                "missing-profile-placement-boundary",
                str(CONFIG_GUIDE_REL),
                "guide must state visibilityProfile never controlled storage placement",
            )
        )
    return failures


def _check_conflated_patterns(root: Path) -> list[NomenclatureFailure]:
    failures: list[NomenclatureFailure] = []
    targets = [CONFIG_GUIDE_REL, CONFIG_README_REL, CONFIG_STUB_REL]
    for rel in targets:
        text = _read_text(root, rel)
        if text is None:
            continue
        scope = _extract_planning_visibility_section(text) if rel == CONFIG_GUIDE_REL else text
        for rule_id, pattern in CONFLATED_PATTERNS:
            if pattern.search(scope):
                failures.append(
                    NomenclatureFailure(
                        rule_id,
                        str(rel),
                        f"conflated or stale visibility nomenclature ({rule_id})",
                    )
                )
    return failures


def has_stale_defaults_profile_row(text: str) -> bool:
    """True when the generated defaults table still lists profile without tier migration."""
    return bool(
        re.search(
            r"\|\s*`planning\.visibilityProfile`\s*\|"
            r"\s*`specs-public`\s*\|\s*`specs-public`\s*\|\s*`specs-public`\s*\|\s*`specs-public`\s*\|",
            text,
        )
    )


def _check_workflow_examples(root: Path) -> list[NomenclatureFailure]:
    failures: list[NomenclatureFailure] = []
    for rel in WORKFLOW_EXAMPLES:
        path = root / rel
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            failures.append(
                NomenclatureFailure(
                    "invalid-workflow-example-json",
                    str(rel),
                    "workflow config example must be valid JSON",
                )
            )
            continue
        planning = doc.get("planning")
        if not isinstance(planning, dict):
            continue
        if "visibilityTier" not in planning and "visibilityProfile" not in planning:
            failures.append(
                NomenclatureFailure(
                    "missing-redaction-tier-example",
                    str(rel),
                    "workflow example must document a redaction-tier key",
                )
            )
        store = planning.get("store")
        if not isinstance(store, dict) or "storeLocation" not in store:
            failures.append(
                NomenclatureFailure(
                    "missing-storage-placement-example",
                    str(rel),
                    "workflow example must document storage placement under planning.store",
                )
            )
    return failures


def check_visibility_nomenclature(root: Path) -> dict[str, Any]:
    """Return machine-readable pass/fail for PRD 339 R32 nomenclature checks."""
    failures = [
        *(_check_guide_vocabulary(root)),
        *(_check_conflated_patterns(root)),
        *(_check_workflow_examples(root)),
    ]
    return {
        "scenario": "visibility_tier_vs_storage_placement",
        "verdict": "pass" if not failures else "fail",
        "failures": [
            {"rule": row.rule, "path": row.path, "message": row.message} for row in failures
        ],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="PRD 339 R32 visibility nomenclature check")
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args(argv)
    result = check_visibility_nomenclature(Path(args.root).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
