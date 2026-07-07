#!/usr/bin/env python3
"""Execute-tier task-list granularity at authoring time (PRD 055 R16–R20).

Decomposes coarse intra-phase refs before freeze; emits durable ``## Execute-tier granularity``
with split preflight JSON. Runtime expansion in ``execute_plan.py`` remains the escape hatch
for already-frozen coarse lists (no frozen-task mutation).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import doc_format
import phase_sizing
import wave_deliver as wd
from execute_plan import load_execute_config

GRANULARITY_HEADING = "## Execute-tier granularity"
SUBTASK_CHECKBOX = re.compile(
    r"^-\s+\[([ xX])\]\s+(?:\*\*)?(\d+(?:\.\d+)+)(?:\*\*)?\s+(.+)$"
)
FILE_LINE = re.compile(r"^(\s*-?\s*\*\*File:\*\*\s*)(.+)$")
REF_ID_PATTERN = re.compile(r"^\d+(?:\.\d+)+$")


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))
    sys.exit(code)


def resolve_task_list(root: Path, raw: str) -> Path:
    task_list = Path(raw)
    if not task_list.is_absolute():
        task_list = (root / task_list).resolve()
    return task_list


def rel_task_list(task_list: Path, root: Path) -> str:
    try:
        return str(task_list.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(task_list)


def has_granularity_section(text: str) -> bool:
    return bool(re.search(rf"^{re.escape(GRANULARITY_HEADING)}\s*$", text, re.MULTILINE))


def strip_granularity_section(text: str) -> str:
    if not has_granularity_section(text):
        return text
    pattern = rf"^{re.escape(GRANULARITY_HEADING)}\s*$[\s\S]*?(?=^##\s|\Z)"
    return re.sub(pattern, "", text, count=1, flags=re.MULTILINE).rstrip() + "\n"


def parse_file_paths(raw: str) -> list[str]:
    backtick_paths = re.findall(r"`([^`]+)`", raw)
    if backtick_paths:
        return [doc_format.normalize_file_path(p) for p in backtick_paths if p.strip()]
    return [
        doc_format.normalize_file_path(p.strip())
        for p in re.split(r"[,]|(?:\s+and\s+)|(?:\s+or\s+)", raw)
        if p.strip()
    ]


def is_list_shaped_file_field(raw: str, paths: list[str]) -> bool:
    if len(paths) < 2:
        return False
    if "," in raw or re.search(r"\s+and\s+|\s+or\s+", raw):
        return True
    return len(re.findall(r"`[^`]+`", raw)) >= 2


@dataclass
class SubtaskRef:
    checked: bool
    ref_id: str
    title: str
    detail_lines: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    file_line_index: int | None = None
    file_raw: str = ""

    def clone(self) -> SubtaskRef:
        return SubtaskRef(
            checked=self.checked,
            ref_id=self.ref_id,
            title=self.title,
            detail_lines=list(self.detail_lines),
            files=list(self.files),
            file_line_index=self.file_line_index,
            file_raw=self.file_raw,
        )


def parse_phase_subtasks(chunk: str) -> list[SubtaskRef]:
    refs: list[SubtaskRef] = []
    current: SubtaskRef | None = None
    for line in chunk.splitlines():
        match = SUBTASK_CHECKBOX.match(line)
        if match:
            if current:
                refs.append(current)
            ref_id = match.group(2)
            if not REF_ID_PATTERN.match(ref_id):
                current = None
                continue
            current = SubtaskRef(
                checked=match.group(1).lower() == "x",
                ref_id=ref_id,
                title=match.group(3).strip(),
            )
            continue
        if current is None:
            continue
        current.detail_lines.append(line)
        file_match = FILE_LINE.match(line)
        if file_match:
            raw = file_match.group(2).strip()
            paths = parse_file_paths(raw)
            current.files.extend(paths)
            current.file_line_index = len(current.detail_lines) - 1
            current.file_raw = raw
    if current:
        refs.append(current)
    return refs


def format_file_field(paths: list[str]) -> str:
    if len(paths) == 1:
        return f"`{paths[0]}`"
    return ", ".join(f"`{path}`" for path in paths)


def render_subtask(ref: SubtaskRef) -> str:
    mark = "x" if ref.checked else " "
    lines = [f"- [{mark}] {ref.ref_id} {ref.title}"]
    for index, detail in enumerate(ref.detail_lines):
        if index == ref.file_line_index and ref.files:
            indent = re.match(r"^(\s*)", detail)
            prefix = indent.group(1) if indent else "  "
            lines.append(f"{prefix}- **File:** {format_file_field(ref.files)}")
        else:
            lines.append(detail)
    if ref.files and ref.file_line_index is None:
        lines.append(f"  - **File:** {format_file_field(ref.files)}")
    return "\n".join(lines)


def subdivide_oversized_set(files: list[str], thresholds: dict[str, int]) -> list[list[str]]:
    if len(files) <= 1:
        return [files]
    metrics = {
        "filesTouched": len(files),
        "distinctDirs": phase_sizing.distinct_dir_count(files),
    }
    over = any(metrics[key] > int(thresholds.get(key, 0)) for key in metrics)
    if not over:
        return [sorted(files)]
    by_dir: dict[str, list[str]] = {}
    for file_path in files:
        parent = str(Path(file_path).parent)
        by_dir.setdefault(parent if parent and parent != "." else ".", []).append(file_path)
    if len(by_dir) >= 2:
        return [sorted(vals) for vals in by_dir.values()]
    return [[path] for path in sorted(files)]


def plan_ref_splits(
    root: Path,
    content: str,
    phase_id: str,
    ref: SubtaskRef,
    thresholds: dict[str, int],
) -> dict[str, Any] | None:
    files = sorted(set(ref.files))
    if len(files) < 2:
        return None
    if not is_list_shaped_file_field(ref.file_raw, files):
        return None

    score = phase_sizing.score_execute_ref(root, content, phase_id, ref.ref_id, thresholds)
    separable = phase_sizing.separable_sets_for_paths(files, root)
    over = bool(score.get("overThreshold"))
    if not over and len(separable) <= 1:
        return None

    target_sets: list[list[str]] = []
    if len(separable) > 1:
        for group in separable:
            target_sets.extend(subdivide_oversized_set(group, thresholds))
    elif over:
        target_sets = subdivide_oversized_set(files, thresholds)
    else:
        return None

    target_sets = [sorted(s) for s in target_sets if s]
    if len(target_sets) <= 1:
        return None

    serial_edges: list[dict[str, str]] = []
    if len(separable) == 1 and len(files) > 1:
        for left, right in zip(target_sets, target_sets[1:]):
            serial_edges.append(
                {
                    "fromFiles": left,
                    "toFiles": right,
                    "kind": "contention-serial",
                    "reason": "shared contention family — serial execute order required",
                }
            )

    return {
        "phase": phase_id,
        "parentRef": ref.ref_id,
        "files": files,
        "targetSets": target_sets,
        "serialEdges": serial_edges,
        "separableSets": separable,
        "overThreshold": over,
    }


def split_subtask(ref: SubtaskRef, target_sets: list[list[str]]) -> list[SubtaskRef]:
    children: list[SubtaskRef] = []
    for index, file_set in enumerate(target_sets, start=1):
        child = ref.clone()
        child.ref_id = f"{ref.ref_id}.{index}"
        child.files = list(file_set)
        if len(target_sets) > 1:
            child.title = f"{ref.title} (unit {index}/{len(target_sets)})"
        children.append(child)
    return children


def renumber_phase_refs(phase_id: str, refs: list[SubtaskRef]) -> tuple[list[SubtaskRef], dict[str, str]]:
    mapping: dict[str, str] = {}
    renumbered: list[SubtaskRef] = []
    for index, ref in enumerate(refs, start=1):
        new_id = f"{phase_id}.{index}"
        mapping[ref.ref_id] = new_id
        updated = ref.clone()
        updated.ref_id = new_id
        renumbered.append(updated)
    return renumbered, mapping


def rewrite_phase_chunk(phase_id: str, title_line: str, refs: list[SubtaskRef]) -> str:
    body = "\n".join(render_subtask(ref) for ref in refs)
    return f"### {phase_id}.{title_line}\n\n{body}\n"


def build_granularity_payload(
    ref_splits: list[dict[str, Any]],
    *,
    score: dict[str, Any] | None,
    task_list: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": 1,
        "generatedBy": "tasks_generate.py",
        "taskList": task_list,
        "refSplits": ref_splits,
    }
    if score is not None:
        split_suggestions = [
            phase.get("splitSuggestion")
            for phase in score.get("phases", [])
            if phase.get("splitSuggestion")
        ]
        payload["splitPreflight"] = {
            "phaseCount": score.get("phaseCount"),
            "costEstimate": score.get("costEstimate"),
            "splitSuggestions": split_suggestions,
            "notices": score.get("notices", []),
        }
    return payload


def render_granularity_section(payload: dict[str, Any]) -> str:
    json_block = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        f"{GRANULARITY_HEADING}\n\n"
        "> Frozen artifact (PRD 055 R17). Generated by "
        "`python3 scripts/tasks_generate.py apply-granularity` before `/sw-freeze`.\n\n"
        f"```json\n{json_block}\n```\n"
    )


def insert_granularity_section(content: str, payload: dict[str, Any]) -> str:
    section = render_granularity_section(payload)
    trace = re.search(r"^## Traceability\s*$", content, flags=re.MULTILINE)
    if trace:
        return content[: trace.start()] + section + "\n" + content[trace.start() :]
    deps = re.search(r"^## Phase Dependencies\s*$", content, flags=re.MULTILINE)
    if deps:
        after = re.search(r"^##\s+", content[deps.end() :], flags=re.MULTILINE)
        if after:
            insert_at = deps.end() + after.start()
            return content[:insert_at] + "\n" + section + content[insert_at:]
    return content.rstrip() + "\n\n" + section


def transform_task_list_text(root: Path, text: str, task_list: Path) -> tuple[str, list[dict[str, Any]]]:
    fm, content = doc_format.split_frontmatter(text)
    thresholds = load_execute_config(root).get("thresholds") or {}
    ref_splits: list[dict[str, Any]] = []

    sections = re.split(r"^(###\s+(\d+)\.\s+(.+))$", content, flags=re.MULTILINE)
    rebuilt: list[str] = []
    if sections and sections[0]:
        rebuilt.append(sections[0])

    for idx in range(1, len(sections), 4):
        phase_id = sections[idx + 1]
        title = sections[idx + 2]
        chunk = sections[idx + 3] if idx + 3 < len(sections) else ""
        refs = parse_phase_subtasks(chunk)
        expanded: list[SubtaskRef] = []
        phase_splits: list[dict[str, Any]] = []
        for ref in refs:
            plan = plan_ref_splits(root, content, phase_id, ref, thresholds)
            if plan:
                children = split_subtask(ref, plan["targetSets"])
                plan = dict(plan)
                plan["childRefs"] = [child.ref_id for child in children]
                phase_splits.append(plan)
                expanded.extend(children)
            else:
                expanded.append(ref)
        expanded, id_map = renumber_phase_refs(phase_id, expanded)
        for plan in phase_splits:
            plan["childRefs"] = [id_map.get(child, child) for child in plan["childRefs"]]
            ref_splits.append(plan)
        rebuilt.append(rewrite_phase_chunk(phase_id, title, expanded))

    new_content = "".join(rebuilt)
    score = phase_sizing.score_task_list(root, task_list, phase_sizing.load_sizing_config(root))
    stripped = strip_granularity_section(new_content)
    rel = rel_task_list(task_list, root)
    payload = build_granularity_payload(ref_splits, score=score, task_list=rel)
    final_content = insert_granularity_section(stripped, payload)
    if fm:
        final_content = f"{fm}{final_content}"
    return final_content, ref_splits


def apply_granularity(root: Path, task_list: Path, *, inplace: bool) -> dict[str, Any]:
    text = task_list.read_text(encoding="utf-8")
    if wd.parse_frontmatter(text).get("frozen", "").lower() == "true":
        emit(
            {
                "verdict": "fail",
                "action": "tasks-generate-apply-granularity",
                "error": "frozen task list — apply before freeze only (R20)",
                "taskList": rel_task_list(task_list, root),
            },
            20,
        )
    final_content, ref_splits = transform_task_list_text(root, text, task_list)
    if inplace:
        task_list.write_text(final_content, encoding="utf-8")
    result = {
        "verdict": "pass",
        "action": "tasks-generate-apply-granularity",
        "taskList": rel_task_list(task_list, root),
        "refSplitCount": len(ref_splits),
        "refSplits": ref_splits,
        "inplace": inplace,
    }
    if not inplace:
        result["markdown"] = final_content
    return result


def check_granularity(root: Path, task_list: Path) -> dict[str, Any]:
    text = task_list.read_text(encoding="utf-8")
    rel = rel_task_list(task_list, root)
    thresholds = load_execute_config(root).get("thresholds") or {}
    failures: list[str] = []

    if not has_granularity_section(text):
        failures.append("missing ## Execute-tier granularity section")

    _, content = doc_format.split_frontmatter(text)
    phases = wd.parse_phases(content)
    oversized: list[str] = []
    for phase in phases:
        pid = phase["id"]
        for ref in parse_phase_subtasks(doc_format.phase_section_text(content, pid)):
            score = phase_sizing.score_execute_ref(root, content, pid, ref.ref_id, thresholds)
            if score.get("overThreshold"):
                oversized.append(ref.ref_id)

    if oversized:
        failures.append(f"oversized refs remain: {', '.join(oversized)}")

    if phase_sizing.has_advisory_block(text):
        failures.append("advisory sizing block present — strip before freeze (R30)")

    verdict = "pass" if not failures else "fail"
    return {
        "verdict": verdict,
        "action": "tasks-generate-check",
        "taskList": rel,
        "failures": failures,
        "phaseCount": len(phases),
        "oversizedRefs": oversized,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tasks_generate.py")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    apply_cmd = sub.add_parser(
        "apply-granularity",
        help="Decompose coarse refs and emit Execute-tier granularity section",
    )
    apply_cmd.add_argument("--task-list", required=True, help="Path to task-list markdown")
    apply_cmd.add_argument("--inplace", action="store_true", help="Rewrite task list in place")
    check_cmd = sub.add_parser("check", help="Verify execute-tier granularity on a task list")
    check_cmd.add_argument("--task-list", required=True, help="Path to task-list markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    task_list = resolve_task_list(root, args.task_list)
    if not task_list.is_file():
        emit({"verdict": "fail", "error": f"task list not found: {task_list}"}, 2)

    if args.command == "apply-granularity":
        result = apply_granularity(root, task_list, inplace=bool(args.inplace))
        if not args.inplace:
            markdown = result.pop("markdown", None)
            if markdown:
                print(markdown, end="")
        emit(result)
    if args.command == "check":
        result = check_granularity(root, task_list)
        emit(result, 0 if result["verdict"] == "pass" else 20)
    emit({"verdict": "fail", "error": f"unknown command {args.command!r}"}, 2)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
