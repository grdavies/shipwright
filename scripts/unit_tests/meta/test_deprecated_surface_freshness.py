"""PRD 060 R10 deprecated-surface freshness tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import deprecated_surface_freshness as dsf


def test_empty_manifest_passes(tmp_path: Path) -> None:
    manifest = tmp_path / "core/sw-reference/deprecated-surface-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"version": 1, "surfaces": []}), encoding="utf-8")
    (tmp_path / "scripts/unit_tests").mkdir(parents=True)
    harness = tmp_path / "scripts/unit_tests/sample.py"
    harness.write_text("REDACT=scripts/memory-redact.sh\n", encoding="utf-8")
    assert dsf.check(tmp_path)["verdict"] == "pass"


def test_manifest_violation_fails(tmp_path: Path) -> None:
    manifest = tmp_path / "core/sw-reference/deprecated-surface-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "surfaces": [
                    {
                        "id": "memory-redact-sh",
                        "deprecatedPath": "scripts/memory-redact.sh",
                        "replacementPath": "scripts/memory-redact.py",
                        "harnessGlobs": ["scripts/unit_tests/**"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    harness = tmp_path / "scripts/unit_tests/sample.py"
    harness.parent.mkdir(parents=True)
    harness.write_text("x = 'scripts/memory-redact.sh'\n", encoding="utf-8")
    assert dsf.check(tmp_path)["verdict"] == "fail"


def test_disable_annotation_allows_reference(tmp_path: Path) -> None:
    manifest = tmp_path / "core/sw-reference/deprecated-surface-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "surfaces": [
                    {
                        "id": "memory-redact-sh",
                        "deprecatedPath": "scripts/memory-redact.sh",
                        "harnessGlobs": ["scripts/unit_tests/**"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    harness = tmp_path / "scripts/unit_tests/sample.py"
    harness.parent.mkdir(parents=True)
    harness.write_text(
        "# deprecated-surface-disable: memory-redact-sh\nscripts/memory-redact.sh\n",
        encoding="utf-8",
    )
    assert dsf.check(tmp_path)["verdict"] == "pass"
