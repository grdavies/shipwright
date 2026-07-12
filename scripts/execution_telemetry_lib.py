"""Execution telemetry capture and retro advisory suggestions (PRD 064 R29/R30)."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from check_gate_lib import cfg_value, load_workflow_config

TELEMETRY_FILENAME = "execution-telemetry.json"
SUGGESTION_FILENAME = "phase-authoring-suggestion.json"
SCHEMA_VERSION = 1

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "suggestionEveryRuns": 5,
}

PASS_COMMANDS = frozenset({"sw-execute", "sw-stabilize"})


@dataclass(frozen=True)
class TelemetryConfig:
    enabled: bool
    suggestion_every_runs: int


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_telemetry_config(root: Path) -> TelemetryConfig:
    cfg = load_workflow_config(root)
    block = cfg_value(cfg, "executionTelemetry", default={}) or {}
    if not isinstance(block, dict):
        block = {}
    merged = {**DEFAULT_CONFIG, **block}
    every = int(merged.get("suggestionEveryRuns", 5))
    return TelemetryConfig(
        enabled=bool(merged.get("enabled", True)),
        suggestion_every_runs=max(1, every),
    )


def _coerce_int(value: Any, *, default: int | None = 0) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    if isinstance(value, str) and value.strip().isdigit():
        return max(0, int(value.strip()))
    return default


def resolve_run_dir(
    root: Path,
    *,
    phase_slug: str | None = None,
    run_dir: Path | str | None = None,
) -> Path:
    if run_dir:
        path = Path(run_dir)
        if not path.is_absolute():
            path = (root / path).resolve()
        return path
    env_run = os.environ.get("SW_RUN_DIR", "").strip()
    if env_run:
        path = Path(env_run)
        if not path.is_absolute():
            path = (root / path).resolve()
        return path
    slug = (phase_slug or os.environ.get("SW_PHASE_SLUG", "")).strip() or "phase"
    return (root / ".cursor" / "sw-deliver-runs" / slug).resolve()


def telemetry_path(run_dir: Path) -> Path:
    return run_dir / TELEMETRY_FILENAME


def suggestion_path(run_dir: Path) -> Path:
    return run_dir / SUGGESTION_FILENAME


def _empty_store(phase_slug: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "phaseSlug": phase_slug,
        "passes": [],
        "updatedAt": utc_now(),
    }


def load_store(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_passes(path: Path) -> list[dict[str, Any]]:
    store = load_store(path)
    passes = store.get("passes")
    if not isinstance(passes, list):
        return []
    return [item for item in passes if isinstance(item, dict)]


def _normalize_command(command: str) -> str:
    cmd = command.strip().lstrip("/")
    return cmd if cmd in PASS_COMMANDS else command.strip()


def build_pass_record(
    *,
    command: str,
    phase_slug: str,
    iteration_count: int | None,
    blocker_ledger_size: int | None,
    time_to_green_ms: int | None,
    rca_triggered_count: int | None,
    green: bool = False,
) -> dict[str, Any]:
    missing: list[str] = []
    metrics: dict[str, Any] = {
        "iterationCount": _coerce_int(iteration_count, default=0),
        "blockerLedgerSize": _coerce_int(blocker_ledger_size, default=0),
        "rcaTriggeredCount": _coerce_int(rca_triggered_count, default=0),
        "timeToGreenMs": _coerce_int(time_to_green_ms, default=None),
        "green": bool(green),
    }
    for key, raw in (
        ("iterationCount", iteration_count),
        ("blockerLedgerSize", blocker_ledger_size),
        ("rcaTriggeredCount", rca_triggered_count),
        ("timeToGreenMs", time_to_green_ms),
    ):
        if raw is None:
            missing.append(key)
    return {
        "passId": uuid.uuid4().hex,
        "command": _normalize_command(command),
        "phaseSlug": phase_slug,
        "recordedAt": utc_now(),
        "metrics": metrics,
        "missingSignals": missing,
    }


def record_pass(
    root: Path,
    *,
    command: str,
    phase_slug: str | None = None,
    run_dir: Path | str | None = None,
    iteration_count: int | None = None,
    blocker_ledger_size: int | None = None,
    time_to_green_ms: int | None = None,
    rca_triggered_count: int | None = None,
    green: bool = False,
) -> dict[str, Any]:
    """Persist one execute/stabilize pass under the phase run dir (R29)."""
    cfg = load_telemetry_config(root)
    slug = (phase_slug or os.environ.get("SW_PHASE_SLUG", "")).strip() or "phase"
    target = resolve_run_dir(root, phase_slug=slug, run_dir=run_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = telemetry_path(target)

    if not cfg.enabled:
        return {
            "verdict": "skipped",
            "reason": "execution-telemetry-disabled",
            "path": str(path),
        }

    store = load_store(path) or _empty_store(slug)
    record = build_pass_record(
        command=command,
        phase_slug=slug,
        iteration_count=iteration_count,
        blocker_ledger_size=blocker_ledger_size,
        time_to_green_ms=time_to_green_ms,
        rca_triggered_count=rca_triggered_count,
        green=green,
    )
    passes = store.get("passes")
    if not isinstance(passes, list):
        passes = []
    passes.append(record)
    store.update(
        {
            "schemaVersion": SCHEMA_VERSION,
            "phaseSlug": slug,
            "passes": passes,
            "updatedAt": utc_now(),
        }
    )
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "verdict": "ok",
        "action": "record-pass",
        "path": str(path),
        "passId": record["passId"],
        "passCount": len(passes),
        "record": record,
    }


def summarize_passes(passes: list[dict[str, Any]]) -> dict[str, Any]:
    if not passes:
        return {
            "passCount": 0,
            "commands": {},
            "averages": {},
        }
    totals = {
        "iterationCount": 0,
        "blockerLedgerSize": 0,
        "rcaTriggeredCount": 0,
        "timeToGreenMs": 0,
        "timeToGreenSamples": 0,
        "greenPasses": 0,
    }
    by_command: dict[str, int] = {}
    for item in passes:
        cmd = str(item.get("command") or "unknown")
        by_command[cmd] = by_command.get(cmd, 0) + 1
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        totals["iterationCount"] += int(metrics.get("iterationCount") or 0)
        totals["blockerLedgerSize"] += int(metrics.get("blockerLedgerSize") or 0)
        totals["rcaTriggeredCount"] += int(metrics.get("rcaTriggeredCount") or 0)
        if metrics.get("green"):
            totals["greenPasses"] += 1
        ttg = metrics.get("timeToGreenMs")
        if isinstance(ttg, int) and ttg >= 0:
            totals["timeToGreenMs"] += ttg
            totals["timeToGreenSamples"] += 1
    count = len(passes)
    averages = {
        "iterationCount": round(totals["iterationCount"] / count, 2),
        "blockerLedgerSize": round(totals["blockerLedgerSize"] / count, 2),
        "rcaTriggeredCount": round(totals["rcaTriggeredCount"] / count, 2),
    }
    if totals["timeToGreenSamples"]:
        averages["timeToGreenMs"] = round(
            totals["timeToGreenMs"] / totals["timeToGreenSamples"], 2
        )
    return {
        "passCount": count,
        "commands": by_command,
        "totals": totals,
        "averages": averages,
    }


def _recommendations_from_summary(summary: dict[str, Any]) -> list[str]:
    recs: list[str] = []
    averages = summary.get("averages") if isinstance(summary.get("averages"), dict) else {}
    if float(averages.get("iterationCount") or 0) >= 3:
        recs.append(
            "Split phase sub-tasks so each `/sw-execute` pass targets one verifiable file/expected pair."
        )
    if float(averages.get("blockerLedgerSize") or 0) >= 4:
        recs.append(
            "Tighten task **Expected:** lines with explicit verify commands to shrink stabilize blocker ledgers."
        )
    if float(averages.get("timeToGreenMs") or 0) >= 600_000:
        recs.append(
            "Add traced test scenarios in `## Traceability` to reduce time-to-green on later passes."
        )
    if float(averages.get("rcaTriggeredCount") or 0) >= 1:
        recs.append(
            "Document RCA-prone failure signatures in task Expected fields before the next phase freeze."
        )
    if not recs:
        recs.append(
            "Telemetry is within nominal bounds; review pass-level metrics before changing frozen task lists."
        )
    return recs


def should_draft_suggestion(pass_count: int, every: int) -> bool:
    if pass_count <= 0:
        return False
    if pass_count == 1:
        return True
    return pass_count % every == 0


def draft_authoring_suggestion(
    root: Path,
    *,
    phase_slug: str | None = None,
    run_dir: Path | str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Draft advisory phase-authoring-improvement suggestion for human review (R30)."""
    cfg = load_telemetry_config(root)
    slug = (phase_slug or os.environ.get("SW_PHASE_SLUG", "")).strip() or "phase"
    target = resolve_run_dir(root, phase_slug=slug, run_dir=run_dir)
    path = telemetry_path(target)

    if not cfg.enabled:
        return {
            "verdict": "skipped",
            "reason": "execution-telemetry-disabled",
            "autoApply": False,
            "binding": False,
        }

    passes = load_passes(path)
    if not passes:
        return {
            "verdict": "no-telemetry",
            "autoApply": False,
            "binding": False,
            "suggestion": None,
            "passCount": 0,
        }

    pass_count = len(passes)
    if not should_draft_suggestion(pass_count, cfg.suggestion_every_runs):
        return {
            "verdict": "deferred",
            "reason": f"cadence-not-met (every {cfg.suggestion_every_runs} passes)",
            "autoApply": False,
            "binding": False,
            "passCount": pass_count,
        }

    summary = summarize_passes(passes)
    recommendations = _recommendations_from_summary(summary)
    suggestion = {
        "category": "phase-authoring-improvement",
        "title": f"Phase authoring improvements for {slug}",
        "rationale": (
            "Structured execution telemetry from recent `/sw-execute` and `/sw-stabilize` passes "
            "indicates where frozen task authoring can be tightened."
        ),
        "recommendations": recommendations,
        "evidence": summary,
        "humanReviewRequired": True,
    }
    payload = {
        "verdict": "advisory",
        "autoApply": False,
        "binding": False,
        "category": "phase-authoring-improvement",
        "phaseSlug": slug,
        "passCount": pass_count,
        "draftedAt": utc_now(),
        "suggestion": suggestion,
    }
    if persist:
        target.mkdir(parents=True, exist_ok=True)
        out = suggestion_path(target)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["path"] = str(out)
    return payload
