#!/usr/bin/env python3
"""Context-switch hook — validated HandoffBundle export on harness pause (PRD 280 R10, PRD 333 R3–R4)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from handoff_bundle import (  # noqa: E402
    SUPPORTED_HARNESSES,
    detect_harness,
    export_for_transition,
    repo_root,
)


def _shipwright_state(root: Path) -> dict[str, Any]:
    from handoff_bundle import _shipwright_state as load_state  # noqa: PLC0415

    return load_state(root)

BUNDLE_DIR = Path(".cursor/sw-handoff-bundles")
BUNDLE_FILENAME = "context-switch-latest.json"
REF_FILENAME = "context-switch-latest.ref.json"


def _bundle_paths(root: Path) -> tuple[Path, Path]:
    bundle_dir = root / BUNDLE_DIR
    return bundle_dir / BUNDLE_FILENAME, bundle_dir / REF_FILENAME


def _resolve_destination(source_harness: str, destination_harness: str | None) -> str:
    explicit = (destination_harness or os.environ.get("SW_CONTEXT_SWITCH_DESTINATION") or "").strip()
    if explicit:
        return explicit
    if source_harness == "cursor":
        return "claude-code"
    if source_harness == "claude-code":
        return "cursor"
    return "unknown"


def _persist_bundle_reference(
    root: Path,
    *,
    bundle: dict[str, Any],
    trigger: str,
    source_harness: str,
    destination_harness: str,
) -> dict[str, Any]:
    bundle_path, ref_path = _bundle_paths(root)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    bundle_ref = {
        "bundlePath": str(bundle_path.relative_to(root)),
        "bundleDigest": str(bundle.get("bundleDigest") or ""),
        "phaseSlug": bundle.get("phaseSlug"),
        "exportedAt": bundle.get("exportedAt"),
        "trigger": trigger,
        "sourceHarness": source_harness,
        "destinationHarness": destination_harness,
        "readOnly": True,
    }
    ref_path.write_text(
        json.dumps(bundle_ref, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle_ref


def _build_import_handoff(root: Path, bundle_ref: dict[str, Any], destination_harness: str) -> dict[str, Any]:
    bundle_path = str(bundle_ref.get("bundlePath") or "")
    import_command = f"python3 scripts/handoff_bundle.py import {bundle_path}"
    return {
        "destinationHarness": destination_harness,
        "bundlePath": bundle_path,
        "bundleDigest": bundle_ref.get("bundleDigest"),
        "importCommand": import_command,
        "detail": (
            f"Import on {destination_harness} harness; foreign deliver resume is forbidden. "
            "Use import_cross_harness for transition validation."
        ),
        "crossHarnessImportCommand": (
            f"python3 -c \"from handoff_bundle import import_cross_harness; "
            f"import json; from pathlib import Path; "
            f"print(json.dumps(import_cross_harness(Path('.'), "
            f"Path('{bundle_path}'), destination_harness='{destination_harness}'), indent=2))\""
        ),
    }


def export_on_context_switch(
    repo_root_path: Path,
    *,
    trigger: str = "context-switch",
    destination_harness: str | None = None,
    handoff_degraded: bool | None = None,
) -> dict[str, Any]:
    """Validated export at pause; persist bundle reference; return destination import handoff."""
    root = repo_root(repo_root_path)
    source_harness = detect_harness()
    destination = _resolve_destination(source_harness, destination_harness)
    base_payload = {
        "trigger": trigger,
        "readOnly": True,
        "resumeForbidden": True,
        "sourceHarness": source_harness,
        "destinationHarness": destination,
    }

    if source_harness not in SUPPORTED_HARNESSES:
        return {
            **base_payload,
            "verdict": "fail",
            "error": "handoff:unsupported-source-harness",
            "harness": source_harness,
        }
    if destination not in SUPPORTED_HARNESSES:
        return {
            **base_payload,
            "verdict": "fail",
            "error": "handoff:unsupported-destination-harness",
            "harness": destination,
        }

    degraded = (
        handoff_degraded
        if handoff_degraded is not None
        else os.environ.get("SW_HANDOFF_DEGRADED", "1").strip() not in {"0", "false", "no"}
    )
    unit_id = os.environ.get("SW_UNIT_ID") or None
    phase_slug = os.environ.get("SW_PHASE_SLUG") or None
    run_id = os.environ.get("SW_DELIVER_RUN_ID") or os.environ.get("SW_RUN_ID") or None
    if not unit_id and not phase_slug and not _shipwright_state(root):
        return {
            **base_payload,
            "verdict": "fail",
            "error": "handoff:missing-durable-state",
        }
    result = export_for_transition(
        root,
        source_harness=source_harness,
        destination_harness=destination,
        session_transition="switch",
        unit_id=unit_id,
        phase_slug=phase_slug,
        run_id=run_id,
        handoff_degraded=degraded,
    )
    if result.get("verdict") != "pass" or not isinstance(result.get("bundle"), dict):
        return {
            **base_payload,
            "verdict": str(result.get("verdict") or "fail"),
            "error": result.get("error"),
            "detail": result.get("detail"),
            "resumeCommand": result.get("resumeCommand"),
        }

    bundle = result["bundle"]
    bundle_ref = _persist_bundle_reference(
        root,
        bundle=bundle,
        trigger=trigger,
        source_harness=source_harness,
        destination_harness=destination,
    )
    import_handoff = _build_import_handoff(root, bundle_ref, destination)
    return {
        **base_payload,
        "verdict": "pass",
        "bundleDigest": bundle.get("bundleDigest"),
        "phaseSlug": bundle.get("phaseSlug"),
        "bundleReference": bundle_ref,
        "importHandoff": import_handoff,
        "foreignHarnessResumeForbidden": True,
        "transitionProvenance": bundle.get("transitionProvenance"),
    }


def main(argv: list[str] | None = None) -> int:
    root = Path.cwd()
    trigger = "context-switch"
    destination_harness: str | None = None
    args = list(argv or sys.argv[1:])
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--trigger" and index + 1 < len(args):
            trigger = args[index + 1]
            index += 2
            continue
        if token == "--destination-harness" and index + 1 < len(args):
            destination_harness = args[index + 1]
            index += 2
            continue
        index += 1
    payload = export_on_context_switch(root, trigger=trigger, destination_harness=destination_harness)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    verdict = str(payload.get("verdict") or "")
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
