"""PRD 066 phase 6 — canonical body dual-write vs projection (R26)."""

from __future__ import annotations

import sys
from pathlib import Path

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_store as ps


def test_r26_lcd_issue_body_is_freeze_hash_sot() -> None:
    """R26 — get/freeze resolves LCD Issue body; projection mirrors are not authority."""
    body = "# PRD 066\n\nCanonical LCD Issue body.\n"
    resolved = ps.resolve_canonical_freeze_body(
        unit_id="066-prd",
        body_path="docs/prds/066-prd.md",
        body=body,
        body_source="lcd-issue",
        projection_mirrors=[
            {
                "entityKind": "Project",
                "entityId": "proj-1",
                "summary": "Browsable title only",
                "derived": True,
            }
        ],
    )
    assert resolved["verdict"] == "pass"
    assert resolved["bodySource"] == "lcd-issue"
    assert resolved["freezeAuthority"] == "lcd-issue"
    assert resolved["body"] == body
    assert resolved["hash"]
    assert resolved["projectionRebuildable"] is True

    frozen = ps.freeze_from_canonical_body(
        unit_id="066-prd",
        body_path="docs/prds/066-prd.md",
        body=body,
        body_source="lcd-issue",
    )
    assert frozen["verdict"] == "pass"
    assert frozen["frozen"] is True
    assert frozen["hash"] == resolved["hash"]
    assert frozen["freezeAuthority"] == "lcd-issue"

    claimed = ps.assert_projection_mirrors_not_freeze_authority(
        [{"entityKind": "Milestone", "entityId": "ms-1", "isFreezeAuthority": True}]
    )
    assert claimed["verdict"] == "fail"
    assert claimed["error"] == "projection-claimed-freeze-authority"


def test_r26_document_backed_body_is_freeze_hash_sot() -> None:
    """R26 — explicitly Document-backed body path remains freeze/hash SoT via facade."""
    body = "<!-- sw-document-backed -->\n# Brainstorm body\n"
    resolved = ps.resolve_canonical_freeze_body(
        unit_id="066-bs",
        body_path="docs/brainstorms/066-bs.md",
        body=body,
        labels=["sw:document-backed"],
    )
    assert resolved["verdict"] == "pass"
    assert resolved["bodySource"] == "document-backed"
    assert resolved["freezeAuthority"] == "document-backed"

    explicit = ps.resolve_canonical_freeze_body(
        unit_id="066-bs",
        body=body,
        document_backed=True,
    )
    assert explicit["bodySource"] == "document-backed"

    policy = ps.dual_write_body_policy()
    assert "lcd-issue" in policy["canonicalBodySources"]
    assert "document-backed" in policy["canonicalBodySources"]
    assert policy["projectionIsFreezeAuthority"] is False
    assert "Document" in policy["projectionMirrorKinds"]


def test_r26_fail_closed_unresolved_canonical_body() -> None:
    """R26 — missing canonical body fails freeze; never falls through to projection."""
    missing = ps.freeze_from_canonical_body(
        unit_id="066-prd",
        body_path="docs/prds/066-prd.md",
        body=None,
        body_source="lcd-issue",
        projection_mirrors=[
            {
                "entityKind": "Document",
                "entityId": "doc-1",
                "body": "# Projection only body\n",
                "bodyParityRequired": True,
            }
        ],
    )
    assert missing["verdict"] == "fail"
    assert missing["error"] == "canonical-body-unresolved"
    assert missing["frozen"] is False

    empty = ps.resolve_canonical_freeze_body(
        unit_id="066-prd",
        body="   ",
        body_source="lcd-issue",
    )
    assert empty["verdict"] == "fail"
    assert empty["error"] == "canonical-body-unresolved"


def test_r26_fail_closed_projection_prefer_split_brain() -> None:
    """R26 — prefer-projection is fail-closed split-brain, not silent SoT swap."""
    body = "# Canonical\n"
    prefer = ps.resolve_canonical_freeze_body(
        unit_id="066-prd",
        body=body,
        prefer="projection",
    )
    assert prefer["verdict"] == "fail"
    assert prefer["error"] == "projection-prefer-split-brain"

    as_source = ps.resolve_canonical_freeze_body(
        unit_id="066-prd",
        body=body,
        body_source="Project",
    )
    assert as_source["verdict"] == "fail"
    assert as_source["error"] == "projection-claimed-freeze-authority"


def test_r26_typed_drift_when_projection_body_diverges() -> None:
    """R26 — projection body divergence is typed drift, not prefer-projection."""
    canonical = "# Canonical body\n"
    drift = ps.check_canonical_projection_split_brain(
        canonical_body=canonical,
        projection_mirrors=[
            {
                "entityKind": "Document",
                "entityId": "doc-1",
                "body": "# Human edited projection\n",
                "bodyParityRequired": True,
            }
        ],
    )
    assert drift["verdict"] == "fail"
    assert drift["error"] == "canonical-projection-body-drift"
    assert drift["typedDrift"] is True

    freeze_blocked = ps.freeze_from_canonical_body(
        unit_id="066-prd",
        body=canonical,
        projection_mirrors=[
            {
                "entityKind": "Project",
                "entityId": "proj-1",
                "body": "# Diverged\n",
                "bodyParityRequired": True,
            }
        ],
    )
    assert freeze_blocked["verdict"] == "fail"
    assert freeze_blocked["error"] == "canonical-projection-body-drift"
    assert freeze_blocked["frozen"] is False

    # Derived browsable summaries are allowed without drift.
    mirror = ps.dual_write_projection_mirror(
        canonical_body=canonical,
        entity_kind="Document",
        entity_id="doc-1",
        derived_summary="PRD 066 summary",
    )
    assert mirror["verdict"] == "pass"
    assert mirror["mirror"]["isFreezeAuthority"] is False
    ok = ps.resolve_canonical_freeze_body(
        unit_id="066-prd",
        body=canonical,
        projection_mirrors=[mirror["mirror"]],
    )
    assert ok["verdict"] == "pass"


def test_r26_facade_exports_and_schema_policy_surface() -> None:
    """R26 — planning_store facade exposes dual-write APIs; schema contract includes policy."""
    assert callable(ps.resolve_canonical_freeze_body)
    assert callable(ps.freeze_from_canonical_body)
    assert callable(ps.check_canonical_projection_split_brain)
    assert callable(ps.dual_write_projection_mirror)
    contract = ps.linear_projection_schema_contract()
    assert contract["verdict"] == "ok"
    assert "dualWriteBody" in contract
    assert contract["dualWriteBody"]["unresolvedCanonicalBody"] == "fail-closed"
    assert contract["dualWriteBody"]["projectionPreferSplitBrain"] == "fail-closed"
