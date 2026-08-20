#!/usr/bin/env python3
"""Repro-first evidence gate for /sw-debug before RCA hypotheses (PRD 323 R16–R21)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

PRODUCTION_SIGNAL_TYPES = frozenset({"sentry", "deploy_log", "user_report"})
DEV_TIME_SIGNAL_TYPES = frozenset({"test_failure", "build_failure", "verify_failure"})

MECHANICAL_REPRO_STEPS: tuple[dict[str, Any], ...] = (
    {
        "id": "repro_command",
        "label": "Run narrowest repro command (red)",
        "required": True,
        "path": "mechanical",
    },
    {
        "id": "repro_minimize",
        "label": "Minimize repro surface",
        "required": False,
        "path": "mechanical",
    },
    {
        "id": "repro_instrument",
        "label": "Instrument failing path",
        "required": False,
        "path": "mechanical",
    },
)

EVIDENCE_ACQUISITION_CHECKLIST: tuple[dict[str, Any], ...] = (
    {
        "id": "logs",
        "label": "Fetch relevant logs",
        "required": True,
        "path": "evidence",
    },
    {
        "id": "traces",
        "label": "Fetch traces or spans",
        "required": True,
        "path": "evidence",
    },
    {
        "id": "replay_bundle",
        "label": "Collect replay bundle",
        "required": False,
        "path": "evidence",
    },
    {
        "id": "sentry_enrich",
        "label": "Sentry MCP enrich (read-only)",
        "required": True,
        "path": "evidence",
    },
)


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def signal_type(signal: dict[str, Any]) -> str:
    return str(signal.get("type") or signal.get("signalType") or "").strip()


def signal_class(signal: dict[str, Any]) -> str:
    st = signal_type(signal)
    if st in DEV_TIME_SIGNAL_TYPES:
        return "dev-time"
    if st in PRODUCTION_SIGNAL_TYPES:
        return "production"
    return "unknown"


def checklist_metadata(*, signal_class_name: str) -> dict[str, Any]:
    if signal_class_name == "dev-time":
        items = list(MECHANICAL_REPRO_STEPS)
    elif signal_class_name == "production":
        items = list(EVIDENCE_ACQUISITION_CHECKLIST)
    else:
        items = []
    return {
        "signalClass": signal_class_name,
        "checklist": items,
        "evidenceBundleFields": [
            "signalClass",
            "checklistState",
            "artifactPaths",
            "complete",
        ],
    }


def _resume_command(*, signal_path: str | None, state_path: str | None) -> str:
    parts = ["python3 scripts/debug_repro_gate.py run"]
    if signal_path:
        parts.append(f"--signal {signal_path}")
    if state_path:
        parts.append(f"--state {state_path}")
    return " ".join(parts)


def _item_states(state: dict[str, Any], bucket: str) -> dict[str, str]:
    raw = state.get(bucket) if isinstance(state.get(bucket), dict) else {}
    return {str(k): str(v) for k, v in raw.items()}


def _checklist_view(
    items: tuple[dict[str, Any], ...],
    states: dict[str, str],
) -> list[dict[str, Any]]:
    view: list[dict[str, Any]] = []
    for item in items:
        status = states.get(item["id"], "pending")
        view.append({**item, "status": status})
    return view


def _pending_required(items: tuple[dict[str, Any], ...], states: dict[str, str]) -> list[str]:
    pending: list[str] = []
    for item in items:
        if not item.get("required"):
            continue
        status = states.get(item["id"], "pending")
        if status in ("pending", "in_progress"):
            pending.append(str(item["id"]))
    return pending


def _exhausted_required(items: tuple[dict[str, Any], ...], states: dict[str, str]) -> bool:
    required = [item for item in items if item.get("required")]
    if not required:
        return False
    for item in required:
        status = states.get(item["id"], "pending")
        if status in ("pending", "in_progress", "complete"):
            return False
    return True


def _dev_time_pass(signal: dict[str, Any], state: dict[str, Any]) -> bool:
    repro = state.get("repro") if isinstance(state.get("repro"), dict) else {}
    if repro.get("reproConfirmed") is True:
        return bool(repro.get("reproCommand"))
    if signal.get("reproConfirmed") is True and signal.get("reproCommand"):
        return True
    return False


def evaluate_dev_time(
    signal: dict[str, Any],
    state: dict[str, Any] | None = None,
    *,
    signal_path: str | None = None,
    state_path: str | None = None,
) -> dict[str, Any]:
    state = state or {}
    repro_states = _item_states(state, "mechanicalRepro")
    checklist = _checklist_view(MECHANICAL_REPRO_STEPS, repro_states)
    if _dev_time_pass(signal, state):
        return {
            "verdict": "pass",
            "signalClass": "dev-time",
            "path": "mechanical-repro",
            "checklist": checklist,
            "repro": {
                "reproCommand": (state.get("repro") or {}).get("reproCommand")
                or signal.get("reproCommand"),
                "reproConfirmed": True,
            },
        }

    pending = _pending_required(MECHANICAL_REPRO_STEPS, repro_states)
    if pending:
        return {
            "verdict": "blocked",
            "cause": "repro-pending",
            "signalClass": "dev-time",
            "path": "mechanical-repro",
            "checklist": checklist,
            "pending": pending,
            "resumeCommand": _resume_command(signal_path=signal_path, state_path=state_path),
        }

    if _exhausted_required(MECHANICAL_REPRO_STEPS, repro_states):
        return {
            "verdict": "exhausted",
            "cause": "repro-exhausted",
            "signalClass": "dev-time",
            "path": "mechanical-repro",
            "checklist": checklist,
            "resumeCommand": _resume_command(signal_path=signal_path, state_path=state_path),
        }

    return {
        "verdict": "blocked",
        "cause": "repro-not-established",
        "signalClass": "dev-time",
        "path": "mechanical-repro",
        "checklist": checklist,
        "pending": pending or ["repro_command"],
        "resumeCommand": _resume_command(signal_path=signal_path, state_path=state_path),
    }


def _production_pass(state: dict[str, Any]) -> bool:
    bundle = state.get("evidenceBundle") if isinstance(state.get("evidenceBundle"), dict) else {}
    if bundle.get("complete") is True:
        return True
    checklist = bundle.get("checklistState")
    if isinstance(checklist, dict) and bundle.get("signalClass"):
        required_ids = [item["id"] for item in EVIDENCE_ACQUISITION_CHECKLIST if item.get("required")]
        if required_ids and all(checklist.get(item_id) == "complete" for item_id in required_ids):
            paths = bundle.get("artifactPaths")
            return isinstance(paths, list) and len(paths) > 0
    return False


def evaluate_production(
    signal: dict[str, Any],
    state: dict[str, Any] | None = None,
    *,
    signal_path: str | None = None,
    state_path: str | None = None,
) -> dict[str, Any]:
    state = state or {}
    evidence_states = _item_states(state, "evidenceAcquisition")
    bundle = state.get("evidenceBundle") if isinstance(state.get("evidenceBundle"), dict) else {}
    checklist = _checklist_view(EVIDENCE_ACQUISITION_CHECKLIST, evidence_states)
    artifact_paths = bundle.get("artifactPaths") if isinstance(bundle.get("artifactPaths"), list) else []
    evidence_bundle = {
        "signalClass": signal_class(signal),
        "checklistState": {item["id"]: item["status"] for item in checklist},
        "artifactPaths": artifact_paths,
        "complete": _production_pass(state),
    }

    if _production_pass(state):
        return {
            "verdict": "pass",
            "signalClass": "production",
            "path": "evidence-acquisition",
            "checklist": checklist,
            "evidenceBundle": evidence_bundle,
        }

    pending = _pending_required(EVIDENCE_ACQUISITION_CHECKLIST, evidence_states)
    if pending:
        return {
            "verdict": "blocked",
            "cause": "evidence-pending",
            "signalClass": "production",
            "path": "evidence-acquisition",
            "checklist": checklist,
            "pending": pending,
            "evidenceBundle": evidence_bundle,
            "resumeCommand": _resume_command(signal_path=signal_path, state_path=state_path),
        }

    if _exhausted_required(EVIDENCE_ACQUISITION_CHECKLIST, evidence_states):
        return {
            "verdict": "exhausted",
            "cause": "evidence-exhausted",
            "signalClass": "production",
            "path": "evidence-acquisition",
            "checklist": checklist,
            "evidenceBundle": evidence_bundle,
            "resumeCommand": _resume_command(signal_path=signal_path, state_path=state_path),
        }

    return {
        "verdict": "blocked",
        "cause": "evidence-not-acquired",
        "signalClass": "production",
        "path": "evidence-acquisition",
        "checklist": checklist,
        "pending": pending or [item["id"] for item in EVIDENCE_ACQUISITION_CHECKLIST if item.get("required")],
        "evidenceBundle": evidence_bundle,
        "resumeCommand": _resume_command(signal_path=signal_path, state_path=state_path),
    }


def evaluate_gate(
    signal: dict[str, Any],
    state: dict[str, Any] | None = None,
    *,
    hypotheses: list[Any] | None = None,
    signal_path: str | None = None,
    state_path: str | None = None,
) -> dict[str, Any]:
    cls = signal_class(signal)
    if cls == "dev-time":
        result = evaluate_dev_time(signal, state, signal_path=signal_path, state_path=state_path)
    elif cls == "production":
        result = evaluate_production(signal, state, signal_path=signal_path, state_path=state_path)
    else:
        result = {
            "verdict": "blocked",
            "cause": "unknown-signal-type",
            "signalClass": cls,
            "signalType": signal_type(signal),
            "resumeCommand": _resume_command(signal_path=signal_path, state_path=state_path),
        }

    if hypotheses and result.get("verdict") != "pass":
        result = {
            **result,
            "hypothesisGate": "refused",
            "cause": "hypothesis-before-gate",
        }
    return result


def exit_code_for_verdict(verdict: str) -> int:
    if verdict == "pass":
        return 0
    if verdict in ("blocked", "exhausted"):
        return 20
    return 20


def load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repro-first debug gate (PRD 323 R16–R21)")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    meta = sub.add_parser("checklist-metadata", help="Return checklist metadata for a signal class")
    meta.add_argument("--signal-class", choices=("dev-time", "production", "unknown"))

    run = sub.add_parser("run", help="Evaluate repro-first gate")
    run.add_argument("--signal", required=True)
    run.add_argument("--state")
    run.add_argument("--hypotheses")
    run.add_argument("--out")

    args = parser.parse_args(argv)

    if args.command == "checklist-metadata":
        emit(checklist_metadata(signal_class_name=args.signal_class or "unknown"))

    signal = load_json(args.signal)
    state = load_json(args.state)
    hypotheses_raw = load_json(args.hypotheses) if args.hypotheses else None
    hypotheses = None
    if isinstance(hypotheses_raw, dict):
        raw = hypotheses_raw.get("hypotheses")
        hypotheses = raw if isinstance(raw, list) else None
    elif isinstance(hypotheses_raw, list):
        hypotheses = hypotheses_raw

    result = evaluate_gate(
        signal,
        state,
        hypotheses=hypotheses,
        signal_path=args.signal,
        state_path=args.state,
    )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    code = exit_code_for_verdict(str(result.get("verdict") or ""))
    emit(result, code)
    return code


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
