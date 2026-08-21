#!/usr/bin/env python3
"""Golden + negative fixtures for workflow-pack-sdk (PRD 280 gap-326 R16–R19)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.packages.trust import package_content_digest  # noqa: E402
from workflow_pack_sdk import (  # noqa: E402
    KERNEL_COMPAT_TIER,
    confirm_adoption,
    validate_pack,
)

_FIXTURES = _SCRIPTS / "test" / "fixtures" / "workflow-pack-sdk"


def test_golden_valid_pack_passes(repo_root: Path) -> None:
    pack_path = _FIXTURES / "golden" / "valid-pack" / "pack.json"
    exit_code, report = validate_pack(pack_path, repo_root=repo_root)
    assert exit_code == 0
    assert report["verdict"] == "pass"
    assert report["kernelCompatibility"]["tier"] == KERNEL_COMPAT_TIER
    assert "human-action" in report["kernelCompatibility"]["closedNodeKinds"]
    assert report["adoption"]["requiresDigestBoundConfirmation"] is True
    assert report["adoption"]["contentDigest"]
    assert "org extensions" in report["orgExtensionMechanism"]["description"]
    for phase in ("schema", "nodeKinds", "capabilities", "sideEffects", "cycles", "instructionLint"):
        assert report["phases"][phase]["verdict"] == "pass"


def test_negative_invalid_node_kind(repo_root: Path) -> None:
    pack_path = _FIXTURES / "negative" / "invalid-node-kind" / "pack.json"
    exit_code, report = validate_pack(pack_path, repo_root=repo_root)
    assert exit_code == 1
    assert report["verdict"] == "fail"
    codes = {item["code"] for item in report["findings"]}
    assert "node-kind-closed" in codes


def test_negative_cycle(repo_root: Path) -> None:
    pack_path = _FIXTURES / "negative" / "cycle" / "pack.json"
    exit_code, report = validate_pack(pack_path, repo_root=repo_root)
    assert exit_code == 1
    assert report["verdict"] == "fail"
    assert any(item["code"] == "graph-cycle" for item in report["findings"])


def test_negative_instruction_lint_critical(repo_root: Path) -> None:
    pack_path = _FIXTURES / "negative" / "bad-instruction" / "pack.json"
    exit_code, report = validate_pack(pack_path, repo_root=repo_root)
    assert exit_code == 1
    assert report["phases"]["instructionLint"]["verdict"] == "fail"
    assert report["verdict"] == "fail"


def test_ci_safe_without_broker_credentials(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    pack_path = _FIXTURES / "golden" / "valid-pack" / "pack.json"
    exit_code, report = validate_pack(pack_path, repo_root=repo_root)
    assert exit_code == 0
    assert report["verdict"] == "pass"


def test_digest_bound_adoption_gate(repo_root: Path) -> None:
    pack_path = _FIXTURES / "golden" / "valid-pack" / "pack.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    digest = package_content_digest(pack)
    ok_code, ok_payload = confirm_adoption(pack_path, expected_digest=digest, repo_root=repo_root)
    assert ok_code == 0
    assert ok_payload["verdict"] == "pass"
    bad_code, bad_payload = confirm_adoption(
        pack_path,
        expected_digest="0" * 64,
        repo_root=repo_root,
    )
    assert bad_code == 1
    assert bad_payload["cause"] == "digest-mismatch"


def test_golden_report_roundtrip(repo_root: Path, tmp_path: Path) -> None:
    pack_path = _FIXTURES / "golden" / "valid-pack" / "pack.json"
    report_path = tmp_path / "report.json"
    exit_code, _ = validate_pack(pack_path, repo_root=repo_root, report_path=report_path)
    assert exit_code == 0
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["kind"] == "WorkflowPackConformanceReport"
