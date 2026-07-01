#!/usr/bin/env python3
"""PRD 040 Phase 0 — frozen task-list corpus calibration (read-only, SC6)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import doc_format
import planning_paths
import wave_deliver as wd

FIXTURE_REL = Path("scripts/test/fixtures/phase-sizing")
BASELINE_NAME = "baseline-distribution.json"
MANIFEST_NAME = "corpus-manifest.json"
DEFAULTS_NAME = "sizing-defaults.json"


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def percentile(values: list[int | float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    k = (len(ordered) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    if lo == hi:
        return float(ordered[lo])
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def distribution(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "min": 0, "p10": 0, "p25": 0, "p50": 0, "p75": 0, "p90": 0, "max": 0}
    return {
        "count": len(values),
        "min": min(values),
        "p10": round(percentile(values, 10), 2),
        "p25": round(percentile(values, 25), 2),
        "p50": round(percentile(values, 50), 2),
        "p75": round(percentile(values, 75), 2),
        "p90": round(percentile(values, 90), 2),
        "max": max(values),
    }


def discover_frozen_task_lists(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.glob("docs/prds/**/tasks-*.md")):
        if not path.is_file():
            continue
        fm = wd.parse_frontmatter(path.read_text(encoding="utf-8"))
        if fm.get("frozen", "").lower() == "true":
            found.append(path)
    return found


def subtask_counts_by_phase(text: str, phase_ids: list[str]) -> dict[str, int]:
    body = doc_format.split_frontmatter(text)[1]
    counts = {pid: 0 for pid in phase_ids}
    sections = re.split(r"^###\s+(\d+)\.", body, flags=re.MULTILINE)
    for idx in range(1, len(sections), 2):
        phase_id = sections[idx]
        chunk = sections[idx + 1] if idx + 1 < len(sections) else ""
        if phase_id not in counts:
            continue
        counts[phase_id] += len(
            re.findall(r"^-\s+\[[ x]\]\s+\d+\.\d+", chunk, flags=re.MULTILINE)
        )
    return counts


def traceability_by_phase(text: str, phase_ids: list[str]) -> dict[str, int]:
    counts = {pid: 0 for pid in phase_ids}
    for row in doc_format.extract_traceability_rows(text):
        match = re.match(r"^(\d+)", row.get("task", ""))
        if match and match.group(1) in counts:
            counts[match.group(1)] += 1
    return counts


def distinct_dir_count(paths: list[str]) -> int:
    if not paths:
        return 0
    dirs: set[str] = set()
    for raw in paths:
        parent = str(Path(raw).parent)
        dirs.add(parent if parent and parent != "." else ".")
    return len(dirs)


def dep_fan_out(edges: list[dict[str, str]], phase_id: str) -> int:
    return sum(1 for edge in edges if edge.get("from") == phase_id)


def measure_task_list(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    phases = wd.parse_phases(text)
    phase_ids = [phase["id"] for phase in phases]
    dep_rows = wd.parse_phase_dependencies(text)
    phase_files = wd.parse_phase_files(text)
    edges, dep_notices = wd.deps_to_edges(phases, dep_rows, phase_files, root)
    contention = planning_paths.contention_default(root)
    waves, edges, injected, contention_notices, phase_files = wd.apply_contention(
        text, phases, edges, contention, root
    )
    subtasks = subtask_counts_by_phase(text, phase_ids)
    scenarios = traceability_by_phase(text, phase_ids)
    wave_widths = [len(wave) for wave in waves]
    per_phase: list[dict[str, Any]] = []
    for phase in phases:
        pid = phase["id"]
        normalized = [wd.normalize_file_path(item) for item in phase_files.get(pid, [])]
        unique_files = sorted(set(normalized))
        per_phase.append(
            {
                "phaseId": pid,
                "title": phase["title"],
                "filesTouched": len(unique_files),
                "distinctDirs": distinct_dir_count(unique_files),
                "subTaskCount": subtasks.get(pid, 0),
                "traceabilityScenarios": scenarios.get(pid, 0),
                "depFanOut": dep_fan_out(edges, pid),
            }
        )
    return {
        "taskList": rel,
        "phaseCount": len(phase_ids),
        "waveCount": len(waves),
        "maxWaveWidth": max(wave_widths) if wave_widths else 0,
        "waveWidths": wave_widths,
        "injectedEdgeCount": len(injected),
        "notices": dep_notices + contention_notices,
        "phases": per_phase,
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    files: list[int] = []
    dirs: list[int] = []
    subtasks: list[int] = []
    scenarios: list[int] = []
    fanout: list[int] = []
    wave_widths: list[int] = []
    phase_counts: list[int] = []
    for record in records:
        phase_counts.append(int(record["phaseCount"]))
        wave_widths.extend(int(w) for w in record.get("waveWidths", []))
        for phase in record.get("phases", []):
            files.append(int(phase["filesTouched"]))
            dirs.append(int(phase["distinctDirs"]))
            subtasks.append(int(phase["subTaskCount"]))
            scenarios.append(int(phase["traceabilityScenarios"]))
            fanout.append(int(phase["depFanOut"]))
    return {
        "taskListCount": len(records),
        "phaseSampleCount": len(files),
        "distributions": {
            "filesTouched": distribution(files),
            "distinctDirs": distribution(dirs),
            "subTaskCount": distribution(subtasks),
            "traceabilityScenarios": distribution(scenarios),
            "depFanOut": distribution(fanout),
            "waveWidth": distribution(wave_widths),
            "phasesPerTaskList": distribution(phase_counts),
        },
        "zeroTraceabilityPhases": sum(1 for value in scenarios if value == 0),
    }


def derive_defaults(summary: dict[str, Any]) -> dict[str, Any]:
    dist = summary["distributions"]

    def pair(key: str) -> tuple[int, int]:
        block = dist[key]
        return int(block["p50"]), int(block["p75"])

    files_small, files_medium = pair("filesTouched")
    scen_small, scen_medium = pair("traceabilityScenarios")
    sub_small, sub_medium = pair("subTaskCount")
    dir_small, dir_medium = pair("distinctDirs")
    fan_small, fan_medium = pair("depFanOut")
    max_phases = int(dist["phasesPerTaskList"]["max"])
    return {
        "tasks.sizing.thresholds": {
            "filesTouched": {"small": files_small, "medium": files_medium},
            "traceabilityScenarios": {"small": scen_small, "medium": scen_medium},
            "subTaskCount": {"small": sub_small, "medium": sub_medium},
            "distinctDirs": {"small": dir_small, "medium": dir_medium},
            "depFanOut": {"small": fan_small, "medium": fan_medium},
        },
        "tasks.sizing.minPhaseFiles": max(1, int(dist["filesTouched"]["p10"])),
        "tasks.sizing.minPhaseScenarios": max(0, int(dist["traceabilityScenarios"]["p10"])),
        "tasks.sizing.maxPhaseCount": max(max_phases, int(dist["phasesPerTaskList"]["p90"]) + 2),
        "derivation": {
            "method": "corpus-percentiles",
            "smallMediumCut": "p50/p75 per signal",
            "floors": "p10 for minPhase*",
            "maxPhaseCount": "max observed phases per task list, floored at p90+2",
        },
    }


def cmd_audit(root: Path, args: argparse.Namespace) -> int:
    task_lists = discover_frozen_task_lists(root)
    if not task_lists:
        emit({"verdict": "fail", "error": "no frozen task lists found"}, 2)
    records = [
        measure_task_list(root, str(path.relative_to(root)).replace("\\", "/"))
        for path in task_lists
    ]
    summary = aggregate(records)
    defaults = derive_defaults(summary)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "version": 1,
        "generatedAt": generated_at,
        "taskLists": [record["taskList"] for record in records],
        "taskListCount": len(records),
    }
    baseline = {
        "version": 1,
        "generatedAt": generated_at,
        "summary": summary,
        "records": records,
        "defaults": defaults,
    }
    fixture_dir = root / FIXTURE_REL
    if not args.stdout_only:
        fixture_dir.mkdir(parents=True, exist_ok=True)
        (fixture_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (fixture_dir / BASELINE_NAME).write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
        (fixture_dir / DEFAULTS_NAME).write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8")
    emit(
        {
            "verdict": "pass",
            "action": "phase-sizing-corpus-audit",
            "taskListCount": len(records),
            "phaseSampleCount": summary["phaseSampleCount"],
            "defaults": defaults,
            "outputs": {
                "manifest": str(FIXTURE_REL / MANIFEST_NAME),
                "baseline": str(FIXTURE_REL / BASELINE_NAME),
                "defaults": str(FIXTURE_REL / DEFAULTS_NAME),
            },
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phase_sizing_corpus.py")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit", help="Audit frozen corpus and write baseline fixtures")
    audit.add_argument("--stdout-only", action="store_true", help="Skip writing fixture files")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "audit":
        return cmd_audit(root, args)
    emit({"verdict": "fail", "error": f"unknown command {args.command!r}"}, 2)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
