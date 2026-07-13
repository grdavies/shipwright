#!/usr/bin/env python3
"""Gate manifest loader with config-resolvable class resolution and kernel floor (PRD 065 R6)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

MANIFEST_REL = Path("core/sw-reference/gate-manifest.json")
VALID_CLASSES = frozenset({"mandatory", "optional", "advisory"})
VALID_TAXONOMY = frozenset({"ship-chain", "external-chokepoint", "advisory"})
CLASS_RANK = {"advisory": 0, "optional": 1, "mandatory": 2}


def repo_root(start: Path | None = None) -> Path:
    return (start or Path.cwd()).resolve()


def manifest_path(root: Path | None = None) -> Path:
    return repo_root(root) / MANIFEST_REL


@lru_cache(maxsize=8)
def _load_raw_manifest(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"gate manifest must be an object: {path}")
    return data


def load_manifest(root: Path | None = None, *, validate: bool = True) -> dict[str, Any]:
    path = manifest_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"missing gate manifest: {path}")
    data = _load_raw_manifest(str(path.resolve()))
    if validate:
        from gate_manifest_validate import validate_manifest

        result = validate_manifest(data, root=repo_root(root))
        if result.get("verdict") != "pass":
            reasons = result.get("reasons") or [result.get("error", "validation failed")]
            raise ValueError(f"gate manifest validation failed: {'; '.join(str(r) for r in reasons)}")
    return data


def kernel_floor_gate_ids(manifest: dict[str, Any] | None = None) -> frozenset[str]:
    if manifest is None:
        manifest = load_manifest(validate=False)
    ids = manifest.get("kernelFloorGateIds")
    if isinstance(ids, list) and ids:
        return frozenset(str(item) for item in ids)
    return frozenset({"verification-gate", "check-gate", "gap-check-gate", "secret-scan"})


def r9_prose_only_gate_ids(manifest: dict[str, Any] | None = None) -> frozenset[str]:
    if manifest is None:
        manifest = load_manifest(validate=False)
    ids = manifest.get("r9ProseOnlyGateIds")
    if not isinstance(ids, list):
        raise ValueError("gate manifest missing r9ProseOnlyGateIds")
    return frozenset(str(item) for item in ids)


def gates_by_id(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
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


def _workflow_config_path(root: Path) -> Path | None:
    for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
        if candidate.is_file():
            return candidate
    return None


def load_gate_class_overrides(root: Path | None = None) -> dict[str, str]:
    root = repo_root(root)
    path = _workflow_config_path(root)
    if path is None:
        return {}
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    gates = config.get("gates")
    if not isinstance(gates, dict):
        return {}
    overrides = gates.get("classOverrides")
    if not isinstance(overrides, dict):
        return {}
    out: dict[str, str] = {}
    for gate_id, gate_class in overrides.items():
        if isinstance(gate_id, str) and isinstance(gate_class, str):
            out[gate_id] = gate_class.strip().lower()
    return out


def default_gate_class(gate: dict[str, Any]) -> str:
    gate_class = str(gate.get("defaultClass") or "optional").strip().lower()
    if gate_class not in VALID_CLASSES:
        raise ValueError(f"invalid defaultClass for gate {gate.get('id')!r}: {gate_class!r}")
    return gate_class


def is_demotion_allowed(
    gate_id: str,
    from_class: str,
    to_class: str,
    *,
    manifest: dict[str, Any] | None = None,
) -> bool:
    manifest = manifest or load_manifest(validate=False)
    floor = kernel_floor_gate_ids(manifest)
    if gate_id in floor:
        return CLASS_RANK.get(to_class, -1) >= CLASS_RANK.get(from_class, -1)
    return True


def resolve_gate_class(
    gate_id: str,
    manifest: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
    overrides: dict[str, str] | None = None,
) -> str:
    manifest = manifest or load_manifest(root)
    gate = gates_by_id(manifest).get(gate_id)
    if gate is None:
        raise KeyError(f"unknown gate id: {gate_id}")
    base = default_gate_class(gate)
    applied = dict(load_gate_class_overrides(root))
    if overrides:
        applied.update({k: v.lower() for k, v in overrides.items()})
    resolved = applied.get(gate_id, base)
    if resolved not in VALID_CLASSES:
        raise ValueError(f"invalid resolved class for {gate_id!r}: {resolved!r}")
    if not is_demotion_allowed(gate_id, base, resolved, manifest=manifest):
        return base
    return resolved


def is_bypass_allowed(gate_id: str, *, manifest: dict[str, Any] | None = None, root: Path | None = None) -> bool:
    resolved = resolve_gate_class(gate_id, manifest=manifest, root=root)
    return resolved in {"optional", "advisory"}


def gate_taxonomy(gate: dict[str, Any]) -> str:
    taxonomy = str(gate.get("taxonomy") or "").strip()
    if taxonomy not in VALID_TAXONOMY:
        raise ValueError(f"invalid taxonomy for gate {gate.get('id')!r}: {taxonomy!r}")
    return taxonomy


def iter_gates_ordered(manifest: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    manifest = manifest or load_manifest()
    gates = manifest.get("gates")
    if not isinstance(gates, list):
        raise ValueError("gate manifest gates must be an array")
    return [gate for gate in gates if isinstance(gate, dict)]


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Gate manifest loader")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--gate", default="")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--no-validate", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = load_manifest(root, validate=not args.no_validate)
    if args.list:
        payload = {
            "verdict": "pass",
            "gates": [
                {
                    "id": gate["id"],
                    "class": resolve_gate_class(gate["id"], manifest, root=root),
                    "taxonomy": gate_taxonomy(gate),
                }
                for gate in iter_gates_ordered(manifest)
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.exit(0)
    if not args.gate:
        print(json.dumps({"verdict": "pass", "gateCount": len(iter_gates_ordered(manifest))}, indent=2))
        sys.exit(0)
    gate_id = args.gate
    gate = gates_by_id(manifest)[gate_id]
    print(
        json.dumps(
            {
                "verdict": "pass",
                "id": gate_id,
                "class": resolve_gate_class(gate_id, manifest, root=root),
                "defaultClass": default_gate_class(gate),
                "taxonomy": gate_taxonomy(gate),
                "bypassAllowed": is_bypass_allowed(gate_id, manifest=manifest, root=root),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
