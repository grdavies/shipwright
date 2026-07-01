#!/usr/bin/env python3
"""PRD 040 — deterministic phase sizing scorer (read-only, Phase 2+)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import doc_format
import planning_paths
import wave_deliver as wd

DEFAULTS_REL = Path("scripts/test/fixtures/phase-sizing/sizing-defaults.json")
ADVISORY_HEADING = "## Sizing & Split Suggestions"

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


def load_parallel_ceiling(root: Path) -> int:
    cfg = load_workflow_config(root)
    worktree = cfg.get("worktree") or {}
    return int(worktree.get("parallelCeiling", 4))


def has_advisory_block(text: str) -> bool:
    return bool(re.search(rf"^{re.escape(ADVISORY_HEADING)}\s*$", text, re.MULTILINE | re.IGNORECASE))


def strip_advisory_block(text: str) -> str:
    if not has_advisory_block(text):
        return text
    pattern = rf"^{re.escape(ADVISORY_HEADING)}\s*$[\s\S]*?(?=^##\s|\Z)"
    stripped = re.sub(pattern, "", text, count=1, flags=re.MULTILINE)
    return stripped.rstrip() + "\n"


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


def serialized_defaults(root: Path) -> list[str]:
    return planning_paths.contention_serialized_defaults(planning_paths.load_planning_dirs(root))


def expanded_phase_paths(
    phase_id: str,
    phase_files: dict[str, list[str]],
    content: str,
    root: Path,
) -> list[str]:
    expanded = planning_paths.expand_generator_contention_paths(phase_files, content, root)
    return sorted(expanded.get(phase_id, []))


def contention_pairs(paths: list[str], root: Path) -> list[tuple[str, str]]:
    serialized = serialized_defaults(root)
    pairs: list[tuple[str, str]] = []
    for i, left in enumerate(paths):
        for right in paths[i + 1 :]:
            contends, _ = wd.paths_contend(left, right, serialized, root)
            if contends:
                pairs.append((left, right))
    return pairs


def separable_sets_for_paths(paths: list[str], root: Path) -> list[list[str]]:
    if not paths:
        return []
    if len(paths) == 1:
        return [paths]
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

    for left, right in contention_pairs(paths, root):
        union(left, right)
    groups: dict[str, list[str]] = {}
    for path in paths:
        groups.setdefault(find(path), []).append(path)
    return [sorted(group) for group in groups.values()]


def separable_sets_for_phase(paths: list[str], content: str, phase_id: str, root: Path) -> list[list[str]]:
    expanded = expanded_phase_paths(phase_id, {phase_id: paths}, content, root)
    return separable_sets_for_paths(expanded, root)


def _sort_phase_key(item: str) -> tuple[int, str | int]:
    return (0, int(item)) if str(item).isdigit() else (1, str(item))


def _has_path(edges: list[dict[str, str]], src: str, dst: str) -> bool:
    adj: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adj[edge["from"]].append(edge["to"])
    seen: set[str] = set()
    stack = [src]
    while stack:
        node = stack.pop()
        if node == dst:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adj.get(node, []))
    return False


def _unit_id(phase_id: str, index: int) -> str:
    return f"{phase_id}{chr(ord('a') + index)}"


def _mandatory_internal_edges(units: list[dict[str, Any]], root: Path) -> list[dict[str, str]]:
    serialized = serialized_defaults(root)
    edges: list[dict[str, str]] = []
    existing: set[tuple[str, str]] = set()
    for i, left in enumerate(units):
        for right in units[i + 1 :]:
            contends = False
            for fl in left["files"]:
                for fr in right["files"]:
                    hit, _ = wd.paths_contend(fl, fr, serialized, root)
                    if hit:
                        contends = True
                        break
                if contends:
                    break
            if contends:
                pair = (left["id"], right["id"])
                if pair not in existing:
                    edges.append({"from": left["id"], "to": right["id"], "kind": "mandatory-contention"})
                    existing.add(pair)
    for i in range(len(units) - 1):
        pair = (units[i]["id"], units[i + 1]["id"])
        if pair not in existing:
            edges.append({"from": units[i]["id"], "to": units[i + 1]["id"], "kind": "serial"})
            existing.add(pair)
    return edges


def _external_edges_for_split(
    phase_id: str,
    unit_ids: list[str],
    edges: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not unit_ids:
        return []
    first_unit = unit_ids[0]
    last_unit = unit_ids[-1]
    external: list[dict[str, str]] = []
    for edge in edges:
        if edge.get("from") == phase_id and edge.get("to") != phase_id:
            external.append({"from": last_unit, "to": edge["to"], "kind": "split-fan-out"})
        elif edge.get("to") == phase_id and edge.get("from") != phase_id:
            external.append({"from": edge["from"], "to": first_unit, "kind": "split-fan-in"})
    return external


def _contention_closure_matches_parent(
    parent_paths: list[str],
    units: list[dict[str, Any]],
    internal_edges: list[dict[str, str]],
    root: Path,
) -> bool:
    parent_sets = [sorted(s) for s in separable_sets_for_paths(parent_paths, root)]
    unit_sets = [sorted(u["files"]) for u in units]
    if sorted(parent_sets) != sorted(unit_sets):
        return False
    serialized = serialized_defaults(root)
    for i, left in enumerate(units):
        for right in units[i + 1 :]:
            cross_contends = any(
                wd.paths_contend(fl, fr, serialized, root)[0]
                for fl in left["files"]
                for fr in right["files"]
            )
            if cross_contends and not (
                _has_path(internal_edges, left["id"], right["id"])
                or _has_path(internal_edges, right["id"], left["id"])
            ):
                return False
    return True


def propose_phase_split(
    phase_id: str,
    paths: list[str],
    content: str,
    root: Path,
    over_threshold: bool,
    separable_sets: list[list[str]],
    phases: list[dict[str, str]],
    edges: list[dict[str, str]],
    sizing: dict[str, Any],
    below_floor: bool = False,
) -> dict[str, Any] | None:
    if below_floor:
        return None
    if not (len(separable_sets) > 1 or over_threshold):
        return None
    if len(separable_sets) <= 1:
        return None
    parent_paths = expanded_phase_paths(phase_id, {phase_id: paths}, content, root)
    units = [
        {"id": _unit_id(phase_id, idx), "files": sorted(file_set)}
        for idx, file_set in enumerate(sorted(separable_sets, key=lambda s: s[0] if s else ""))
    ]
    if len(units) < 2:
        return None
    projected_phase_count = len(phases) - 1 + len(units)
    if projected_phase_count > int(sizing.get("maxPhaseCount", 99)):
        return {
            "phase": phase_id,
            "rejected": True,
            "reason": "maxPhaseCount exceeded",
            "units": units,
        }
    internal_edges = _mandatory_internal_edges(units, root)
    if not _contention_closure_matches_parent(parent_paths, units, internal_edges, root):
        return {
            "phase": phase_id,
            "rejected": True,
            "reason": "contention closure differs from parent",
            "units": units,
        }
    unit_ids = [unit["id"] for unit in units]
    external_edges = _external_edges_for_split(phase_id, unit_ids, edges)
    split = {
        "phase": phase_id,
        "rejected": False,
        "units": units,
        "internalEdges": internal_edges,
        "externalEdges": external_edges,
    }
    return split


def _contention_only_internal_edges(internal_edges: list[dict[str, str]]) -> list[dict[str, str]]:
    return [dict(edge) for edge in internal_edges if edge.get("kind") == "mandatory-contention"]


def _build_split_simulation(
    split: dict[str, Any],
    phases: list[dict[str, str]],
    edges: list[dict[str, str]],
    phase_files: dict[str, list[str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, list[str]]]:
    phase_id = split["phase"]
    simulated_phases: list[dict[str, str]] = []
    simulated_files: dict[str, list[str]] = {}
    for phase in phases:
        if phase["id"] == phase_id:
            for unit in split.get("units") or []:
                simulated_phases.append(
                    {
                        "id": unit["id"],
                        "title": f"{phase['title']} ({unit['id']})",
                        "slug": unit["id"],
                    }
                )
                simulated_files[unit["id"]] = list(unit.get("files") or [])
        else:
            simulated_phases.append(dict(phase))
            simulated_files[phase["id"]] = list(phase_files.get(phase["id"], []))
    split_ids = {phase_id}
    simulated_edges: list[dict[str, str]] = []
    for edge in edges:
        if edge.get("from") in split_ids or edge.get("to") in split_ids:
            continue
        simulated_edges.append(dict(edge))
    simulated_edges.extend(_contention_only_internal_edges(split.get("internalEdges") or []))
    simulated_edges.extend(dict(edge) for edge in split.get("externalEdges") or [])
    return simulated_phases, simulated_edges, simulated_files


def _safe_inject_contention_edges(
    phase_ids: list[str],
    declared_edges: list[dict[str, str]],
    phase_files: dict[str, list[str]],
    root: Path,
) -> tuple[list[dict[str, str]] | None, list[dict[str, str]], list[str], str | None]:
    contention = planning_paths.contention_default(root)
    serialized = list(
        contention.get("serialized")
        or planning_paths.contention_serialized_defaults(planning_paths.load_planning_dirs(root))
    )
    notices: list[str] = []
    injected: list[dict[str, str]] = []
    existing = {(e["from"], e["to"]) for e in declared_edges}
    all_edges = [dict(e) for e in declared_edges]
    phase_id_set = set(phase_ids)
    graph_nodes = set(phase_ids)
    for edge in declared_edges:
        graph_nodes.add(edge["from"])
        graph_nodes.add(edge["to"])
    declared_waves = _safe_assign_waves(sorted(graph_nodes, key=_sort_phase_key), declared_edges)
    if declared_waves is None:
        return None, injected, notices, "dependency cycle detected before contention injection"

    for wave in declared_waves:
        phase_in_wave = [phase for phase in wave if phase in phase_id_set]
        if len(phase_in_wave) < 2:
            continue
        for left in phase_in_wave:
            for right in phase_in_wave:
                if left.isdigit() and right.isdigit():
                    skip = int(left) >= int(right)
                else:
                    skip = left >= right
                if skip:
                    continue
                files_left = phase_files.get(left, [])
                files_right = phase_files.get(right, [])
                overlap = ""
                contend = False
                for fl in files_left:
                    for fr in files_right:
                        hit, detail = wd.paths_contend(fl, fr, serialized, root)
                        if hit:
                            contend = True
                            overlap = detail or f"{fl} ⟷ {fr}"
                            break
                    if contend:
                        break
                if not contend:
                    continue
                if _has_path(declared_edges, right, left):
                    return (
                        None,
                        injected,
                        notices,
                        "contention-cycle: shared-file overlap opposes declared ordering",
                    )
                if (left, right) in existing or _has_path(all_edges, left, right):
                    continue
                edge = {"from": left, "to": right, "kind": "contention"}
                injected.append(edge)
                all_edges.append(edge)
                existing.add((left, right))
                notices.append(f"contention: phases {left} and {right} serialized ({overlap})")

    nodes = sorted(graph_nodes, key=_sort_phase_key)
    if wd.graph_has_cycle(nodes, all_edges):
        return None, injected, notices, "contention-cycle: combined declared + contention graph has a cycle"
    return all_edges, injected, notices, None


def _simulate_split_waves(
    split: dict[str, Any],
    phases: list[dict[str, str]],
    edges: list[dict[str, str]],
    phase_files: dict[str, list[str]],
    root: Path,
) -> tuple[list[list[str]] | None, list[dict[str, str]], list[str], str | None]:
    simulated_phases, simulated_edges, simulated_files = _build_split_simulation(
        split, phases, edges, phase_files
    )
    phase_ids = [phase["id"] for phase in simulated_phases]
    if wd.graph_has_cycle(phase_ids, simulated_edges):
        return None, simulated_edges, [], "dependency cycle in split simulation"
    all_edges, injected, notices, error = _safe_inject_contention_edges(
        phase_ids, simulated_edges, simulated_files, root
    )
    if error:
        return None, simulated_edges, notices, error
    assert all_edges is not None
    waves = _safe_assign_waves(phase_ids, all_edges)
    if waves is None:
        return None, all_edges, notices, "unable to assign waves after contention simulation"
    return waves, all_edges, notices + [f"contention injected {len(injected)} edge(s)"], None


def evaluate_split_preflight(
    split: dict[str, Any],
    phases: list[dict[str, str]],
    edges: list[dict[str, str]],
    phase_files: dict[str, list[str]],
    root: Path,
    ceiling: int,
    sizing: dict[str, Any],
) -> dict[str, Any]:
    if split.get("rejected") and split.get("reason") not in {
        "maxPhaseCount exceeded",
        "contention closure differs from parent",
    }:
        return {"verdict": "skip", "reason": split.get("reason", "split already rejected")}
    units = split.get("units") or []
    if len(units) < 2:
        return {"verdict": "reject", "reason": "split has fewer than two units"}

    baseline_ids = [phase["id"] for phase in phases]
    baseline_waves = _safe_assign_waves(baseline_ids, edges) or [baseline_ids]
    baseline_max_width = max(len(wave) for wave in baseline_waves) if baseline_waves else 0
    baseline_phase_count = len(baseline_ids)

    waves, _, notices, error = _simulate_split_waves(split, phases, edges, phase_files, root)
    if error:
        return {"verdict": "reject", "reason": error, "notices": notices}
    assert waves is not None
    max_width = max(len(wave) for wave in waves) if waves else 0
    projected_phase_count = len(baseline_ids) - 1 + len(units)
    max_phase_count = int(sizing.get("maxPhaseCount", 99))
    if projected_phase_count > max_phase_count:
        return {
            "verdict": "reject",
            "reason": "maxPhaseCount exceeded",
            "projectedPhaseCount": projected_phase_count,
            "maxPhaseCount": max_phase_count,
            "notices": notices,
        }

    unit_ids = {unit["id"] for unit in units}
    parallel_units_in_wave = max(len([item for item in wave if item in unit_ids]) for wave in waves)
    if parallel_units_in_wave <= 1 and len(units) > 1:
        return {
            "verdict": "reject",
            "reason": "width-1 collapse",
            "maxWaveWidth": max_width,
            "notices": notices,
        }

    if projected_phase_count <= baseline_phase_count:
        return {
            "verdict": "reject",
            "reason": "does not raise independent-phase count",
            "projectedPhaseCount": projected_phase_count,
            "baselinePhaseCount": baseline_phase_count,
            "notices": notices,
        }

    if max_width > ceiling:
        return {
            "verdict": "reject",
            "reason": "exceeds parallelCeiling",
            "maxWaveWidth": max_width,
            "parallelCeiling": ceiling,
            "notices": notices,
        }

    return {
        "verdict": "pass",
        "projectedPhaseCount": projected_phase_count,
        "baselinePhaseCount": baseline_phase_count,
        "maxWaveWidth": max_width,
        "baselineMaxWaveWidth": baseline_max_width,
        "parallelCeiling": ceiling,
        "waves": waves,
        "notices": notices,
    }



def _safe_assign_waves(items: list[str], edges: list[dict[str, str]]) -> list[list[str]] | None:
    graph_nodes = set(items)
    for edge in edges:
        graph_nodes.add(edge["from"])
        graph_nodes.add(edge["to"])
    items_list = sorted(graph_nodes, key=_sort_phase_key)
    if wd.graph_has_cycle(items_list, edges):
        return None
    deps = {i: {e["from"] for e in edges if e["to"] == i} for i in items_list}
    waves: list[list[str]] = []
    remaining = set(items_list)
    while remaining:
        wave = sorted([i for i in remaining if not (deps[i] & remaining)], key=_sort_phase_key)
        if not wave:
            return None
        waves.append(wave)
        remaining -= set(wave)
    return waves


def cost_estimate(
    phases: list[dict[str, str]],
    edges: list[dict[str, str]],
    split_suggestions: list[dict[str, Any]],
) -> dict[str, int]:
    phase_ids = [phase["id"] for phase in phases]
    simulated_ids: list[str] = []
    simulated_edges: list[dict[str, str]] = []
    split_by_phase = {item["phase"]: item for item in split_suggestions if not item.get("rejected")}
    for pid in phase_ids:
        split = split_by_phase.get(pid)
        if split:
            simulated_ids.extend(unit["id"] for unit in split["units"])
            simulated_edges.extend(split.get("internalEdges") or [])
            simulated_edges.extend(split.get("externalEdges") or [])
        else:
            simulated_ids.append(pid)
    for edge in edges:
        if edge.get("from") in split_by_phase or edge.get("to") in split_by_phase:
            continue
        simulated_edges.append(dict(edge))
    waves = _safe_assign_waves(simulated_ids, simulated_edges) or [simulated_ids]
    projected_waves = len(waves)
    merge_gates = projected_waves
    return {
        "projectedWaves": projected_waves,
        "mergeGates": merge_gates,
        "estimate": projected_waves * merge_gates,
    }


def render_advisory_markdown(score: dict[str, Any], root: Path) -> str:
    splits = [
        phase["splitSuggestion"]
        for phase in score.get("phases", [])
        if phase.get("splitSuggestion") and not phase["splitSuggestion"].get("rejected")
    ]
    cost = cost_estimate(
        [{"id": phase["phase"], "title": phase.get("title", "")} for phase in score.get("phases", [])],
        [],
        splits,
    )
    lines = [
        ADVISORY_HEADING,
        "",
        "> Draft-only advisory (stripped at freeze). Generated by `phase_sizing.py`.",
        "",
        "### Cost estimate",
        "",
        f"- Projected waves: {cost['projectedWaves']}",
        f"- Merge gates: {cost['mergeGates']}",
        f"- Structural cost (waves × gates): {cost['estimate']}",
        "",
    ]
    if not splits:
        lines.append("_No split suggestions at this time._")
        lines.append("")
        return "\n".join(lines)
    lines.append("### Split suggestions")
    lines.append("")
    for split in splits:
        phase_id = split["phase"]
        lines.append(f"#### Phase {phase_id}")
        lines.append("")
        for unit in split.get("units", []):
            files = ", ".join(f"`{path}`" for path in unit.get("files", []))
            lines.append(f"- **{unit['id']}**: {files}")
        internal = split.get("internalEdges") or []
        if internal:
            lines.append("")
            lines.append("Internal edges:")
            for edge in internal:
                lines.append(f"- `{edge['from']}` → `{edge['to']}` ({edge.get('kind', 'edge')})")
        external = split.get("externalEdges") or []
        if external:
            lines.append("")
            lines.append("External edges preserved:")
            for edge in external:
                lines.append(f"- `{edge['from']}` → `{edge['to']}` ({edge.get('kind', 'edge')})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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
        separable_sets = separable_sets_for_phase(normalized, text, pid, root)
        entry: dict[str, Any] = {
            "phase": pid,
            "title": phase["title"],
            **metrics,
            "size": size,
            "overThreshold": over_threshold,
            "belowFloor": below_floor,
            "separableSets": separable_sets,
        }
        if under:
            entry["scopeUnderDeclared"] = under
            notices.append(
                f"phase {pid}: scopeUnderDeclared ({len(under)} implied path(s) not in **File:** lines)"
            )
        split = propose_phase_split(
            pid,
            normalized,
            text,
            root,
            over_threshold,
            separable_sets,
            phases,
            edges,
            sizing,
            below_floor,
        )
        if split is not None:
            ceiling = load_parallel_ceiling(root)
            split["preflight"] = evaluate_split_preflight(
                split,
                phases,
                edges,
                phase_files,
                root,
                ceiling,
                sizing,
            )
            if not split.get("rejected") and split["preflight"].get("verdict") == "reject":
                split["rejected"] = True
                split["reason"] = split["preflight"].get("reason", "preflight rejected")
            entry["splitSuggestion"] = split
        per_phase.append(entry)
    split_suggestions = [
        phase["splitSuggestion"]
        for phase in per_phase
        if phase.get("splitSuggestion")
    ]
    return {
        "verdict": "pass",
        "action": "phase-sizing-score",
        "taskList": rel_task_list(task_list, root),
        "frozen": wd.parse_frontmatter(text).get("frozen", "").lower() == "true",
        "phaseCount": len(per_phase),
        "notices": notices,
        "phases": per_phase,
        "costEstimate": cost_estimate(phases, edges, split_suggestions),
        "config": {
            "minPhaseFiles": sizing.get("minPhaseFiles"),
            "minPhaseScenarios": sizing.get("minPhaseScenarios"),
            "maxPhaseCount": sizing.get("maxPhaseCount"),
        },
    }


def rel_task_list(task_list: Path, root: Path) -> str:
    try:
        return str(task_list.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(task_list)


def resolve_task_list(root: Path, raw: str) -> Path:
    task_list = Path(raw)
    if not task_list.is_absolute():
        task_list = (root / task_list).resolve()
    return task_list




def cmd_preflight(root: Path, args: argparse.Namespace) -> int:
    task_list = resolve_task_list(root, args.task_list)
    if not task_list.is_file():
        emit({"verdict": "fail", "error": f"task list not found: {task_list}"}, 2)
    sizing = load_sizing_config(root)
    score = score_task_list(root, task_list, sizing)
    preflights = [
        {
            "phase": phase["phase"],
            "preflight": (phase.get("splitSuggestion") or {}).get("preflight"),
        }
        for phase in score.get("phases", [])
        if phase.get("splitSuggestion")
    ]
    emit(
        {
            "verdict": "pass",
            "action": "phase-sizing-preflight",
            "taskList": rel_task_list(task_list, root),
            "parallelCeiling": load_parallel_ceiling(root),
            "preflights": preflights,
            "costEstimate": score.get("costEstimate"),
        }
    )

def cmd_score(root: Path, args: argparse.Namespace) -> int:
    task_list = resolve_task_list(root, args.task_list)
    if not task_list.is_file():
        emit({"verdict": "fail", "error": f"task list not found: {task_list}"}, 2)
    emit(score_task_list(root, task_list, load_sizing_config(root)))


def cmd_check_frozen(root: Path, args: argparse.Namespace) -> int:
    task_list = resolve_task_list(root, args.task_list)
    text = task_list.read_text(encoding="utf-8")
    if has_advisory_block(text) and not getattr(args, "allow_advisory", False):
        emit(
            {
                "verdict": "fail",
                "action": "phase-sizing-check-frozen",
                "error": "advisory block present — strip before freeze (R30)",
                "taskList": rel_task_list(task_list, root),
            },
            20,
        )
    if wd.parse_frontmatter(text).get("frozen", "").lower() == "true" and not args.allow_frozen:
        emit(
            {
                "verdict": "fail",
                "action": "phase-sizing-check-frozen",
                "error": "frozen task list — print-only / fail-closed (R30)",
                "taskList": rel_task_list(task_list, root),
            },
            20,
        )
    emit(score_task_list(root, task_list, load_sizing_config(root)))


def cmd_advisory(root: Path, args: argparse.Namespace) -> int:
    task_list = resolve_task_list(root, args.task_list)
    if not task_list.is_file():
        emit({"verdict": "fail", "error": f"task list not found: {task_list}"}, 2)
    score = score_task_list(root, task_list, load_sizing_config(root))
    print(render_advisory_markdown(score, root), end="")
    return 0


def cmd_strip_advisory(root: Path, args: argparse.Namespace) -> int:
    task_list = resolve_task_list(root, args.task_list)
    if not task_list.is_file():
        emit({"verdict": "fail", "error": f"task list not found: {task_list}"}, 2)
    text = task_list.read_text(encoding="utf-8")
    stripped = strip_advisory_block(text)
    if args.inplace:
        task_list.write_text(stripped, encoding="utf-8")
    else:
        print(stripped, end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phase_sizing.py")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight", help="Preflight split simulations (read-only JSON)")
    preflight.add_argument("task_list", help="Path to task-list markdown")
    score = sub.add_parser("score", help="Score phases in a task list (read-only JSON)")
    score.add_argument("task_list", help="Path to task-list markdown")
    frozen = sub.add_parser("check-frozen", help="Fail-closed score on frozen lists (R30)")
    frozen.add_argument("task_list", help="Path to task-list markdown")
    frozen.add_argument("--allow-frozen", action="store_true", help="Fixture-only bypass")
    frozen.add_argument("--allow-advisory", action="store_true", help="Fixture-only bypass")
    advisory = sub.add_parser("advisory", help="Render sizing advisory markdown")
    advisory.add_argument("task_list", help="Path to task-list markdown")
    strip = sub.add_parser("strip-advisory", help="Strip advisory block from a task list")
    strip.add_argument("task_list", help="Path to task-list markdown")
    strip.add_argument("--inplace", action="store_true", help="Rewrite task list in place")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "preflight":
        return cmd_preflight(root, args)
    if args.command == "score":
        return cmd_score(root, args)
    if args.command == "check-frozen":
        return cmd_check_frozen(root, args)
    if args.command == "advisory":
        return cmd_advisory(root, args)
    if args.command == "strip-advisory":
        return cmd_strip_advisory(root, args)
    emit({"verdict": "fail", "error": f"unknown command {args.command!r}"}, 2)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
