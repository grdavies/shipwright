"""Regression tests for gap-105 opaque issue-store locator type hygiene (PRD 060 R1–R3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from planning_canonical import (
    ARTIFACT_TYPE_UNRESOLVED,
    ArtifactTypeUnresolved,
    artifact_type_from_content,
    infer_artifact_type,
    require_artifact_type,
    type_label,
)
from planning_store import IssueStoreBackend


GAP_CONTENT = """---
id: gap-fixture-opaque
type: gap
status: open
title: opaque locator fixture
visibility: public
---

# gap fixture
"""


@pytest.mark.parametrize(
    ("body_path", "expected"),
    [
        ("issue:297", ARTIFACT_TYPE_UNRESOLVED),
        ("issue-cache:42", ARTIFACT_TYPE_UNRESOLVED),
        ("docs/prds/gap/gap-x/gap-x.md", "gap"),
        ("docs/prds/060-slug/tasks-060-slug.md", "tasks"),
    ],
)
def test_infer_artifact_type_opaque_vs_path(body_path: str, expected: str) -> None:
    assert infer_artifact_type(body_path) == expected


def test_artifact_type_from_content_frontmatter() -> None:
    assert artifact_type_from_content(GAP_CONTENT) == "gap"


def test_require_artifact_type_prefers_content_over_opaque_path() -> None:
    assert require_artifact_type("issue:1", content=GAP_CONTENT) == "gap"


def test_require_artifact_type_fail_closed_on_opaque_without_hints() -> None:
    with pytest.raises(ArtifactTypeUnresolved):
        require_artifact_type("issue:99")


def test_issue_store_put_via_opaque_locator_preserves_gap_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    (root / ".cursor" / "hooks" / "state").mkdir(parents=True)
    cfg = {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "fixture-alpha",
            }
        },
    }
    cfg_path = root / ".cursor" / "workflow.config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    unit_id = "gap-fixture-opaque"
    file_path = "docs/prds/gap/gap-fixture-opaque/gap-fixture-opaque.md"
    backend = IssueStoreBackend(root, cfg)
    created = backend.put(unit_id, file_path, GAP_CONTENT)
    assert created.verdict == "ok"
    record = backend._lookup_record(unit_id, file_path)  # noqa: SLF001 — fixture introspection
    opaque_path = f"issue:{record.number}"
    assert infer_artifact_type(opaque_path) == ARTIFACT_TYPE_UNRESOLVED

    updated = backend.put(unit_id, opaque_path, GAP_CONTENT + "\n")
    assert updated.verdict == "ok"
    refreshed = backend._client.issue_get(record.id)  # noqa: SLF001
    label_set = set(refreshed.labels)
    assert type_label("gap") in label_set
    assert type_label("prd") not in label_set
