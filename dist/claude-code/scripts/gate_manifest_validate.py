#!/usr/bin/env python3
"""Fail-closed gate manifest lineage and R9-boundary validator (PRD 065 R20)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from kernel_classification import load_classification, normalize_step

VALID_CLASSES = frozenset({"mandatory", "optional", "advisory"})
VALID_TAXONOMY = frozenset({"ship-chain", "external-chokepoint", "advisory"})
R9_AUTHORIZED_ADDITIONS = frozenset(
    {
        "behavioral-anomaly",
        "build-chain",
        "pre-pr-smoke",
        "decision-log",
        "verification-gate",
    }
)


def _kernel_chokepoint_ids(classification: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in classification.get("kernelChokepoints") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.add(item["id"])
    return ids


def _plan_policy_step_ids(classification: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in classification.get("planPolicySteps") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.add(normalize_step(item["id"]))
    return ids


def _prose_only_bindings(classification: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lineage = classification.get("proseOnlyGateLineage") or {}
    bindings = lineage.get("bindings") if isinstance(lineage, dict) else {}
    if not isinstance(bindings, dict):
        return {}
    return {str(k): v for k, v in bindings.items() if isinstance(v, dict)}


def _gate_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    gates = manifest.get("gates")
    if not isinstance(gates, list):
        raise ValueError("gate manifest gates must be an array")
    out: dict[str, dict[str, Any]] = {}
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        gate_id = gate.get("id")
        if not isinstance(gate_id, str) or not gate_id.strip():
            raise ValueError("gate entry missing id")
        if gate_id in out:
            raise ValueError(f"duplicate gate id: {gate_id}")
        out[gate_id] = gate
    return out


def validate_manifest_shape(manifest: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if manifest.get("version") != 1:
        reasons.append("manifest.version must be 1")
    r9 = manifest.get("r9ProseOnlyGateIds")
    if not isinstance(r9, list) or frozenset(str(x) for x in r9) != R9_AUTHORIZED_ADDITIONS:
        reasons.append("r9ProseOnlyGateIds must match the authorized R9 set")
    floor = manifest.get("kernelFloorGateIds")
    if not isinstance(floor, list) or not floor:
        reasons.append("kernelFloorGateIds must be a non-empty array")
    gate_map = _gate_map(manifest)
    for gate_id, gate in gate_map.items():
        gate_class = str(gate.get("defaultClass") or "").lower()
        if gate_class not in VALID_CLASSES:
            reasons.append(f"{gate_id}: invalid defaultClass {gate_class!r}")
        taxonomy = str(gate.get("taxonomy") or "")
        if taxonomy not in VALID_TAXONOMY:
            reasons.append(f"{gate_id}: invalid taxonomy {taxonomy!r}")
        lineage = gate.get("lineageRef")
        if not isinstance(lineage, dict):
            reasons.append(f"{gate_id}: missing lineageRef")
        entrypoint = gate.get("entrypoint")
        if not isinstance(entrypoint, dict):
            reasons.append(f"{gate_id}: missing entrypoint")
        evidence = gate.get("evidence")
        if not isinstance(evidence, dict):
            reasons.append(f"{gate_id}: missing evidence contract")
        elif not evidence.get("bindingMode"):
            reasons.append(f"{gate_id}: evidence.bindingMode required")
    return reasons


def validate_r9_only_boundary(manifest: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    declared = manifest.get("r9ProseOnlyGateIds")
    if not isinstance(declared, list):
        return ["r9ProseOnlyGateIds missing"]
    declared_set = frozenset(str(x) for x in declared)
    if declared_set != R9_AUTHORIZED_ADDITIONS:
        reasons.append("r9ProseOnlyGateIds diverges from authorized R9 boundary")
    gate_map = _gate_map(manifest)
    for gate_id in declared_set:
        if gate_id not in gate_map:
            reasons.append(f"R9 gate missing from manifest: {gate_id}")
        else:
            lineage = gate_map[gate_id].get("lineageRef") or {}
            if lineage.get("kind") != "prose-only-r9" and gate_id != "verification-gate":
                reasons.append(f"{gate_id}: R9 gate must use prose-only-r9 lineage (except verification-gate kernel binding)")
    for gate_id, gate in gate_map.items():
        lineage = gate.get("lineageRef") or {}
        if lineage.get("kind") == "prose-only-r9" and gate_id not in declared_set:
            reasons.append(f"prose-only-r9 gate outside R9 boundary: {gate_id}")
    return reasons


def validate_lineage_bindings(manifest: dict[str, Any], classification: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    gate_map = _gate_map(manifest)
    chokepoints = _kernel_chokepoint_ids(classification)
    plan_steps = _plan_policy_step_ids(classification)
    prose_bindings = _prose_only_bindings(classification)

    for gate_id, gate in gate_map.items():
        lineage = gate.get("lineageRef") or {}
        kind = lineage.get("kind")
        if kind == "kernel":
            kid = lineage.get("kernelChokepointId")
            if not isinstance(kid, str) or kid not in chokepoints:
                reasons.append(f"{gate_id}: unknown kernel chokepoint {kid!r}")
        elif kind == "guideline":
            step_id = lineage.get("planPolicyStepId")
            if not isinstance(step_id, str) or normalize_step(step_id) not in plan_steps:
                reasons.append(f"{gate_id}: unknown planPolicy step {step_id!r}")
        elif kind == "prose-only-r9":
            binding_key = lineage.get("bindingKey")
            if binding_key not in prose_bindings:
                reasons.append(f"{gate_id}: prose-only-r9 binding missing in kernel-classification: {binding_key!r}")
        else:
            reasons.append(f"{gate_id}: invalid lineageRef.kind {kind!r}")

    for binding_key, binding in prose_bindings.items():
        manifest_gate_id = binding.get("manifestGateId", binding_key)
        if manifest_gate_id not in gate_map:
            reasons.append(f"kernel proseOnlyGateLineage binding {binding_key!r} missing manifest gate {manifest_gate_id!r}")

    return reasons


def validate_ordering_consistency(manifest: dict[str, Any], classification: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    gate_map = _gate_map(manifest)
    prose_bindings = _prose_only_bindings(classification)
    for binding_key, binding in prose_bindings.items():
        gate_id = str(binding.get("manifestGateId", binding_key))
        gate = gate_map.get(gate_id)
        if gate is None:
            continue
        expected_order = binding.get("ordering") if isinstance(binding.get("ordering"), dict) else {}
        actual_order = gate.get("ordering") if isinstance(gate.get("ordering"), dict) else {}
        for key in ("before", "after"):
            if key in expected_order and expected_order.get(key) != actual_order.get(key):
                reasons.append(
                    f"{gate_id}: ordering.{key} drift (manifest={actual_order.get(key)!r}, lineage={expected_order.get(key)!r})"
                )
    return reasons


def validate_kernel_floor_present(manifest: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    gate_map = _gate_map(manifest)
    floor_ids = manifest.get("kernelFloorGateIds") or []
    for gate_id in floor_ids:
        if gate_id not in gate_map:
            reasons.append(f"kernel floor gate missing from manifest: {gate_id}")
            continue
        if str(gate_map[gate_id].get("defaultClass")).lower() != "mandatory":
            reasons.append(f"kernel floor gate must be mandatory: {gate_id}")
    required_floor = {"verification-gate", "check-gate", "gap-check-gate", "secret-scan"}
    if required_floor - {str(x) for x in floor_ids}:
        reasons.append(f"kernelFloorGateIds missing required ids: {sorted(required_floor - set(floor_ids))}")
    return reasons


def validate_manifest(manifest: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    root = (root or Path.cwd()).resolve()
    reasons: list[str] = []
    reasons.extend(validate_manifest_shape(manifest))
    try:
        classification = load_classification(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"verdict": "fail", "error": f"cannot load kernel classification: {exc}"}
    reasons.extend(validate_r9_only_boundary(manifest))
    reasons.extend(validate_lineage_bindings(manifest, classification))
    reasons.extend(validate_ordering_consistency(manifest, classification))
    reasons.extend(validate_kernel_floor_present(manifest))
    if reasons:
        return {"verdict": "fail", "reasons": reasons}
    return {"verdict": "pass", "gateCount": len(_gate_map(manifest))}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate gate manifest lineage")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    manifest_path = args.manifest or (root / "core/sw-reference/gate-manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}))
        return 20
    result = validate_manifest(manifest, root=root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict") == "pass" else 20


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
