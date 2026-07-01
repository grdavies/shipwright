"""Loop-health aggregation — downstream-cost metrics (PRD 041 R29)."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sw_state_write_lib as writer


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return {}


def load_loop_health_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not cfg:
        return {"enabled": False, "staleInboxDays": 14}
    block = cfg.get("loopHealth")
    if not isinstance(block, dict):
        return {"enabled": False, "staleInboxDays": 14}
    stale = block.get("staleInboxDays")
    if not isinstance(stale, int) or stale < 1:
        stale = 14
    return {"enabled": block.get("enabled") is True, "staleInboxDays": stale}


def _load_deliver_state(root: Path, deliver_state_path: Path | None) -> dict[str, Any]:
    candidates: list[Path] = []
    if deliver_state_path:
        candidates.append(deliver_state_path)
    candidates.extend(
        [
            root / ".cursor" / "sw-deliver-runs" / "sw-deliver-state.json",
            root / ".cursor" / "sw-deliver-state.json",
        ]
    )
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return {}


def _int_metric(value: Any, default: int = 0) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0:
        return int(value)
    return default


def aggregate_review_effort(deliver_state: dict[str, Any]) -> dict[str, int]:
    benefit = deliver_state.get("benefitMetric")
    stabilize_count = 0
    if isinstance(benefit, dict):
        entries = benefit.get("stabilizeReentries")
        if isinstance(entries, list):
            stabilize_count = len(entries)
    review_rounds = _int_metric(deliver_state.get("reviewRounds"))
    if review_rounds == 0:
        review_rounds = _int_metric(deliver_state.get("reviewRoundCount"))
    if review_rounds == 0 and isinstance(deliver_state.get("stabilizePassId"), dict):
        review_rounds = len(deliver_state["stabilizePassId"])
    return {"reviewRounds": review_rounds, "stabilizeReentries": stabilize_count}


def aggregate_rework_defect(deliver_state: dict[str, Any], incidents: dict[str, Any]) -> dict[str, int]:
    reopened = _int_metric(deliver_state.get("reopenedPhases"))
    if reopened == 0 and isinstance(deliver_state.get("reopenedPhaseIds"), list):
        reopened = len(deliver_state["reopenedPhaseIds"])
    reverts = _int_metric(incidents.get("count")) if incidents.get("status") == "known" else 0
    if reverts == 0:
        reverts = _int_metric(deliver_state.get("postMergeReverts"))
    return {"reopenedPhases": reopened, "postMergeReverts": reverts}


def _host_loop_health_incidents(root: Path) -> dict[str, Any] | None:
    host_sh = root / "host.sh"
    if not host_sh.is_file():
        return None
    proc = subprocess.run(
        ["bash", str(host_sh), "loop-health-incidents"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def load_incidents(root: Path) -> dict[str, Any]:
    host_doc = _host_loop_health_incidents(root)
    if host_doc is not None:
        items = host_doc.get("items") if isinstance(host_doc.get("items"), list) else []
        return {
            "status": "known",
            "count": _int_metric(host_doc.get("count"), len(items)),
            "source": "host.sh:loop-health-incidents",
            "items": items,
        }
    fallback = root / ".cursor" / "sw-post-merge-incidents.json"
    if fallback.is_file():
        try:
            data = json.loads(fallback.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            items = data.get("items") if isinstance(data.get("items"), list) else []
            return {
                "status": "known",
                "count": _int_metric(data.get("count"), len(items)),
                "source": str(fallback.relative_to(root)) if fallback.is_relative_to(root) else str(fallback),
                "items": items,
            }
    return {"status": "unknown"}


def _failure_recurrence_map(root: Path) -> dict[str, int]:
    path = writer.resolve_store_path(root, "failure-signatures")
    doc = writer.load_store(path)
    if not doc:
        return {}
    out: dict[str, int] = {}
    for rec in doc.get("records") or []:
        if not isinstance(rec, dict):
            continue
        key = rec.get("key")
        if not isinstance(key, dict):
            continue
        token = json.dumps(key, sort_keys=True)
        out[token] = _int_metric(rec.get("count"), 1)
    return out


def _inbox_signal_recurrence(signal_id: str, failure_map: dict[str, int]) -> int:
    if signal_id in failure_map:
        return failure_map[signal_id]
    return 1


def rank_meta_inbox(
    root: Path,
    *,
    review_rounds: int,
    stale_inbox_days: int,
) -> list[dict[str, Any]]:
    inbox_dir = root / ".cursor" / "sw-meta-inbox"
    if not inbox_dir.is_dir():
        return []
    failure_map = _failure_recurrence_map(root)
    now = datetime.now(timezone.utc)
    ranked: list[dict[str, Any]] = []
    for path in sorted(inbox_dir.glob("*.json")):
        try:
            draft = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(draft, dict):
            continue
        if draft.get("destination") != "meta-shipwright":
            continue
        signal_id = str(draft.get("signalId") or path.stem)
        recurrence = _int_metric(draft.get("recurrence"), _inbox_signal_recurrence(signal_id, failure_map))
        score = float(recurrence * max(review_rounds, 1))
        captured_at = str(draft.get("capturedAt") or "")
        stale = False
        ts = parse_ts(captured_at)
        if ts and now - ts > timedelta(days=stale_inbox_days):
            stale = True
        ranked.append(
            {
                "signalId": signal_id,
                "title": str(draft.get("title") or ""),
                "score": score,
                "recurrence": recurrence,
                "reviewRounds": review_rounds,
                "capturedAt": captured_at,
                "stale": stale,
            }
        )
    ranked.sort(key=lambda r: (-r["score"], r["signalId"]))
    return ranked


def build_record(
    root: Path,
    *,
    cfg: dict[str, Any] | None = None,
    deliver_state_path: Path | None = None,
) -> dict[str, Any]:
    workflow = cfg if cfg is not None else load_workflow_config(root)
    lh_cfg = load_loop_health_config(workflow)
    deliver_state = _load_deliver_state(root, deliver_state_path)
    review = aggregate_review_effort(deliver_state)
    incidents = load_incidents(root)
    rework = aggregate_rework_defect(deliver_state, incidents)
    inbox = rank_meta_inbox(
        root,
        review_rounds=review["reviewRounds"],
        stale_inbox_days=lh_cfg["staleInboxDays"],
    )
    return {
        "version": 1,
        "recordedAt": utc_now(),
        "diagnosticOnly": True,
        "gating": False,
        "metrics": {
            "reviewEffort": review,
            "reworkDefect": rework,
            "incidents": incidents,
            "inboxRanking": inbox,
        },
    }


def surface_summary(record: dict[str, Any]) -> dict[str, Any]:
    metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
    review = metrics.get("reviewEffort") if isinstance(metrics.get("reviewEffort"), dict) else {}
    rework = metrics.get("reworkDefect") if isinstance(metrics.get("reworkDefect"), dict) else {}
    incidents = metrics.get("incidents") if isinstance(metrics.get("incidents"), dict) else {}
    inbox = metrics.get("inboxRanking") if isinstance(metrics.get("inboxRanking"), list) else []
    stale = [r for r in inbox if isinstance(r, dict) and r.get("stale")]
    return {
        "diagnosticOnly": True,
        "gating": False,
        "reviewEffort": review,
        "reworkDefect": rework,
        "incidentsStatus": incidents.get("status", "unknown"),
        "topInbox": inbox[:5],
        "staleInboxCount": len(stale),
        "message": (
            "Loop-health is diagnostic-only (no gating). "
            f"Incidents: {incidents.get('status', 'unknown')}."
        ),
    }


def aggregate(
    root: Path,
    *,
    cfg: dict[str, Any] | None = None,
    deliver_state_path: Path | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    workflow = cfg if cfg is not None else load_workflow_config(root)
    lh_cfg = load_loop_health_config(workflow)
    if not lh_cfg.get("enabled"):
        return {
            "verdict": "skipped",
            "reason": "loopHealth.enabled is false",
            "gating": False,
            "diagnosticOnly": True,
        }
    record = build_record(root, cfg=workflow, deliver_state_path=deliver_state_path)
    path: str | None = None
    if persist:
        try:
            out_path = writer.cmd_write(root, store="loop-health", data=record)
            path = str(out_path)
        except writer.StateWriteError as exc:
            return {
                "verdict": "fail",
                "error": str(exc),
                "halt": exc.halt,
                "gating": False,
                "diagnosticOnly": True,
            }
    return {
        "verdict": "ok",
        "record": record,
        "summary": surface_summary(record),
        "path": path,
        "gating": False,
        "diagnosticOnly": True,
    }


def stale_inbox_alerts(root: Path, *, cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    workflow = cfg if cfg is not None else load_workflow_config(root)
    lh_cfg = load_loop_health_config(workflow)
    if not lh_cfg.get("enabled"):
        return []
    record = build_record(root, cfg=workflow)
    alerts: list[dict[str, Any]] = []
    for row in record["metrics"]["inboxRanking"]:
        if row.get("stale"):
            alerts.append(
                {
                    "signalId": row["signalId"],
                    "title": row.get("title", ""),
                    "capturedAt": row.get("capturedAt", ""),
                    "staleInboxDays": lh_cfg["staleInboxDays"],
                    "message": f"Meta-inbox draft stale (>{lh_cfg['staleInboxDays']}d): {row['signalId']}",
                }
            )
    return alerts

