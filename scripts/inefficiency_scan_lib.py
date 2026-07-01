"""Inefficiency scanner — action-linked improvement items (PRD 041 R25/R26)."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import planning_gap_capture as pgc
import wave_deliver as wd

DEFAULT_SLOW_TEST_SECONDS = 30.0
DEFAULT_SLOW_CI_JOB_SECONDS = 300.0


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def load_inefficiency_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not cfg:
        return {"enabled": False}
    ineff = cfg.get("inefficiency")
    if not isinstance(ineff, dict):
        return {"enabled": False}
    thresholds = ineff.get("thresholds") if isinstance(ineff.get("thresholds"), dict) else {}
    allowlist = ineff.get("allowlist") if isinstance(ineff.get("allowlist"), dict) else {}
    return {
        "enabled": ineff.get("enabled") is True,
        "thresholds": {
            "slowTestSeconds": float(thresholds.get("slowTestSeconds", DEFAULT_SLOW_TEST_SECONDS)),
            "slowCiJobSeconds": float(thresholds.get("slowCiJobSeconds", DEFAULT_SLOW_CI_JOB_SECONDS)),
        },
        "allowlist": {
            "manualSteps": list(allowlist.get("manualSteps") or []),
        },
    }


def parse_junit_slow_tests(path: Path, threshold_sec: float) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    items: list[dict[str, Any]] = []
    for case in root.iter("testcase"):
        name = case.get("name") or case.get("classname") or "unknown"
        time_raw = case.get("time")
        if time_raw is None:
            continue
        try:
            duration = float(time_raw)
        except (TypeError, ValueError):
            continue
        if duration >= threshold_sec:
            items.append(
                {
                    "class": "long-single-threaded-test",
                    "test": name,
                    "durationSeconds": duration,
                    "thresholdSeconds": threshold_sec,
                    "action": f"Split or parallelize slow test {name!r} (>{threshold_sec}s)",
                    "nextStep": "Review verify.test parallelism config or split test module",
                }
            )
    return items


def parse_ci_job_timings(
    *,
    timing_path: Path | None,
    gate_json: dict[str, Any] | None,
    threshold_sec: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    notices: list[str] = []
    jobs: list[dict[str, Any]] = []
    if timing_path and timing_path.is_file():
        try:
            doc = json.loads(timing_path.read_text(encoding="utf-8"))
            jobs = list(doc.get("jobs") or [])
        except json.JSONDecodeError:
            notices.append("ci-timing: invalid JSON; skipped slow CI job detection")
            return [], notices
    elif gate_json and isinstance(gate_json.get("checkDurations"), list):
        jobs = list(gate_json["checkDurations"])
    else:
        notices.append("ci-timing: no host-attested timing source; skipped slow CI job detection")
        return [], notices
    items: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        name = str(job.get("name") or job.get("checkId") or "unknown")
        try:
            duration = float(job.get("durationSeconds") or job.get("duration") or 0)
        except (TypeError, ValueError):
            continue
        if duration >= threshold_sec:
            items.append(
                {
                    "class": "slow-ci-job",
                    "job": name,
                    "durationSeconds": duration,
                    "thresholdSeconds": threshold_sec,
                    "action": f"Investigate slow CI job {name!r} (>{threshold_sec}s)",
                    "nextStep": "Profile job steps or split CI matrix",
                }
            )
    return items, notices


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


def detect_serialized_parallelizable(
    root: Path,
    *,
    deliver_state: dict[str, Any],
    tasks_path: Path | None,
    cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    notices: list[str] = []
    plan = deliver_state.get("waveBatchingPlan")
    if not isinstance(plan, dict) or not isinstance(plan.get("waves"), list):
        notices.append("waveBatchingPlan absent; skipped serialized-but-parallelizable detection")
        return [], notices
    ceiling = int(plan.get("parallelCeiling") or (cfg.get("worktree") or {}).get("parallelCeiling") or 1)
    if ceiling <= 1:
        notices.append("parallelCeiling<=1; serialized-but-parallelizable detection not applicable")
        return [], notices
    realized_waves = plan.get("waves") or []
    realized_width_one = all(isinstance(w, list) and len(w) == 1 for w in realized_waves if w)
    if not realized_width_one or len(realized_waves) < 2:
        return [], notices
    phase_ids: list[str] = []
    if tasks_path and tasks_path.is_file():
        content = tasks_path.read_text(encoding="utf-8")
        phases = wd.parse_phases(content)
        phase_ids = [p["id"] for p in phases if isinstance(p.get("id"), str)]
    if not phase_ids:
        phase_ids = [str(i + 1) for i in range(len(realized_waves))]
    simulated = wd.greedy_wave_batches(phase_ids, ceiling)
    simulated_max = max((len(b) for b in simulated), default=1)
    if simulated_max <= 1:
        return [], notices
    return [
        {
            "class": "serialized-but-parallelizable",
            "parallelCeiling": ceiling,
            "realizedWaveCount": len(realized_waves),
            "simulatedMaxWidth": simulated_max,
            "action": "Revisit wave batching — phases executed width-1 despite parallel headroom",
            "nextStep": "Run wave_deliver.py plan validate with proposed batching or split phases (PRD B)",
        }
    ], notices


def detect_repeated_manual_steps(
    run_log_path: Path,
    allowlist: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    notices: list[str] = []
    if not run_log_path.is_file():
        notices.append("run.log absent; skipped repeated manual step detection")
        return [], notices
    commands: list[str] = []
    for line in run_log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        cmd = row.get("command") or row.get("manualCommand")
        if isinstance(cmd, str) and cmd.strip():
            commands.append(cmd.strip())
    if not commands:
        return [], notices
    counts = Counter(commands)
    allow = {a.strip() for a in allowlist if isinstance(a, str)}
    items: list[dict[str, Any]] = []
    for cmd, count in counts.items():
        if count < 2 or cmd in allow:
            continue
        items.append(
            {
                "class": "repeated-manual-step",
                "command": cmd,
                "occurrences": count,
                "action": f"Automate or document recurring manual step ({count}x): {cmd}",
                "nextStep": "Capture as meta-shipwright inbox item or add to orchestrator chain",
            }
        )
    return items, notices


def resolve_junit_path(root: Path, verify_status: dict[str, Any] | None, explicit: Path | None) -> Path | None:
    if explicit and explicit.is_file():
        return explicit
    if verify_status:
        artifacts = verify_status.get("artifacts") or {}
        if isinstance(artifacts, dict):
            junit = artifacts.get("junit") or artifacts.get("junitXml")
            if junit:
                candidate = Path(str(junit))
                if not candidate.is_absolute():
                    candidate = root / candidate
                if candidate.is_file():
                    return candidate
    for candidate in (
        root / "junit.xml",
        root / ".cursor" / "junit.xml",
    ):
        if candidate.is_file():
            return candidate
    return None


def load_benefit_metric(deliver_state: dict[str, Any]) -> dict[str, Any] | None:
    metric = deliver_state.get("benefitMetric")
    return metric if isinstance(metric, dict) else None


def draft_items_to_inbox(root: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    drafted: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        signal_id = f"ineff-{re.sub(r'[^a-z0-9]+', '-', item.get('class', 'item').lower()).strip('-')}-{idx}"
        title = str(item.get("action") or item.get("class") or "Inefficiency item")
        summary = json.dumps(item, ensure_ascii=False, sort_keys=True)
        out = pgc.capture_meta_draft(root, signal_id=signal_id, title=title[:120], summary=summary)
        drafted.append({**item, "signalId": out["signalId"], "inboxPath": out["path"]})
    return drafted


def scan(
    root: Path,
    *,
    cfg: dict[str, Any] | None = None,
    junit_path: Path | None = None,
    gate_json_path: Path | None = None,
    ci_timing_path: Path | None = None,
    deliver_state_path: Path | None = None,
    tasks_path: Path | None = None,
    run_log_path: Path | None = None,
    verify_status_path: Path | None = None,
    draft_to_inbox: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    workflow = cfg if cfg is not None else load_workflow_config(root)
    ineff_cfg = load_inefficiency_config(workflow)
    if not ineff_cfg.get("enabled"):
        return {
            "verdict": "skipped",
            "reason": "inefficiency scanner disabled (set inefficiency.enabled: true)",
            "items": [],
            "notices": [],
            "drafted": [],
        }
    thresholds = ineff_cfg["thresholds"]
    notices: list[str] = []
    items: list[dict[str, Any]] = []

    verify_status: dict[str, Any] | None = None
    if verify_status_path and verify_status_path.is_file():
        try:
            verify_status = json.loads(verify_status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            notices.append("verify status unreadable; skipped per-test timing")

    junit = resolve_junit_path(root, verify_status, junit_path)
    if junit:
        items.extend(parse_junit_slow_tests(junit, thresholds["slowTestSeconds"]))
    else:
        notices.append("junit: no host-attested per-test timing; skipped long-test detection")

    gate_doc: dict[str, Any] | None = None
    if gate_json_path and gate_json_path.is_file():
        try:
            gate_doc = json.loads(gate_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            gate_doc = None
    timing_path = ci_timing_path or (root / ".cursor" / "sw-ci-timing.json")
    ci_items, ci_notices = parse_ci_job_timings(
        timing_path=timing_path,
        gate_json=gate_doc,
        threshold_sec=thresholds["slowCiJobSeconds"],
    )
    items.extend(ci_items)
    notices.extend(ci_notices)

    deliver_state = _load_deliver_state(root, deliver_state_path)
    benefit = load_benefit_metric(deliver_state)
    par_items, par_notices = detect_serialized_parallelizable(
        root,
        deliver_state=deliver_state,
        tasks_path=tasks_path,
        cfg=workflow,
    )
    items.extend(par_items)
    notices.extend(par_notices)

    log_path = run_log_path or (root / ".cursor" / "sw-deliver-runs" / "run.log")
    manual_items, manual_notices = detect_repeated_manual_steps(
        log_path,
        ineff_cfg["allowlist"]["manualSteps"],
    )
    items.extend(manual_items)
    notices.extend(manual_notices)

    drafted: list[dict[str, Any]] = []
    if items and draft_to_inbox:
        drafted = draft_items_to_inbox(root, items)

    return {
        "verdict": "ok",
        "scannedAt": utc_now(),
        "itemCount": len(items),
        "items": items,
        "notices": notices,
        "drafted": drafted,
        "benefitMetricPresent": benefit is not None,
    }
