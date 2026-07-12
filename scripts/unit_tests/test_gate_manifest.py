"""Unit tests for gate manifest loader, lineage validator, and kernel floor (PRD 065 R5, R20)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from gate_manifest import (
    is_bypass_allowed,
    is_demotion_allowed,
    load_manifest,
    resolve_gate_class,
)
from gate_manifest_validate import validate_manifest, validate_r9_only_boundary


def test_manifest_lineage_consistency_passes(repo_root: Path) -> None:
    manifest = load_manifest(repo_root)
    result = validate_manifest(manifest, root=repo_root)
    assert result["verdict"] == "pass"
    assert result["gateCount"] >= 5


def test_divergence_fail_closed(repo_root: Path) -> None:
    manifest = load_manifest(repo_root, validate=False)
    drifted = copy.deepcopy(manifest)
    drifted["gates"][0]["ordering"]["before"] = "sw-ready"
    result = validate_manifest(drifted, root=repo_root)
    assert result["verdict"] == "fail"
    assert any("ordering" in reason for reason in result.get("reasons", []))


def test_r9_only_add_rejection(repo_root: Path) -> None:
    manifest = load_manifest(repo_root, validate=False)
    extra = copy.deepcopy(manifest)
    extra["gates"].append(
        {
            "id": "rogue-gate",
            "taxonomy": "ship-chain",
            "defaultClass": "mandatory",
            "lineageRef": {"kind": "prose-only-r9", "bindingKey": "rogue-gate"},
            "entrypoint": {"script": "scripts/rogue.py", "mechanical": True},
            "evidence": {"bindingMode": "head-exact", "evaluationPoint": "pre-sw-commit", "statusArtifact": "{runDir}/rogue.status.json"},
            "failureRouting": "halt",
            "ordering": {"before": "sw-commit"},
        }
    )
    result = validate_r9_only_boundary(extra)
    assert any("outside R9 boundary" in reason for reason in result)


def test_r9_set_mutation_rejected(repo_root: Path) -> None:
    manifest = load_manifest(repo_root, validate=False)
    mutated = copy.deepcopy(manifest)
    mutated["r9ProseOnlyGateIds"] = list(manifest["r9ProseOnlyGateIds"]) + ["rogue-gate"]
    result = validate_manifest(mutated, root=repo_root)
    assert result["verdict"] == "fail"


def test_kernel_floor_demotion_refused(repo_root: Path) -> None:
    manifest = load_manifest(repo_root, validate=False)
    assert is_demotion_allowed("verification-gate", "mandatory", "optional", manifest=manifest) is False
    assert is_demotion_allowed("check-gate", "mandatory", "advisory", manifest=manifest) is False
    assert is_demotion_allowed("gap-check-gate", "mandatory", "optional", manifest=manifest) is False
    assert is_demotion_allowed("secret-scan", "mandatory", "optional", manifest=manifest) is False


def test_config_demotion_blocked_for_floor(repo_root: Path, tmp_path: Path) -> None:
    manifest = load_manifest(repo_root, validate=False)
    config_path = tmp_path / "workflow.config.json"
    config_path.write_text(
        json.dumps({"gates": {"classOverrides": {"verification-gate": "optional"}}}) + "\n",
        encoding="utf-8",
    )
  # Point loader at temp config by monkeypatching path discovery via cwd symlink is heavy;
  # pass overrides directly for the demotion contract under test.
    resolved = resolve_gate_class(
        "verification-gate",
        manifest,
        overrides={"verification-gate": "optional"},
    )
    assert resolved == "mandatory"


def test_optional_gate_bypass_allowed(repo_root: Path) -> None:
    manifest = load_manifest(repo_root, validate=False)
    assert is_bypass_allowed("sw-simplify", manifest=manifest, root=repo_root) is True
    assert is_bypass_allowed("verification-gate", manifest=manifest, root=repo_root) is False


def test_sw_simplify_agent_classified_outcome_artifact(repo_root: Path) -> None:
    manifest = load_manifest(repo_root, validate=False)
    simplify = next(g for g in manifest["gates"] if g["id"] == "sw-simplify")
    assert simplify.get("agentClassified") is True
    assert simplify["evidence"].get("outcomeArtifact")
