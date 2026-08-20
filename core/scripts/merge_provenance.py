#!/usr/bin/env python3
"""Merge provenance resolver — maps conflict paths to PRD/task intent (PRD 323 R10, R15)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doc_format  # noqa: E402
from claims_audit_lib import parse_phase_subtasks  # noqa: E402
from execute_task_status import sanitize_ref, status_path  # noqa: E402
from planning_materialize import materialized_rel, parse_frontmatter  # noqa: E402

SIDE_VALUES = frozenset({"LEFT", "RIGHT"})


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def normalize_side(raw: str) -> str:
    side = str(raw or "").strip().upper()
    if side not in SIDE_VALUES:
        emit({"verdict": "fail", "error": f"invalid side: {raw!r}"}, 2)
    return side


def normalize_repo_path(raw: str) -> str:
    return raw.replace("\\", "/").lstrip("/")


def git_run(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
    )


def git_commit_rationale(root: Path, rel_path: str, head: str | None) -> str:
    if not head:
        return ""
    rel = normalize_repo_path(rel_path)
    proc = git_run(
        root,
        ["log", "-1", "--format=%s", head, "--", rel],
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


@dataclass
class PathBinding:
    task_ref: str
    phase_id: str
    phase_slug: str
    title: str = ""
    expected: str = ""
    files: list[str] = field(default_factory=list)
    done: bool = False


@dataclass
class ProvenanceIndex:
    task_list: str
    prd_unit_id: str
    tasks_unit_id: str
    prd_body_path: str
    by_path: dict[str, list[PathBinding]] = field(default_factory=dict)
    execute_receipts: dict[str, dict[str, Any]] = field(default_factory=dict)
    ledger_tasks: dict[str, Any] = field(default_factory=dict)


def _append_binding(index_map: dict[str, list[PathBinding]], path: str, binding: PathBinding) -> None:
    entries = index_map.setdefault(path, [])
    if not any(existing.task_ref == binding.task_ref for existing in entries):
        entries.append(binding)


def _tasks_frontmatter(text: str) -> dict[str, str]:
    fm = parse_frontmatter(text)
    return fm if isinstance(fm, dict) else {}


def _prd_unit_id(root: Path, fm: dict[str, str]) -> str:
    explicit = str(fm.get("unit-id") or fm.get("unit_id") or "").strip()
    if explicit and not explicit.startswith("tasks-"):
        return explicit
    prd_rel = str(fm.get("prd") or "").strip()
    if prd_rel:
        prd_text, _ = _read_text(root, prd_rel, unit_id=None)
        if prd_text:
            prd_fm = parse_frontmatter(prd_text)
            uid = str(prd_fm.get("unit-id") or prd_fm.get("unit_id") or "").strip()
            if uid:
                return uid
        stem = Path(prd_rel).stem
        if stem:
            return stem
    topic = str(fm.get("topic") or "").strip()
    if topic:
        return f"323-prd-{topic}" if topic else ""
    return ""


def _read_text(root: Path, body_path: str, *, unit_id: str | None) -> tuple[str | None, str]:
    import planning_artifact_handle as pah

    rel = normalize_repo_path(body_path)
    direct = root / rel
    if direct.is_file():
        return direct.read_text(encoding="utf-8"), "file"
    text, source = pah.resolve_artifact_text(root, rel, unit_id=unit_id)
    return text, source


def _virtual_body_path(logical_path: str) -> str:
    return materialized_rel(normalize_repo_path(logical_path))


def load_execute_receipts(root: Path) -> dict[str, dict[str, Any]]:
    base = root / ".cursor" / "sw-execute-runs"
    out: dict[str, dict[str, Any]] = {}
    if not base.is_dir():
        return out
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        status_file = child / "status.json"
        if not status_file.is_file():
            continue
        try:
            doc = json.loads(status_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(doc, dict):
            continue
        ref = str(doc.get("taskRef") or child.name.replace("-", "."))
        out[ref] = doc
    return out


def load_deliver_ledger(root: Path, deliver_state: dict[str, Any] | None) -> dict[str, Any]:
    if deliver_state is None:
        return {}
    ledger = deliver_state.get("taskLedger") or {}
    tasks = ledger.get("tasks") if isinstance(ledger, dict) else {}
    return tasks if isinstance(tasks, dict) else {}


def build_index(
    root: Path,
    task_list_rel: str,
    *,
    deliver_state: dict[str, Any] | None = None,
    execute_receipts: dict[str, dict[str, Any]] | None = None,
) -> ProvenanceIndex:
    root = root.resolve()
    task_list_rel = normalize_repo_path(task_list_rel)
    tasks_unit_id = ""
    text, source = _read_text(root, task_list_rel, unit_id=None)
    if text is None:
        emit({"verdict": "fail", "error": f"task list not found: {task_list_rel}"}, 2)
    fm = _tasks_frontmatter(text)
    tasks_unit_id = str(fm.get("unit-id") or fm.get("unit_id") or Path(task_list_rel).stem)
    prd_body_path = normalize_repo_path(str(fm.get("prd") or ""))
    prd_unit_id = _prd_unit_id(root, fm)
    phases = doc_format.extract_phases(text)
    phase_slug_by_id = {p["id"]: p.get("slug") or "" for p in phases if p.get("id")}
    by_path: dict[str, list[PathBinding]] = {}
    for phase_id in sorted(phase_slug_by_id):
        for st in parse_phase_subtasks(text, phase_id):
            files = [normalize_repo_path(f) for f in (st.get("files") or [])]
            binding = PathBinding(
                task_ref=str(st.get("ref") or ""),
                phase_id=phase_id,
                phase_slug=phase_slug_by_id.get(phase_id, ""),
                title=str(st.get("title") or ""),
                expected=str(st.get("expected") or ""),
                files=files,
                done=bool(st.get("checked")),
            )
            for path in files:
                _append_binding(by_path, path, binding)
                virtual = _virtual_body_path(path)
                if virtual != path:
                    _append_binding(by_path, virtual, binding)
    ledger = load_deliver_ledger(root, deliver_state)
    for ref, entry in ledger.items():
        if not isinstance(entry, dict):
            continue
        for bindings in by_path.values():
            for binding in bindings:
                if binding.task_ref != ref:
                    continue
                binding.done = bool(entry.get("done"))
                phase_slug = str(entry.get("phase") or "").strip()
                if phase_slug:
                    binding.phase_slug = phase_slug
    receipts = execute_receipts if execute_receipts is not None else load_execute_receipts(root)
    return ProvenanceIndex(
        task_list=task_list_rel,
        prd_unit_id=prd_unit_id,
        tasks_unit_id=tasks_unit_id,
        prd_body_path=prd_body_path,
        by_path=by_path,
        execute_receipts=receipts,
        ledger_tasks=ledger,
    )


def _receipt_rationale(receipt: dict[str, Any] | None) -> str:
    if not receipt:
        return ""
    for key in ("rationale", "commitMessage", "commitRationale", "title"):
        val = str(receipt.get(key) or "").strip()
        if val:
            return val
    return ""


def select_binding(
    bindings: list[PathBinding] | None,
    *,
    execute_receipts: dict[str, dict[str, Any]],
) -> PathBinding | None:
    if not bindings:
        return None
    for binding in bindings:
        if binding.task_ref in execute_receipts:
            return binding
    for binding in bindings:
        if binding.done:
            return binding
    return bindings[0]


def intent_record_for_path(
    index: ProvenanceIndex,
    path: str,
    side: str,
    *,
    root: Path,
    head: str | None = None,
) -> dict[str, Any]:
    rel = normalize_repo_path(path)
    bindings = index.by_path.get(rel)
    if bindings is None:
        virtual = _virtual_body_path(rel)
        bindings = index.by_path.get(virtual)
    binding = select_binding(bindings, execute_receipts=index.execute_receipts)
    receipt = index.execute_receipts.get(binding.task_ref) if binding else None
    rationale = _receipt_rationale(receipt)
    if not rationale:
        rationale = git_commit_rationale(root, rel, head)
    if not rationale and binding:
        rationale = binding.expected or binding.title
    record: dict[str, Any] = {
        "side": side,
        "path": rel,
        "resolved": binding is not None,
        "virtualPath": _virtual_body_path(rel),
    }
    if binding:
        record.update(
            {
                "prdUnitId": index.prd_unit_id,
                "tasksUnitId": index.tasks_unit_id,
                "taskRef": binding.task_ref,
                "phaseId": binding.phase_id,
                "phaseSlug": binding.phase_slug,
                "rationale": rationale,
                "expected": binding.expected,
                "unitId": index.tasks_unit_id,
                "bodyPath": rel,
                "virtualPath": _virtual_body_path(rel),
                "ledgerDone": binding.done,
            }
        )
        if receipt:
            record["executeReceipt"] = {
                "taskRef": receipt.get("taskRef") or binding.task_ref,
                "verdict": receipt.get("verdict"),
                "path": str(status_path(root, binding.task_ref)),
            }
    else:
        record["rationale"] = rationale
        record["prdUnitId"] = index.prd_unit_id
        record["tasksUnitId"] = index.tasks_unit_id
        record["unitId"] = index.tasks_unit_id
    return record


def resolve_paths(
    root: Path,
    paths: list[str],
    *,
    left_head: str | None,
    right_head: str | None,
    task_list: str,
    deliver_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    index = build_index(root, task_list, deliver_state=deliver_state)
    left_records = [
        intent_record_for_path(index, path, "LEFT", root=root, head=left_head)
        for path in paths
    ]
    right_records = [
        intent_record_for_path(index, path, "RIGHT", root=root, head=right_head)
        for path in paths
    ]
    return {
        "verdict": "pass",
        "taskList": task_list,
        "prdUnitId": index.prd_unit_id,
        "leftHead": left_head,
        "rightHead": right_head,
        "records": {"left": left_records, "right": right_records},
        "indexStats": {
            "pathBindings": len(index.by_path),
            "executeReceipts": len(index.execute_receipts),
            "ledgerTasks": len(index.ledger_tasks),
        },
    }


def index_payload(index: ProvenanceIndex) -> dict[str, Any]:
    bindings_out = []
    seen: set[tuple[str, str]] = set()
    for path, bindings in sorted(index.by_path.items()):
        for binding in bindings:
            key = (path, binding.task_ref)
            if key in seen:
                continue
            seen.add(key)
            bindings_out.append(
                {
                    "path": path,
                    "taskRef": binding.task_ref,
                    "phaseId": binding.phase_id,
                    "phaseSlug": binding.phase_slug,
                    "expected": binding.expected,
                }
            )
    return {
        "verdict": "pass",
        "taskList": index.task_list,
        "prdUnitId": index.prd_unit_id,
        "tasksUnitId": index.tasks_unit_id,
        "prdBodyPath": index.prd_body_path,
        "bindings": bindings_out,
        "executeReceipts": sorted(index.execute_receipts),
        "ledgerTasks": index.ledger_tasks,
    }


def load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return doc if isinstance(doc, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge provenance resolver (PRD 323 R10, R15)")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("index", help="Build provenance index from task list + receipts")
    build.add_argument("--tasks", required=True)
    build.add_argument("--deliver-state")
    build.add_argument("--out")

    resolve = sub.add_parser("resolve", help="Resolve one conflict path to LEFT/RIGHT intent records")
    resolve.add_argument("--path", required=True)
    resolve.add_argument("--tasks", required=True)
    resolve.add_argument("--left-head")
    resolve.add_argument("--right-head")
    resolve.add_argument("--deliver-state")
    resolve.add_argument("--out")

    batch = sub.add_parser("resolve-batch", help="Resolve many conflict paths")
    batch.add_argument("--paths", required=True, help="Comma-separated repo-relative paths")
    batch.add_argument("--tasks", required=True)
    batch.add_argument("--left-head")
    batch.add_argument("--right-head")
    batch.add_argument("--deliver-state")
    batch.add_argument("--out")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    deliver_state = load_json(args.deliver_state) if getattr(args, "deliver_state", None) else None

    if args.command == "index":
        index = build_index(root, args.tasks, deliver_state=deliver_state)
        payload = index_payload(index)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        emit(payload)

    if args.command == "resolve":
        result = resolve_paths(
            root,
            [args.path],
            left_head=args.left_head,
            right_head=args.right_head,
            task_list=args.tasks,
            deliver_state=deliver_state,
        )
        left = result["records"]["left"][0]
        right = result["records"]["right"][0]
        payload = {"verdict": "pass", "left": left, "right": right}
        if args.out:
            Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        emit(payload)

    if args.command == "resolve-batch":
        paths = [normalize_repo_path(p) for p in args.paths.split(",") if p.strip()]
        result = resolve_paths(
            root,
            paths,
            left_head=args.left_head,
            right_head=args.right_head,
            task_list=args.tasks,
            deliver_state=deliver_state,
        )
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        emit(result)
    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
