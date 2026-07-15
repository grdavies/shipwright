"""PRD 070 phase 3 — PR-to-delivery mapping + closure manifest tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import deliver_closeout as dc

SHA = "a" * 40
HEAD = "b" * 40


def test_validate_metadata_rejects_hostile_pr_title() -> None:
    result = dc.validate_metadata_field("prTitle", "feat; rm -rf /")
    assert result["verdict"] == "pass"
    hostile = dc.validate_metadata_field("prTitle", "bad\x00title")
    assert hostile["verdict"] == "fail"


def test_validate_metadata_rejects_invalid_prd_unit_id() -> None:
    result = dc.validate_metadata_field("prdUnitId", "not-a-unit")
    assert result["verdict"] == "fail"


def test_record_mapping_immutable(tmp_path: Path) -> None:
    payload = {
        "prNumber": "42",
        "prdUnitId": "prd-070-automated-delivery-closeout",
        "deliverySlug": "automated-delivery-closeout",
        "targetBranch": "feat/automated-delivery-closeout",
        "headSha": HEAD,
        "runSlug": "automated-delivery-closeout",
    }
    first = dc.record_pr_delivery_mapping(tmp_path, payload)
    assert first["verdict"] == "pass"
    conflict = dict(payload)
    conflict["deliverySlug"] = "other-slug"
    second = dc.record_pr_delivery_mapping(tmp_path, conflict)
    assert second["verdict"] == "fail"
    assert second["error"] == "mapping-immutable-conflict"


def test_resolve_delivery_for_pr_uses_mapping(tmp_path: Path) -> None:
    payload = {
        "prNumber": "99",
        "prdUnitId": "prd-070-automated-delivery-closeout",
        "deliverySlug": "automated-delivery-closeout",
        "targetBranch": "feat/automated-delivery-closeout",
        "headSha": HEAD,
        "runSlug": "automated-delivery-closeout",
    }
    dc.record_pr_delivery_mapping(tmp_path, payload)
    resolved = dc.resolve_delivery_for_pr(tmp_path, 99)
    assert resolved["verdict"] == "pass"
    assert resolved["prdUnitId"] == "prd-070-automated-delivery-closeout"
    missing = dc.resolve_delivery_for_pr(tmp_path, 100)
    assert missing["verdict"] == "fail"
    assert missing["error"] == "no-delivery-mapping"


def test_build_closure_manifest_shape() -> None:
    manifest = dc.build_closure_manifest(
        prd_unit_id="prd-070-automated-delivery-closeout",
        merge_sha=SHA,
        delivery_set=[{"unitId": "prd-070-automated-delivery-closeout", "artifactType": "prd", "priorState": "open"}],
        pr_number=42,
    )
    assert manifest["mergeSha"] == SHA
    assert manifest["deliverySet"][0]["priorState"] == "open"
    assert manifest["prNumber"] == 42


def test_persist_closure_manifest_writes_file(tmp_path: Path) -> None:
    manifest = dc.build_closure_manifest(
        prd_unit_id="prd-070-automated-delivery-closeout",
        merge_sha=SHA,
        delivery_set=[],
    )
    result = dc.persist_closure_manifest(tmp_path, manifest)
    assert result["verdict"] == "pass"
    loaded = dc.load_closure_manifest(tmp_path, "prd-070-automated-delivery-closeout")
    assert loaded is not None
    assert loaded["mergeSha"] == SHA
