#!/usr/bin/env python3
"""PRD 040 — deterministic phase sizing scorer (read-only, Phase 2+)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import doc_format
import planning_paths
import wave_deliver as wd

DEFAULTS_REL = Path("scripts/test/fixtures/phase-sizing/sizing-defaults.json")

def valid_path(path: str) -> bool:
    if not path or "{" in path or "}" in path or "`" in path or "(" in path:
        return False
    return "/" in path or path.endswith((".md", ".py", ".json", ".sh"))

PATH_LIKE = re.compile(
    r"`([^`]+)`|(?:^|\s)((?:[\w.-]+/)+[\w.*{}-]+(?:/[\w.*{}-]+)*)"
)


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))
    sys.exit(code)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def load_workflow_config(root: Path) -> dict[str, Any]:
    for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
        if candidate.is_file():
            data = load_json(candidate)
            if data:
                return data
    return {}


def load_sizing_config(root: Path) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    sizing = (cfg.get("tasks") or {}).get("sizing")
    if isinstance(sizing, dict) and sizing.get("thresholds"):
        return sizing
    defaults = load_json(root / DEFAULTS_REL)
    thresholds = defaults.get("tasks.sizing.thresholds") or defaults.get("thresholds") or {}
    return {
        "thresholds": thresholds,
        "minPhaseFiles": int(defaults.get("tasks.sizing.minPhaseFiles", 1)),
        "minPhaseScenarios": int(defaults.get("tasks.sizing.minPhaseScenarios", 0)),
        "maxPhaseCount": int(defaults.get("tasks.sizing.maxPhaseCount", 99)),
    }


def has_traceability_section(text: str) -> bool:
    return any(
        tok.kind == doc_format.TokenKind.SECTION_HEADING
        and tok.text.strip().lower() == "## traceability"
        for tok in doc_format.tokenize(text).tokens
    )


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


def traceability_by_phase(text: str, phase_ids: list[str]) -> dict[str, int | None]:
    if not has_traceability_section(text):
        return {pid: None for pid in phase_ids}
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


def extract_relevant_files(text: str) -> list[str]:
    _, body = doc_format.split_frontmatter(text)
    lines = body.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if re.match(r"^##\s+Relevant Files\s*$", line, re.I):
            start = idx + 1
            break
    if start is None:
        return []
    paths: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        for match in PATH_LIKE.finditer(line):
            raw = match.group(1) or match.group(2)
            if raw and ("/" in raw or raw.endswith((".md", ".py", ".json", ".sh"))):
                norm = wd.normalize_file_path(raw)
                if valid_path(norm):
                    paths.append(norm)
    return sorted(set(paths))



def phase_section_text(text: str, phase_id: str) -> str:
    body = doc_format.split_frontmatter(text)[1]
    sections = re.split(r"^###\s+(\d+)\.", body, flags=re.MULTILINE)
    for idx in range(1, len(sections), 2):
        if sections[idx] == phase_id:
            return sections[idx + 1] if idx + 1 < len(sections) else ""
    return ""


def phase_prose_paths(text: str, phase_id: str) -> list[str]:
    body = doc_format.split_frontmatter(text)[1]
    sections = re.split(r"^###\s+(\d+)\.", body, flags=re.MULTILINE)
    chunk = ""
    for idx in range(1, len(sections), 2):
        if sections[idx] == phase_id:
            chunk = sections[idx + 1] if idx + 1 < len(sections) else ""
            break
    paths: list[str] = []
    for line in chunk.splitlines():
        if "**File:**" in line:
            continue
        for match in PATH_LIKE.finditer(line):
            raw = match.group(1) or match.group(2)
            if raw and "/" in raw:
                norm = wd.normalize_file_path(raw)
                if valid_path(norm):
                    paths.append(norm)
    return sorted(set(paths))


def scope_under_declared(declared: list[str], relevant: list[str], prose: list[str]) -> list[str]:
    declared_set = set(declared)
    return [path for path in sorted(set(relevant) | set(prose)) if path not in declared_set]


def signal_tier(value: int | None, thresholds: dict[str, int]) -> int:
    if value is None:
        return 0
    small = int(thresholds.get("small", 0))
    medium = int(thresholds.get("medium", small))
    if value <= small:
        return 0
    if value <= medium:
        return 1
    return 2


def classify_size(metrics: dict[str, int | None], sizing: dict[str, Any]) -> tuple[str, bool, bool]:
    thresholds = sizing.get("thresholds") or {}
    tiers = [
        signal_tier(metrics.get("filesTouched"), thresholds.get("filesTouched") or {}),
        signal_tier(metrics.get("distinctDirs"), thresholds.get("distinctDirs") or {}),
        signal_tier(metrics.get("subTaskCount"), thresholds.get("subTaskCount") or {}),
        signal_tier(metrics.get("depFanOut"), thresholds.get("depFanOut") or {}),
    ]
    scen = metrics.get("traceabilityScenarios")
    if scen is not None:
        tiers.append(signal_tier(scen, thresholds.get("traceabilityScenarios") or {}))
    peak = max(tiers) if tiers else 0
    size = ("small", "medium", "large")[min(peak, 2)]
    over_threshold = peak >= 2
    below_floor = int(metrics.get("filesTouched") or 0) < int(sizing.get("minPhaseFiles", 1))
    if scen is not None:
        below_floor = below_floor or int(scen) < int(sizing.get("minPhaseScenarios", 0))
    return size, over_threshold, below_floor


def separable_sets_for_phase(paths: list[str], root: Path) -> list[list[str]]:
    if len(paths) <= 1:
        return [paths] if paths else []
    serialized = planning_paths.contention_serialized_defaults(planning_paths.load_planning_dirs(root))
    parent: dict[str, str] = {path: path for path in paths}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        rl, rr = find(left), find(right)
        if rl != rr:
            parent[rr] = rl

    for i, left in enumerate(paths):
        for right in paths[i + 1 :]:
            contends, _ = wd.paths_contend(left, right, serialized, root)
            if contends:
                union(left, right)
    groups: dict[str, list[str]] = {}
    for path in paths:
        groups.setdefault(find(path), []).append(path)
    return [sorted(group) for group in groups.values()]


def score_task_list(root: Path, task_list: Path, sizing: dict[str, Any]) -> dict[str, Any]:
    text = task_list.read_text(encoding="utf-8")
    phases = wd.parse_phases(text)
    phase_ids = [phase["id"] for phase in phases]
    dep_rows = wd.parse_phase_dependencies(text)
    phase_files = wd.parse_phase_files(text)
    edges, dep_notices = wd.deps_to_edges(phases, dep_rows, phase_files, root)
    subtasks = subtask_counts_by_phase(text, phase_ids)
    scenarios = traceability_by_phase(text, phase_ids)
    relevant = extract_relevant_files(text)
    notices: list[str] = list(dep_notices)
    if not has_traceability_section(text):
        notices.append("traceability section absent; traceabilityScenarios=null per phase")
    per_phase: list[dict[str, Any]] = []
    for phase in phases:
        pid = phase["id"]
        normalized = sorted({wd.normalize_file_path(item) for item in phase_files.get(pid, []) if valid_path(wd.normalize_file_path(item))})
        phase_text = phase_section_text(text, pid)
        phase_relevant = [path for path in relevant if path in phase_text or any(part in phase_text for part in path.split("/"))]
        under = scope_under_declared(normalized, phase_relevant, phase_prose_paths(text, pid))
        metrics = {
            "filesTouched": len(normalized),
            "distinctDirs": distinct_dir_count(normalized),
            "subTaskCount": subtasks.get(pid, 0),
            "traceabilityScenarios": scenarios.get(pid),
            "depFanOut": dep_fan_out(edges, pid),
        }
        size, over_threshold, below_floor = classify_size(metrics, sizing)
        entry: dict[str, Any] = {
            "phase": pid,
            "title": phase["title"],
            **metrics,
            "size": size,
            "overThreshold": over_threshold,
            "belowFloor": below_floor,
            "separableSets": separable_sets_for_phase(normalized, root),
        }
        if under:
            entry["scopeUnderDeclared"] = under
            notices.append(
                f"phase {pid}: scopeUnderDeclared ({len(under)} implied path(s) not in **File:** lines)"
            )
        per_phase.append(entry)
    return {
        "verdict": "pass",
        "action": "phase-sizing-score",
        "taskList": str(task_list.relative_to(root)).replace("\\", "/"),
        "frozen": wd.parse_frontmatter(text).get("frozen", "").lower() == "true",
        "phaseCount": len(per_phase),
        "notices": notices,
        "phases": per_phase,
        "config": {
            "minPhaseFiles": sizing.get("minPhaseFiles"),
            "minPhaseScenarios": sizing.get("minPhaseScenarios"),
            "maxPhaseCount": sizing.get("maxPhaseCount"),
        },
    }


def cmd_score(root: Path, args: argparse.Namespace) -> int:
    task_list = Path(args.task_list)
    if not task_list.is_absolute():
        task_list = (root / task_list).resolve()
    if not task_list.is_file():
        emit({"verdict": "fail", "error": f"task list not found: {task_list}"}, 2)
    emit(score_task_list(root, task_list, load_sizing_config(root)))


def cmd_check_frozen(root: Path, args: argparse.Namespace) -> int:
    task_list = Path(args.task_list)
    if not task_list.is_absolute():
        task_list = (root / task_list).resolve()
    text = task_list.read_text(encoding="utf-8")
    if wd.parse_frontmatter(text).get("frozen", "").lower() == "true" and not args.allow_frozen:
        emit(
            {
                "verdict": "fail",
                "action": "phase-sizing-check-frozen",
                "error": "frozen task list — print-only / fail-closed (R30)",
                "taskList": str(task_list.relative_to(root)).replace("\\", "/"),
            },
            20,
        )
    emit(score_task_list(root, task_list, load_sizing_config(root)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phase_sizing.py")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="Score phases in a task list (read-only JSON)")
    score.add_argument("task_list", help="Path to task-list markdown")
    frozen = sub.add_parser("check-frozen", help="Fail-closed score on frozen lists (R30)")
    frozen.add_argument("task_list", help="Path to task-list markdown")
    frozen.add_argument("--allow-frozen", action="store_true", help="Fixture-only bypass")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "score":
        return cmd_score(root, args)
    if args.command == "check-frozen":
        return cmd_check_frozen(root, args)
    emit({"verdict": "fail", "error": f"unknown command {args.command!r}"}, 2)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
