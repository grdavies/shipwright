"""PRD 339 R32 — planning visibility nomenclature documentation consistency."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from prd339_visibility_nomenclature import (
    check_visibility_nomenclature,
    has_stale_defaults_profile_row,
)

ROOT = Path(__file__).resolve().parents[3]

CONFLATED_GUIDE = """\
### Planning visibility

Use the visibility profile to choose whether planning bodies live in the same repo
or a separate project via `planning.store.storeLocation.mode`.

| Axis | Key |
|------|-----|
| Visibility profile | `planning.visibilityProfile` |
"""

STALE_DEFAULTS_ROW = """\
| `planning.visibilityProfile` | `specs-public` | `specs-public` | `specs-public` | `specs-public` | `—` | `—` |
"""

GOOD_GUIDE_SNIPPET = """\
### Planning visibility (redaction tier and storage placement)

**Operator vocabulary:** use **redaction tier** for content-default privacy and
**storage placement** for where planning bodies are stored. These axes are orthogonal.

| Axis | Key |
|------|-----|
| Redaction tier | `planning.visibilityTier` |
| Storage placement | `planning.store.storeLocation.mode` |

**Migration:** rename `planning.visibilityProfile` → `planning.visibilityTier`.
`planning.visibilityProfile` never controlled storage placement.
"""


def test_visibility_tier_vs_storage_placement_passes_on_repo() -> None:
    result = check_visibility_nomenclature(ROOT)
    assert result["scenario"] == "visibility_tier_vs_storage_placement"
    assert result["verdict"] == "pass", result


def test_visibility_tier_vs_storage_placement_rejects_conflated_guide(
    tmp_path: Path,
) -> None:
    guide = tmp_path / "core/documentation/configuration.md"
    guide.parent.mkdir(parents=True)
    guide.write_text(CONFLATED_GUIDE, encoding="utf-8")
    result = check_visibility_nomenclature(tmp_path)
    assert result["verdict"] == "fail"
    rules = {row["rule"] for row in result["failures"]}
    assert "visibility-profile-controls-storage" in rules


def test_visibility_tier_vs_storage_placement_detects_stale_defaults_row() -> None:
    text = GOOD_GUIDE_SNIPPET + "\n" + STALE_DEFAULTS_ROW
    assert has_stale_defaults_profile_row(text)
    assert not has_stale_defaults_profile_row(GOOD_GUIDE_SNIPPET)


def test_visibility_tier_vs_storage_placement_requires_operator_terms(
    tmp_path: Path,
) -> None:
    guide = tmp_path / "core/documentation/configuration.md"
    guide.parent.mkdir(parents=True)
    guide.write_text(
        "### Planning visibility\n\n`planning.visibilityTier` only.\n",
        encoding="utf-8",
    )
    result = check_visibility_nomenclature(tmp_path)
    assert result["verdict"] == "fail"
    rules = {row["rule"] for row in result["failures"]}
    assert "missing-operator-term" in rules
