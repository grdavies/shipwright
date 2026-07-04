#!/usr/bin/env python3
"""Execute-plan builder, dependency rules, and runtime expansion (PRD 053).

Runtime expansion is the escape hatch for **already frozen** coarse task lists (PRD 055 R20): oversized
refs may be split into synthetic child refs at deliver time without mutating the frozen task file.
Authoring-time decomposition is handled by ``tasks_generate.py apply-granularity`` before freeze."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import doc_format
import planning_paths
from intra_phase_dispatch import DECISIONS_FILENAME, intra_phase_settings, load_workflow_config
from wave_deliver import (
    feature_slug,
    graph_has_cycle,
    has_path,
    parse_frontmatter,
    paths_contend,
    resolve_task_list_path,
)
from wave_json_io import write_json
from wave_plan_validate import (
    DEFAULT_PLAN_POLICY,
    plan_stamps,
    read_config_plan_policy,
    resolve_plan_policy_for_proposal,
)

EXECUTE_PLAN_FILENAME = "execute-step-plan.json"
REF_ID_PATTERN = re.compile(r"^\d+(?:\.\d+)+$")
BACKTICK_RE = re.compile(r"`([^`]+)`")
RULES_REL = Path("core/sw-reference/execute-dependency-rules.json")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ref_sort_key(ref_id: str) -> tuple[int, ...]:
    return tuple(int(part) for part in ref_id.split("."))


def sanitize_ref_for_branch(ref_id: str) -> str:
    return ref_id.replace(".", "-")


def sub_branch_name(feature_slug_value: str, phase_slug: str, ref_id: str) -> str:
    return f"feat/{feature_slug_value}-phase-{phase_slug}--task-{sanitize_ref_for_branch(ref_id)}"


def load_dependency_rules(root: Path) -> dict[str, Any]:
    path = root / RULES_REL
    if not path.is_file():
        fail(f"missing dependency rules: {RULES_REL}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        fail("invalid execute-dependency-rules.json shape")
    return data


def load_execute_config(root: Path) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    execute = cfg.get("execute") or {}
    if not isinstance(execute, dict):
        execute = {}
    sizing = execute.get("sizing") or {}
    thresholds = sizing.get("thresholds") or {}
    return {
        "enabled": bool(execute.get("enabled", True)),
        "maxExpansionDepth": int(execute.get("maxExpansionDepth", 2)),
        "thresholds": {
            "filesTouched": int(thresholds.get("filesTouched", 3)),
            "distinctDirs": int(thresholds.get("distinctDirs", 2)),
            "traceabilityScenarios": int(thresholds.get("traceabilityScenarios", 2)),
        },
    }


def parse_executable_subtasks(content: str, phase_id: str) -> list[dict[str, Any]]:
    return doc_format.extract_executable_subtasks(content, phase_id)


def ref_files_map(subtasks: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {st["id"]: list(st.get("files") or []) for st in subtasks}


def first_backtick(title: str) -> str | None:
    match = BACKTICK_RE.search(title)
    return match.group(1).strip() if match else None


def apply_wire_after_implement(subtasks: list[dict[str, Any]], rule: dict[str, Any]) -> list[dict[str, str]]:
    wire_re = re.compile(str(rule.get("wireTitlePattern", "(?i)^Wire\\b")))
    impl_re = re.compile(str(rule.get("implementTitlePattern", "(?i)^(Implement|Add)\\b")))
    edges: list[dict[str, str]] = []
    ordered = sorted(subtasks, key=lambda st: ref_sort_key(st["id"]))
    for idx, task in enumerate(ordered):
        title = str(task.get("title") or "")
        if not wire_re.search(title):
            continue
        wire_files = set(task.get("files") or [])
        wire_tick = first_backtick(title)
        implement_ref: str | None = None
        for prior in reversed(ordered[:idx]):
            prior_title = str(prior.get("title") or "")
            if not impl_re.search(prior_title):
                continue
            prior_files = set(prior.get("files") or [])
            prior_tick = first_backtick(prior_title)
            if (wire_files & prior_files) or (wire_tick and prior_tick and wire_tick == prior_tick):
                implement_ref = prior["id"]
                break
        if implement_ref:
            edges.append({"from": implement_ref, "to": task["id"], "kind": "wire-after-implement"})
    return edges


def apply_fixtures_after_prior_work(subtasks: list[dict[str, Any]], rule: dict[str, Any]) -> list[dict[str, str]]:
    fixtures_re = re.compile(str(rule.get("fixturesTitlePattern", "(?i)\\bFixtures?\\b")))
    edges: list[dict[str, str]] = []
    ordered = sorted(subtasks, key=lambda st: ref_sort_key(st["id"]))
    for task in ordered:
        if not fixtures_re.search(str(task.get("title") or "")):
            continue
        for prior in ordered:
            if ref_sort_key(prior["id"]) >= ref_sort_key(task["id"]):
                break
            edges.append({"from": prior["id"], "to": task["id"], "kind": "fixtures-after-prior-work"})
    return edges


def apply_traceability_row_order(content: str, phase_id: str, subtasks: list[dict[str, Any]], rule: dict[str, Any]) -> list[dict[str, str]]:
    _ = (phase_id, rule)
    phase_refs = {st["id"] for st in subtasks}
    edges: list[dict[str, str]] = []
    for row in doc_format.extract_traceability_rows(content):
        refs = sorted({t for t in re.findall(r"\d+(?:\.\d+)+", row.get("task", "")) if t in phase_refs}, key=ref_sort_key)
        for left, right in zip(refs, refs[1:]):
            edges.append({"from": left, "to": right, "kind": "traceability-row-order"})
    return edges


def apply_dependency_rules(root: Path, content: str, phase_id: str, subtasks: list[dict[str, Any]]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for rule in load_dependency_rules(root).get("rules") or []:
        if not isinstance(rule, dict):
            continue
        kind = str(rule.get("kind") or rule.get("id") or "")
        if kind == "wire-after-implement":
            edges.extend(apply_wire_after_implement(subtasks, rule))
        elif kind == "fixtures-after-prior-work":
            edges.extend(apply_fixtures_after_prior_work(subtasks, rule))
        elif kind == "traceability-row-order":
            edges.extend(apply_traceability_row_order(content, phase_id, subtasks, rule))
    return dedupe_edges(edges)


def dedupe_edges(edges: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for edge in edges:
        key = (edge["from"], edge["to"], edge.get("kind", ""))
        if key not in seen:
            seen.add(key)
            out.append(edge)
    return out


def inject_ref_contention_edges(ref_ids: list[str], declared_edges: list[dict[str, str]], ref_files: dict[str, list[str]], root: Path):
    contention = planning_paths.contention_default(root)
    serialized = list(contention.get("serialized") or planning_paths.contention_serialized_defaults(planning_paths.load_planning_dirs(root)))
    injected: list[dict[str, str]] = []
    notices: list[str] = []
    all_edges = [dict(e) for e in declared_edges]
    existing = {(e["from"], e["to"]) for e in all_edges}
    sorted_ids = sorted(ref_ids, key=ref_sort_key)
    for left in sorted_ids:
        for right in sorted_ids:
            if ref_sort_key(left) >= ref_sort_key(right):
                continue
            overlap = ""
            contend = False
            for fl in ref_files.get(left, []):
                for fr in ref_files.get(right, []):
                    hit, detail = paths_contend(fl, fr, serialized, root)
                    if hit:
                        contend, overlap = True, detail or f"{fl} ⟷ {fr}"
                        break
                if contend:
                    break
            if not contend:
                continue
            if has_path(declared_edges, right, left):
                fail("contention-cycle", exit_code=20, refs=[left, right], overlap=overlap)
            if (left, right) in existing or has_path(all_edges, left, right):
                continue
            edge = {"from": left, "to": right, "kind": "contention"}
            injected.append(edge)
            all_edges.append(edge)
            existing.add((left, right))
            notices.append(f"contention: refs {left} and {right} serialized ({overlap})")
    if graph_has_cycle(sorted_ids, all_edges):
        fail("contention-cycle", exit_code=20)
    return all_edges, injected, notices


def assign_ref_waves(ref_ids: list[str], edges: list[dict[str, str]]) -> list[list[str]]:
    graph_nodes = set(ref_ids)
    for edge in edges:
        graph_nodes.update((edge["from"], edge["to"]))
    items = sorted(graph_nodes, key=ref_sort_key)
    deps = {item: {e["from"] for e in edges if e["to"] == item} for item in items}
    if graph_has_cycle(items, edges):
        fail("dependency cycle detected in execute plan", exit_code=20)
    waves: list[list[str]] = []
    remaining = set(items)
    while remaining:
        wave = sorted([i for i in remaining if not (deps[i] & remaining)], key=ref_sort_key)
        if not wave:
            fail("unable to assign execute ref wave", exit_code=20)
        waves.append(wave)
        remaining -= set(wave)
    return waves


def greedy_execute_batches(ref_ids: list[str], edges: list[dict[str, str]], budget: int) -> list[list[str]]:
    batches: list[list[str]] = []
    for wave in assign_ref_waves(ref_ids, edges):
        sorted_wave = sorted(wave, key=ref_sort_key)
        for index in range(0, len(sorted_wave), budget):
            batches.append(sorted_wave[index : index + budget])
    return batches


def canonical_linear_batches(ref_ids: list[str]) -> list[list[str]]:
    return [[ref] for ref in sorted(ref_ids, key=ref_sort_key)]


def parallel_budget(root: Path) -> int:
    return max(1, intra_phase_settings(load_workflow_config(root))["parallelBudget"])


def runtime_expand_refs(root: Path, content: str, phase_id: str, subtasks: list[dict[str, Any]], execute_cfg: dict[str, Any], *, depth: int = 0):
    import phase_sizing
    max_depth = int(execute_cfg.get("maxExpansionDepth", 2))
    if depth >= max_depth:
        import phase_sizing
        for task in subtasks:
            score = phase_sizing.score_execute_ref(root, content, phase_id, task["id"], execute_cfg.get("thresholds") or {})
            if score.get("overThreshold"):
                fail(
                    f"runtime expansion depth cap exceeded for ref {task['id']}",
                    exit_code=20,
                    maxExpansionDepth=max_depth,
                )
        return subtasks, [], []
    expanded: list[dict[str, Any]] = []
    expansion_edges: list[dict[str, str]] = []
    notices: list[str] = []
    for task in subtasks:
        score = phase_sizing.score_execute_ref(root, content, phase_id, task["id"], execute_cfg.get("thresholds") or {})
        sets = score.get("separableSets") or []
        if not score.get("overThreshold") or len(sets) < 2:
            expanded.append(task)
            continue
        child_ids = []
        for index, file_set in enumerate(sets, start=1):
            child_id = f"{task['id']}.{index}"
            child_ids.append(child_id)
            expanded.append({"id": child_id, "title": f"{task.get('title', '')} (expansion {index})", "files": sorted(file_set), "parentRef": task["id"], "synthetic": True})
        for left, right in zip(child_ids, child_ids[1:]):
            expansion_edges.append({"from": left, "to": right, "kind": "runtime-expansion"})
        notices.append(f"runtime expansion: {task['id']} -> {child_ids}")
    return expanded, expansion_edges, notices


def build_execute_refs(feature_slug_value: str, phase_slug: str, subtasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = []
    for task in subtasks:
        entry = {"id": task["id"], "branch": sub_branch_name(feature_slug_value, phase_slug, task["id"]), "files": sorted(set(task.get("files") or [])), "status": "pending"}
        if task.get("parentRef"):
            entry["parentRef"] = task["parentRef"]
        refs.append(entry)
    return refs


def record_dispatch_decisions(run_dir: Path, payload: dict[str, Any]) -> None:
    path = run_dir / DECISIONS_FILENAME
    existing: dict[str, Any] = {"version": 1, "decisions": []}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = raw
        except json.JSONDecodeError:
            pass
    decisions = existing.setdefault("decisions", [])
    if not isinstance(decisions, list):
        decisions = []
        existing["decisions"] = decisions
    decisions.append({**payload, "at": utc_now()})
    write_json(path, existing)


def execute_fallback_canonical_linear_order(root: Path, task_list: str, phase_id: str, *, phase_slug: str = "", feature_slug_value: str = "") -> dict[str, Any]:
    task_path = resolve_task_list_path(root, task_list)
    content = task_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(content)
    slug = feature_slug_value or feature_slug(fm, task_path)
    pslug = phase_slug or f"phase-{phase_id}"
    subtasks = parse_executable_subtasks(content, phase_id)
    if not subtasks:
        fail(f"no executable sub-tasks for phase {phase_id}")
    ref_ids = [st["id"] for st in subtasks]
    edges, _, _ = inject_ref_contention_edges(ref_ids, apply_dependency_rules(root, content, phase_id, subtasks), ref_files_map(subtasks), root)
    stamps = plan_stamps(root, DEFAULT_PLAN_POLICY)
    return {"version": 1, "tier": "execute", "phaseId": phase_id, "phaseSlug": pslug, "refs": build_execute_refs(slug, pslug, subtasks), "edges": edges, "batches": canonical_linear_batches(ref_ids), **stamps, "fallback": "canonical-linear", "validatedAt": utc_now()}


def propose_execute_plan(root: Path, *, task_list: str, phase_id: str, phase_slug: str, feature_slug_value: str = "", plan_policy: str | None = None, recorded_parent: dict[str, Any] | None = None) -> dict[str, Any]:
    task_path = resolve_task_list_path(root, task_list)
    content = task_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(content)
    slug = feature_slug_value or feature_slug(fm, task_path)
    policy = plan_policy or resolve_plan_policy_for_proposal(root, recorded_parent=recorded_parent)
    execute_cfg = load_execute_config(root)
    subtasks = parse_executable_subtasks(content, phase_id)
    if not subtasks:
        fail(f"no executable sub-tasks for phase {phase_id}")
    subtasks, expansion_edges, expansion_notices = runtime_expand_refs(root, content, phase_id, subtasks, execute_cfg)
    ref_ids = [st["id"] for st in subtasks]
    edges, injected, contention_notices = inject_ref_contention_edges(ref_ids, dedupe_edges(apply_dependency_rules(root, content, phase_id, subtasks) + expansion_edges), ref_files_map(subtasks), root)
    batches = canonical_linear_batches(ref_ids) if policy == "canonical" else greedy_execute_batches(ref_ids, edges, parallel_budget(root))
    stamps = plan_stamps(root, policy, recorded_parent=recorded_parent)
    plan = {"version": 1, "tier": "execute", "phaseId": phase_id, "phaseSlug": phase_slug, "refs": build_execute_refs(slug, phase_slug, subtasks), "edges": edges, "batches": batches, **stamps, "validatedAt": utc_now()}
    if injected or expansion_notices or contention_notices:
        plan["notices"] = {"contention": contention_notices, "injectedEdges": injected, "expansion": expansion_notices}
    return plan


def resolve_run_dir(phase_slug: str, explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit)
        return path.parent if path.suffix == ".json" else path
    env_dir = os.environ.get("SW_RUN_DIR", "").strip()
    return Path(env_dir) if env_dir else Path(".cursor/sw-deliver-runs") / phase_slug


def closed_world_ref_ids(root: Path, task_list: str, phase_id: str) -> set[str]:
    content = resolve_task_list_path(root, task_list).read_text(encoding="utf-8")
    return {st["id"] for st in parse_executable_subtasks(content, phase_id)}


def validate_execute_plan(root: Path, proposal: dict[str, Any], *, task_list: str | None = None, phase_id: str | None = None) -> dict[str, Any]:
    refs_raw = proposal.get("refs") or []
    batches_raw = proposal.get("batches") or []
    edges_raw = proposal.get("edges") or []
    pid = phase_id or str(proposal.get("phaseId") or "")
    if not pid:
        return {"verdict": "reject", "reasons": ["phaseId required"]}
    if not isinstance(refs_raw, list) or not refs_raw:
        return {"verdict": "reject", "reasons": ["refs must be a non-empty array"]}
    if not isinstance(batches_raw, list) or not batches_raw:
        return {"verdict": "reject", "reasons": ["batches must be a non-empty array"]}
    ref_ids = [str(ref.get("id")) for ref in refs_raw if isinstance(ref, dict)]
    if len(ref_ids) != len(set(ref_ids)):
        return {"verdict": "ambiguous", "reasons": ["duplicate ref ids in proposal"]}
    for ref_id in ref_ids:
        if not REF_ID_PATTERN.match(ref_id):
            return {"verdict": "reject", "reasons": [f"invalid ref id: {ref_id}"]}
    if task_list:
        allowed = closed_world_ref_ids(root, task_list, pid)
        for ref in refs_raw:
            if not isinstance(ref, dict):
                continue
            ref_id = str(ref.get("id"))
            parent = ref.get("parentRef")
            if ref_id not in allowed and not (isinstance(parent, str) and parent in allowed):
                return {"verdict": "reject", "reasons": [f"closed-world violation: unknown ref {ref_id}"]}
    edges = [dict(edge) for edge in edges_raw if isinstance(edge, dict)]
    if graph_has_cycle(sorted(ref_ids, key=ref_sort_key), edges):
        return {"verdict": "reject", "reasons": ["dependency cycle detected"]}
    must_precede: dict[str, set[str]] = {}
    for edge in edges:
        src, dst = edge.get("from"), edge.get("to")
        if isinstance(src, str) and isinstance(dst, str):
            must_precede.setdefault(dst, set()).add(src)
    reasons: list[str] = []
    batch_refs = {ref for batch in batches_raw for ref in batch}
    if batch_refs != set(ref_ids):
        missing = sorted(set(ref_ids) - batch_refs, key=ref_sort_key)
        extra = sorted(batch_refs - set(ref_ids), key=ref_sort_key)
        if missing:
            reasons.append(f"batches missing refs: {missing}")
        if extra:
            reasons.append(f"batches have extraneous refs: {extra}")
    for batch in batches_raw:
        if not isinstance(batch, list) or not batch:
            reasons.append("each batch must be a non-empty array")
            continue
        if len(batch) < 2:
            continue
        batch_set = set(batch)
        for ref in batch:
            for dep in must_precede.get(ref, set()):
                if dep in batch_set:
                    reasons.append(f"batch disjointness violation: {ref} cannot batch with dependency {dep}")
    if reasons:
        return {"verdict": "reject", "reasons": reasons}
    stamps = plan_stamps(root, str(proposal.get("planPolicy") or read_config_plan_policy(root)))
    return {"verdict": "pass", "reasons": [], "plan": {"version": 1, "tier": "execute", "phaseId": pid, "phaseSlug": proposal.get("phaseSlug"), "refs": refs_raw, "edges": edges, "batches": batches_raw, **stamps, "validatedAt": utc_now()}}


def apply_execute_fallback(result: dict[str, Any], root: Path, *, task_list: str, phase_id: str, phase_slug: str) -> dict[str, Any]:
    if result.get("verdict") == "pass":
        return result
    result["fallback"] = execute_fallback_canonical_linear_order(root, task_list, phase_id, phase_slug=phase_slug)
    result["fallbackAction"] = "canonical-linear"
    return result


def persist_execute_plan(run_dir: Path, plan: dict[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / EXECUTE_PLAN_FILENAME
    write_json(path, plan)
    return path


def cmd_propose(root: Path, args: argparse.Namespace) -> int:
    plan = propose_execute_plan(root, task_list=args.task_list, phase_id=args.phase_id, phase_slug=args.phase_slug, feature_slug_value=args.feature_slug or "", plan_policy=args.plan_policy)
    if args.record:
        run_dir = resolve_run_dir(args.phase_slug, args.run_dir)
        path = persist_execute_plan(run_dir, plan)
        record_dispatch_decisions(run_dir, {"action": "execute-plan-propose", "phaseId": args.phase_id, "phaseSlug": args.phase_slug, "planPolicy": plan.get("planPolicy"), "batchCount": len(plan.get("batches") or []), "refCount": len(plan.get("refs") or [])})
        emit({"verdict": "pass", "plan": plan, "path": str(path)})
    emit({"verdict": "pass", "plan": plan})


def cmd_validate(root: Path, args: argparse.Namespace) -> int:
    proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    result = validate_execute_plan(root, proposal, task_list=args.task_list or None, phase_id=args.phase_id)
    if args.task_list:
        result = apply_execute_fallback(result, root, task_list=args.task_list, phase_id=args.phase_id, phase_slug=args.phase_slug)
    if result.get("verdict") == "pass" and args.record:
        plan = result["plan"]
        run_dir = resolve_run_dir(args.phase_slug, args.run_dir)
        result["path"] = str(persist_execute_plan(run_dir, plan))
    emit(result, 0)



def sub_branch_worktree_name(feature_slug_value: str, phase_slug: str, ref_id: str) -> str:
    return f"{feature_slug_value}-phase-{phase_slug}--task-{sanitize_ref_for_branch(ref_id)}"


def resolve_sub_branch_ceiling(root: Path) -> int:
    from worktree import resolve_sub_branch_ceiling as _resolve

    return _resolve(load_workflow_config(root))


def active_sub_branch_count(phase_slug: str | None = None) -> int:
    from worktree import active_execute_sub_branch_count

    return active_execute_sub_branch_count(phase_slug)


def cmd_provision_sub_branch(root: Path, args: argparse.Namespace) -> int:
    import subprocess

    ceiling = resolve_sub_branch_ceiling(root)
    active = active_sub_branch_count(args.phase_slug)
    if active >= ceiling:
        fail(
            "execute sub-branch ceiling reached",
            exit_code=20,
            cause="execute:sub-branch-ceiling",
            activeSubBranches=active,
            subBranchCeiling=ceiling,
            phaseSlug=args.phase_slug,
        )
    name = args.worktree_name or sub_branch_worktree_name(args.feature_slug, args.phase_slug, args.task_ref)
    branch = args.branch or sub_branch_name(args.feature_slug, args.phase_slug, args.task_ref)
    base = args.base
    if not base:
        fail("--base required for sub-branch provision")
    script = Path(__file__).resolve().parent / "worktree.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "provision",
            name,
            "--branch",
            branch,
            "--base",
            base,
            "--counts-toward-ceiling",
            "false",
            "--worktree-role",
            "execute-sub-branch",
            "--phase-slug",
            args.phase_slug,
            "--task-ref",
            args.task_ref,
        ],
        cwd=str(Path(__file__).resolve().parent.parent),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "provision failed"
        fail(detail, exit_code=proc.returncode or 20, cause="execute:provision-failed")
    payload = json.loads(proc.stdout)
    emit(
        {
            "verdict": "pass",
            "action": "provision-sub-branch",
            "taskRef": args.task_ref,
            "phaseSlug": args.phase_slug,
            "branch": branch,
            "worktreeName": name,
            **payload,
        }
    )


def cmd_teardown_sub_branch(root: Path, args: argparse.Namespace) -> int:
    import subprocess

    name = args.worktree_name
    if not name:
        name = sub_branch_worktree_name(args.feature_slug, args.phase_slug, args.task_ref)
    script = Path(__file__).resolve().parent / "worktree.py"
    proc = subprocess.run(
        [sys.executable, str(script), "teardown", name, "--force"],
        cwd=str(Path(__file__).resolve().parent.parent),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "teardown failed", exit_code=proc.returncode or 20)
    payload = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"raw": proc.stdout.strip()}
    emit({"verdict": "pass", "action": "teardown-sub-branch", "taskRef": args.task_ref, **payload})


def cmd_sub_branch_ceiling_check(root: Path, args: argparse.Namespace) -> int:
    from worktree import sub_branch_ceiling_check

    result = sub_branch_ceiling_check(args.phase_slug or None, load_workflow_config(root))
    emit({"verdict": "pass" if result.get("verdict") == "ok" else "refuse", **result}, 0 if result.get("verdict") == "ok" else 20)


def execute_plan_has_parallel_batches(run_dir: Path) -> bool:
    path = run_dir / EXECUTE_PLAN_FILENAME
    if not path.is_file():
        return False
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    for batch in plan.get("batches") or []:
        if isinstance(batch, list) and len(batch) > 1:
            return True
    refs = plan.get("refs") or []
    return isinstance(refs, list) and len(refs) > 1


def frontier_refs(plan: dict[str, Any]) -> list[str]:
    refs = {str(r.get("id")): r for r in plan.get("refs") or [] if isinstance(r, dict) and r.get("id")}
    edges = plan_edges_from_plan(plan)
    deps = {rid: {e["from"] for e in edges if e["to"] == rid} for rid in refs}
    ready = []
    for rid, ref in refs.items():
        status = str(ref.get("status") or "pending")
        if status in {"green", "integrated", "skipped", "blocked"}:
            continue
        if not (deps.get(rid, set()) - {d for d, r in refs.items() if str(r.get("status")) in {"green", "integrated", "skipped"}}):
            ready.append(rid)
    return sorted(ready, key=ref_sort_key)


def plan_edges_from_plan(plan: dict[str, Any]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for edge in plan.get("edges") or []:
        if isinstance(edge, dict) and edge.get("from") and edge.get("to"):
            edges.append({"from": str(edge["from"]), "to": str(edge["to"]), "kind": str(edge.get("kind") or "")})
    return edges


def cmd_dispatch_binding(root: Path, args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.phase_slug, args.run_dir)
    plan_path = run_dir / EXECUTE_PLAN_FILENAME
    if not plan_path.is_file():
        fail(f"missing execute plan: {plan_path}", exit_code=20)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    refs = {str(r.get("id")): r for r in plan.get("refs") or [] if isinstance(r, dict)}
    ref = refs.get(args.task_ref)
    if not ref:
        fail(f"unknown task ref: {args.task_ref}", exit_code=20)
    emit(
        {
            "verdict": "pass",
            "action": "execute-dispatch-binding",
            "taskRef": args.task_ref,
            "phaseSlug": args.phase_slug,
            "branch": ref.get("branch"),
            "files": ref.get("files") or [],
            "command": "sw-execute",
            "statusPath": str(__import__("execute_task_status").status_path(root, args.task_ref)),
            "conductorMode": "execute_fan_out",
        }
    )


def cmd_dispatch_frontier(root: Path, args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.phase_slug, args.run_dir)
    plan_path = run_dir / EXECUTE_PLAN_FILENAME
    if not plan_path.is_file():
        fail(f"missing execute plan: {plan_path}", exit_code=20)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    ready = frontier_refs(plan)
    emit(
        {
            "verdict": "pass",
            "action": "execute-dispatch-frontier",
            "phaseSlug": args.phase_slug,
            "readyRefs": ready,
            "runDir": str(run_dir),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute-plan builder (PRD 053)")
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser("propose")
    propose.add_argument("--task-list", required=True)
    propose.add_argument("--phase-id", required=True)
    propose.add_argument("--phase-slug", required=True)
    propose.add_argument("--feature-slug", default="")
    propose.add_argument("--plan-policy", choices=["canonical", "proposed"])
    propose.add_argument("--record", action="store_true")
    propose.add_argument("--run-dir", default="")
    validate = sub.add_parser("validate")
    validate.add_argument("--proposal", required=True)
    validate.add_argument("--task-list", default="")
    validate.add_argument("--phase-id", required=True)
    validate.add_argument("--phase-slug", default="")
    validate.add_argument("--record", action="store_true")
    validate.add_argument("--run-dir", default="")
    provision = sub.add_parser("provision-sub-branch")
    provision.add_argument("--task-ref", required=True)
    provision.add_argument("--phase-slug", required=True)
    provision.add_argument("--feature-slug", required=True)
    provision.add_argument("--base", required=True)
    provision.add_argument("--branch", default="")
    provision.add_argument("--worktree-name", default="")
    teardown = sub.add_parser("teardown-sub-branch")
    teardown.add_argument("--task-ref", required=True)
    teardown.add_argument("--phase-slug", required=True)
    teardown.add_argument("--feature-slug", required=True)
    teardown.add_argument("--worktree-name", default="")
    ceiling = sub.add_parser("sub-branch-ceiling-check")
    ceiling.add_argument("--phase-slug", default="")
    binding = sub.add_parser("dispatch-binding")
    binding.add_argument("--task-ref", required=True)
    binding.add_argument("--phase-slug", required=True)
    binding.add_argument("--run-dir", default="")
    frontier = sub.add_parser("dispatch-frontier")
    frontier.add_argument("--phase-slug", required=True)
    frontier.add_argument("--run-dir", default="")
    resume = sub.add_parser("resume-frontier")
    resume.add_argument("--phase-slug", required=True)
    resume.add_argument("--run-dir", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        fail("usage: execute_plan.py <root> <command> [args]")
    root = Path(argv[0])
    args = build_parser().parse_args(argv[1:])
    if args.command == "propose":
        return cmd_propose(root, args)
    if args.command == "validate":
        return cmd_validate(root, args)
    if args.command == "provision-sub-branch":
        return cmd_provision_sub_branch(root, args)
    if args.command == "teardown-sub-branch":
        return cmd_teardown_sub_branch(root, args)
    if args.command == "sub-branch-ceiling-check":
        return cmd_sub_branch_ceiling_check(root, args)
    if args.command == "dispatch-binding":
        return cmd_dispatch_binding(root, args)
    if args.command == "dispatch-frontier":
        return cmd_dispatch_frontier(root, args)
    if args.command == "resume-frontier":
        import execute_ship
        execute_ship.cmd_resume_frontier(root, ["--phase-slug", args.phase_slug] + (["--run-dir", args.run_dir] if args.run_dir else []))
        return 0
    fail(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
