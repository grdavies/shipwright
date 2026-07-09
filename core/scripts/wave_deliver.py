#!/usr/bin/env python3
"""Wave / deliver planning engine — multi-feature and phase-mode.

Contention serialization (R20/R39): `inject_contention_edges` runs at plan time from phase
`**File:**` touch paths (migrations, INDEX, CHANGELOG/version, doc-numbering). Ambiguous overlap
fails safe to sequential waves.

Blast-radius (R24): transitive dependent blocking uses plan `edges` from this module's plan
output; applied at `status collect` via `wave_failure.py blast-radius apply` — siblings in the
same wave without a dependency path continue.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doc_format
import planning_paths
import planning_path_redirect

PLAN_PATH_NAME = "sw-deliver-plan.json"
STATE_PATH_NAME = "sw-deliver-state.json"

_FALLBACK_TYPES = frozenset(
    {"feat", "fix", "perf", "revert", "docs", "chore", "refactor", "test"}
)


def _load_valid_types() -> frozenset[str]:
    """Single-source allowed branch/commit types from release-please-config.json
    (PRD 007 R24 — kept in lockstep with scripts/branch-name-guard.py)."""
    cfg = SCRIPT_DIR.parent / "release-please-config.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        types = [
            sec["type"]
            for pkg in data.get("packages", {}).values()
            for sec in pkg.get("changelog-sections", [])
            if sec.get("type")
        ]
        if types:
            return frozenset(types)
    except Exception:
        pass
    return _FALLBACK_TYPES


VALID_TYPES = _load_valid_types()
MIGRATION_DIRS = (
    "db/migrate/",
    "supabase/migrations/",
    "prisma/migrations/",
)
RELEASE_BOOKKEEPING = ("CHANGELOG.md", "version.txt")

def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    extra.pop("error", None)
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def fail_payload(data: dict[str, Any], default: str, exit_code: int, **extra: Any) -> None:
    reserved = {"error", *extra.keys()}
    payload = {k: v for k, v in data.items() if k not in reserved}
    fail(data.get("error") or default, exit_code=exit_code, **extra, **payload)


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[`/]", " ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_frontmatter(content: str) -> dict[str, str]:
    fm, _ = doc_format.split_frontmatter(content)
    if fm is None:
        return {}
    out: dict[str, str] = {}
    for line in fm.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def task_list_is_frozen(root: Path, task_list: str, fm: dict[str, str]) -> bool:
    """File-native frozen frontmatter or issue-store verify-frozen-hash (PRD 043)."""
    if fm.get("frozen", "").lower() == "true":
        return True
    import planning_materialize as pm

    return pm.issue_store_frozen_verified(root, task_list)


def require_task_list_frozen(root: Path, task_list: str, fm: dict[str, str]) -> None:
    if not task_list_is_frozen(root, task_list, fm):
        fail("task list is not frozen; run /sw-freeze first", exit_code=2, halt="unfrozen")


def parse_phases(content: str) -> list[dict[str, str]]:
    return doc_format.extract_phases(content)


def parse_phase_dependencies(content: str) -> list[dict[str, str]] | None:
    return doc_format.extract_phase_dependencies(content)


def normalize_file_path(raw: str) -> str:
    return doc_format.normalize_file_path(raw)


def parse_phase_files(content: str) -> dict[str, list[str]]:
    """Map phase id -> normalized **File:** paths under that phase section."""
    return doc_format.extract_phase_files(content)


def migration_dir(path: str) -> str | None:
    for prefix in MIGRATION_DIRS:
        if path.startswith(prefix) or f"/{prefix}" in path:
            return prefix
    return None


def phase_touches_doc_numbering(paths: list[str], root: Path) -> bool:
    return planning_paths.phase_touches_doc_numbering(paths, root)


def paths_contend(
    left: str, right: str, serialized: list[str], root: Path
) -> tuple[bool, str]:
    if left == right:
        return True, left
    left_m, right_m = migration_dir(left), migration_dir(right)
    if left_m and right_m and left_m == right_m:
        return True, left_m
    for book in RELEASE_BOOKKEEPING:
        left_hit = left == book or left.endswith(f"/{book}")
        right_hit = right == book or right.endswith(f"/{book}")
        if left_hit and right_hit:
            return True, book
    index_paths = planning_paths.index_paths_rel(planning_paths.load_planning_dirs(root))
    for index in index_paths:
        if index in left and index in right:
            return True, index
    if "doc-numbering" in serialized:
        if phase_touches_doc_numbering([left], root) and phase_touches_doc_numbering([right], root):
            return True, "doc-numbering"
    for token in serialized:
        if token.endswith("/**") or token == planning_paths.GOLDEN_MANIFEST_REL:
            if planning_paths.path_matches_serialized_token(left, token) and planning_paths.path_matches_serialized_token(
                right, token
            ):
                return True, token
    if planning_paths.path_matches_generator_output(left) and planning_paths.path_matches_generator_output(right):
        return True, "generator-output"
    return False, ""


def has_path(edges: list[dict[str, str]], src: str, dst: str) -> bool:
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


def graph_has_cycle(items: list[str], edges: list[dict[str, str]]) -> bool:
    nodes = set(items)
    for edge in edges:
        nodes.add(edge["from"])
        nodes.add(edge["to"])
    indeg = {i: 0 for i in nodes}
    adj: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge["to"] not in indeg:
            indeg[edge["to"]] = 0
        if edge["from"] not in indeg:
            indeg[edge["from"]] = 0
        adj[edge["from"]].append(edge["to"])
        indeg[edge["to"]] += 1
    q = deque([i for i in nodes if indeg[i] == 0])
    order: list[str] = []
    while q:
        node = q.popleft()
        order.append(node)
        for nxt in adj[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    return len(order) != len(nodes)


def inject_contention_edges(
    phase_ids: list[str],
    declared_edges: list[dict[str, str]],
    phase_files: dict[str, list[str]],
    contention: dict[str, Any],
    root: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    dirs = planning_paths.load_planning_dirs(root)
    serialized = list(
        contention.get("serialized")
        or planning_paths.contention_serialized_defaults(dirs)
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

    def sort_key(item: str) -> tuple[int, str | int]:
        return (0, int(item)) if str(item).isdigit() else (1, item)

    declared_waves = assign_waves(sorted(graph_nodes, key=sort_key), declared_edges)

    for wave in declared_waves:
        phase_in_wave = [p for p in wave if p in phase_id_set]
        if len(phase_in_wave) < 2:
            continue
        for left in phase_in_wave:
            for right in phase_in_wave:
                if int(left) >= int(right):
                    continue
                files_left = phase_files.get(left, [])
                files_right = phase_files.get(right, [])
                overlap = ""
                contend = False
                for fl in files_left:
                    for fr in files_right:
                        hit, detail = paths_contend(fl, fr, serialized, root)
                        if hit:
                            contend = True
                            overlap = detail or f"{fl} ⟷ {fr}"
                            break
                    if contend:
                        break
                if not contend:
                    continue
                if has_path(declared_edges, right, left):
                    fail(
                        "contention-cycle: shared-file overlap opposes declared ordering",
                        exit_code=20,
                        halt="contention-cycle",
                        phases=[left, right],
                        overlap=overlap,
                    )
                if (left, right) in existing or has_path(all_edges, left, right):
                    continue
                edge = {"from": left, "to": right, "kind": "contention"}
                injected.append(edge)
                all_edges.append(edge)
                existing.add((left, right))
                notices.append(
                    f"contention: phases {left} and {right} serialized ({overlap})"
                )

    if graph_has_cycle(sorted(graph_nodes, key=sort_key), all_edges):
        fail(
            "contention-cycle: combined declared + contention graph has a cycle",
            exit_code=20,
            halt="contention-cycle",
        )
    return all_edges, injected, notices


def apply_contention(
    content: str,
    phases: list[dict[str, str]],
    declared_edges: list[dict[str, str]],
    contention: dict[str, Any],
    root: Path,
) -> tuple[list[list[str]], list[dict[str, str]], list[dict[str, str]], list[str], dict[str, list[str]]]:
    phase_ids = [p["id"] for p in phases]
    phase_files = parse_phase_files(content)
    phase_files = planning_paths.expand_generator_contention_paths(phase_files, content, root)
    edges, injected, contention_notices = inject_contention_edges(
        phase_ids, declared_edges, phase_files, contention, root
    )
    waves = assign_waves(phase_ids, edges)
    return waves, edges, injected, contention_notices, phase_files


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (
        ".cursor/workflow.config.json",
        "workflow.config.json",
        ".sw/workflow.config.example.json",
    ):
        path = root / rel
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return {}


def load_parallel_ceiling(root: Path, args: list[str]) -> int:
    explicit = parse_kv(args, "--ceiling")
    if explicit is not None:
        return int(explicit)
    cfg = load_workflow_config(root)
    worktree = cfg.get("worktree") or {}
    return int(worktree.get("parallelCeiling", 4))


def greedy_wave_batches(phase_ids: list[str], ceiling: int) -> list[list[str]]:
    if ceiling < 1:
        fail("parallelCeiling must be >= 1", exit_code=2)
    if not phase_ids:
        return []
    batches: list[list[str]] = []
    index = 0
    while index < len(phase_ids):
        batches.append(phase_ids[index : index + ceiling])
        index += ceiling
    return batches


def deps_to_edges(
    phases: list[dict[str, str]],
    dep_rows: list[dict[str, str]] | None,
    phase_files: dict[str, list[str]] | None = None,
    root: Path | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    notices: list[str] = []
    phase_ids = {p["id"] for p in phases}
    edges: list[dict[str, str]] = []

    if dep_rows is not None:
        for row in dep_rows:
            phase = row["phase"]
            raw = row["depends_on"].strip().lower()
            if raw in ("none", "—", "-", ""):
                continue
            for dep in re.findall(r"\d+", raw):
                if dep not in phase_ids:
                    fail(f"phase dependency references unknown phase {dep!r}")
                if dep == phase:
                    fail(f"phase {phase} cannot depend on itself")
                edges.append({"from": dep, "to": phase})
        return edges, notices

    sorted_ids = sorted(phase_ids, key=int)
    files = phase_files or {}
    file_edges: list[dict[str, str]] = []
    for i, left in enumerate(sorted_ids):
        for right in sorted_ids[i + 1 :]:
            contend = False
            detail = ""
            for fl in files.get(left, []):
                for fr in files.get(right, []):
                    hit, detail = paths_contend(
                        fl,
                        fr,
                        planning_paths.contention_serialized_defaults(
                            planning_paths.load_planning_dirs(root)
                        ),
                        root,
                    )
                    if hit:
                        contend = True
                        break
                if contend:
                    break
            if contend:
                file_edges.append({"from": left, "to": right, "kind": "file-set"})
                notices.append(
                    f"file-set edge {left}→{right} ({detail or 'shared file overlap'})"
                )
    if file_edges:
        notices.insert(
            0,
            "missing Phase Dependencies table — edges inferred from overlapping **File:** paths",
        )
        return file_edges, notices

    notices.append(
        "missing Phase Dependencies table — sequential fallback edges 1→2, 2→3, …"
    )
    for i in range(1, len(sorted_ids)):
        edges.append({"from": sorted_ids[i - 1], "to": sorted_ids[i]})
    return edges, notices


def assign_waves(items: list[str], edges: list[dict[str, str]]) -> list[list[str]]:
    graph_nodes = set(items)
    for edge in edges:
        graph_nodes.add(edge["from"])
        graph_nodes.add(edge["to"])
    items_list = sorted(graph_nodes, key=lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x)))
    deps = {i: {e["from"] for e in edges if e["to"] == i} for i in items_list}
    if graph_has_cycle(items_list, edges):
        fail("dependency cycle detected", exit_code=20)
    waves: list[list[str]] = []
    remaining = set(items_list)
    while remaining:
        wave = sorted(
            [i for i in remaining if not (deps[i] & remaining)],
            key=lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x)),
        )
        if not wave:
            fail("unable to assign wave", exit_code=20)
        waves.append(wave)
        remaining -= set(wave)
    return waves


def build_waves(items: list[str], edges: list[dict[str, str]]) -> list[list[str]]:
    return assign_waves(items, edges)


def resolve_type(args: list[str], frontmatter: dict[str, str]) -> str:
    explicit = parse_kv(args, "--type")
    if explicit:
        branch_type = explicit
    elif frontmatter.get("type"):
        branch_type = frontmatter["type"]
    else:
        branch_type = "feat"
    if branch_type not in VALID_TYPES:
        fail(
            f"invalid branch type {branch_type!r}; want one of {sorted(VALID_TYPES)}"
        )
    return branch_type


def prd_number_from_path(task_path: Path, frontmatter: dict[str, str]) -> str | None:
    m = re.search(r"tasks-(\d+)-", task_path.name)
    if m:
        return m.group(1)
    prd_ref = frontmatter.get("prd", "")
    m2 = re.search(r"/(\d+)-", prd_ref)
    return m2.group(1) if m2 else None


def feature_slug(frontmatter: dict[str, str], task_path: Path) -> str:
    if frontmatter.get("topic"):
        return slugify(frontmatter["topic"])
    m = re.search(r"tasks-\d+-(.+)\.md$", task_path.name)
    if m:
        return m.group(1)
    return slugify(task_path.stem)


def load_run_state(root: Path) -> dict[str, Any]:
    from wave_state import resolve_state_path

    state_path = resolve_state_path(root)
    if not state_path.is_file():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def phase_status_map(state: dict[str, Any]) -> dict[str, str]:
    phases = state.get("phases") or {}
    if isinstance(phases, dict):
        return {k: v.get("status", "") if isinstance(v, dict) else str(v) for k, v in phases.items()}
    return {}


def resolve_task_list_arg(root: Path, args: list[str]) -> str | None:
    import planning_unit_status as pus

    return pus.resolve_task_list_reference(root, args, parse_kv=parse_kv, has_flag=has_flag)


def detect_mode(args: list[str]) -> str:
    task_list = parse_kv(args, "--task-list") or parse_kv(args, "--unit-id") or parse_kv(args, "--issue")
    items = parse_kv(args, "--items", "")
    edges = parse_kv(args, "--edges", "")
    plan_file = parse_kv(args, "--plan")
    has_multi = bool(items.strip() or edges.strip() or plan_file)
    has_phase = bool(task_list)
    if has_phase and has_multi:
        if has_flag(args, "--combine"):
            return "combined"
        fail(
            "ambiguous input: both task-list and multi-feature item set; pass --combine to mix units",
            exit_code=2,
            halt="disambiguation",
        )
    if has_phase:
        return "phase"
    if has_multi or has_flag(args, "--items"):
        return "multi-feature"
    fail("mode undetected: provide --task-list, --unit-id, --issue, or --items")


def parse_multi_edges(edges_raw: str) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for pair in [x.strip() for x in edges_raw.split(",") if x.strip()]:
        if ":" not in pair:
            fail(f"invalid edge {pair!r}, want item:dependency")
        item, dep = pair.split(":", 1)
        edges.append({"from": dep.strip(), "to": item.strip()})
    return edges


def persist_contention_feedback(
    root: Path,
    target_branch: str,
    notices: list[str],
    injected: list[dict[str, str]],
) -> None:
    """Persist contention serialization feedback for /sw-tasks re-run (PRD 013 R16)."""
    if not injected and not any(n.startswith("contention:") for n in notices):
        return
    from wave_state import load_deliver_state, save_deliver_state

    try:
        state = load_deliver_state(root, target=target_branch)
    except SystemExit:
        return
    state["contentionFeedback"] = {
        "notices": [n for n in notices if n.startswith("contention:") or "serialized" in n],
        "injectedEdges": injected,
        "suggestedTaskListAction": "Re-run /sw-tasks to add explicit ## Phase Dependencies rows",
        "updatedAt": utc_now_iso(),
    }
    save_deliver_state(root, state, target=target_branch)


def utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_tasks_suggest(root: Path, args: list[str]) -> None:
    """Surface durable contention feedback as /sw-tasks re-run suggestions (R16)."""
    from wave_state import load_deliver_state, resolve_state_path

    target = parse_kv(args, "--target")
    task_list = parse_kv(args, "--task-list")
    try:
        state = load_deliver_state(root, target=target, task_list=task_list)
    except SystemExit:
        state = {}
    fb = state.get("contentionFeedback") or {}
    injected = fb.get("injectedEdges") or []
    rows: list[dict[str, str]] = []
    for edge in injected:
        rows.append(
            {
                "phase": edge.get("to", ""),
                "dependsOn": edge.get("from", ""),
                "tableRow": f"| {edge.get('to', '')} | {edge.get('from', '')} |",
            }
        )
    emit(
        {
            "verdict": "pass",
            "action": "tasks-suggest",
            "statePath": str(
                resolve_state_path(root, target=target, task_list=task_list).relative_to(root)
            ),
            "suggestion": fb.get("suggestedTaskListAction")
            or "No contention feedback recorded; nothing to suggest",
            "notices": fb.get("notices") or [],
            "explicitDependencyRows": rows,
            "rerunCommand": "/sw-tasks",
        }
    )


def plan_combined(
    root: Path,
    args: list[str],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Cross-feature plan: frozen phase list + multi-feature units (PRD 013 R13)."""
    task_list = resolve_task_list_arg(root, args)
    assert task_list
    task_path = resolve_task_list_path(root, task_list)
    content = task_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(content)
    require_task_list_frozen(root, task_list, fm)

    branch_type = resolve_type(args, fm)
    slug = feature_slug(fm, task_path)
    branch = f"{branch_type}/{slug}"
    prd_num = prd_number_from_path(task_path, fm)
    phases = parse_phases(content)
    if not phases:
        fail("no phases found in task list")

    multi_raw = parse_kv(args, "--items", "")
    multi_items = [x.strip() for x in multi_raw.split(",") if x.strip()]
    if not multi_items:
        fail("combined plan requires --items")

    phase_files = parse_phase_files(content)
    dep_rows = parse_phase_dependencies(content)
    phase_edges, notices = deps_to_edges(phases, dep_rows, phase_files, root)
    multi_edges = parse_multi_edges(parse_kv(args, "--edges", ""))
    edges = phase_edges + multi_edges
    phase_ids = [p["id"] for p in phases]
    all_ids = phase_ids + multi_items
    if graph_has_cycle(all_ids, edges):
        fail("combined plan has a dependency cycle", exit_code=20, halt="cycle")

    contention = planning_paths.contention_default(root)
    waves, edges, injected, contention_notices, phase_files = apply_contention(
        content, phases, edges, contention, root
    )
    waves = assign_waves(all_ids, edges)
    notices.extend(contention_notices)

    if not has_flag(args, "--skip-base-check"):
        run_base_preflight(root, branch)

    items_out: list[dict[str, Any]] = []
    for p in phases:
        items_out.append(
            {
                "id": p["id"],
                "kind": "phase",
                "slug": p["slug"],
                "title": p["title"],
                "branch": f"{branch}-phase-{p['slug']}",
                "files": phase_files.get(p["id"], []),
            }
        )
    for item in multi_items:
        items_out.append(
            {
                "id": item,
                "kind": "multi-feature",
                "branch": f"feat/{item}",
            }
        )

    out: dict[str, Any] = {
        "verdict": "pass",
        "mode": "combined",
        "source_task_list": task_list,
        "prd_number": prd_num,
        "target": {"type": branch_type, "slug": slug, "branch": branch},
        "items": items_out,
        "edges": edges,
        "waves": waves,
        "contention": {**contention, "injectedEdges": injected},
        "notices": notices + ["combined plan: phase-mode + multi-feature units"],
    }
    if dry_run:
        out["dry_run"] = True
        return out

    plan_path = root / ".cursor" / PLAN_PATH_NAME
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    persist_contention_feedback(root, branch, notices, injected)
    return out


TERMINAL_IN_FLIGHT_ACTIONS = frozenset(
    {
        "terminal",
        "terminal-ship",
        "terminal-checkpoint",
        "finalize-completion",
        "all-phases-complete",
        "suggest-cleanup",
    }
)


def resync_auto_invocation_blocked(state: dict[str, Any]) -> bool:
    """Guard auto-resync while merge or terminal work is in-flight (PRD 059 R11)."""
    if state.get("mergeJournal"):
        return True
    if state.get("nextAction") in TERMINAL_IN_FLIGHT_ACTIONS:
        return True
    terminal_ship = state.get("terminalShip") or {}
    if isinstance(terminal_ship, dict) and terminal_ship.get("status") in {
        "watching",
        "gate-green",
        "local-evidence",
    }:
        return True
    return False


def phase_entry_currency_check(
    root: Path,
    task_list: str,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Phase-entry currency check with optional auto-resync (PRD 059 R11)."""
    from planning_store import materialize_with_resync, resolve_effective_backend
    from wave_deliver_loop import load_plan, tasks_currency_ok
    from wave_state import load_deliver_state, resolve_state_path

    if state is None:
        state_path = resolve_state_path(root)
        if not state_path.is_file():
            return None
        state = load_deliver_state(root)
    plan_path = root / ".cursor" / PLAN_PATH_NAME
    plan: dict[str, Any] = {}
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            plan = {}
    if not plan.get("source_task_list"):
        plan = dict(plan)
        plan["source_task_list"] = task_list

    ok, cause = tasks_currency_ok(root, state, plan)
    if ok:
        return None

    cfg = load_workflow_config(root)
    if resolve_effective_backend(root, cfg).get("effective") != "issue-store":
        return {"verdict": "report-only", "cause": cause or "tasks-currency-divergence"}

    if resync_auto_invocation_blocked(state):
        return {
            "verdict": "report-only",
            "cause": cause or "tasks-currency-divergence",
            "reason": "merge-or-terminal-in-flight",
        }

    import planning_materialize as pm

    unit_id = pm.unit_id_from_task_list_rel(task_list)
    worktree = planning_paths.git_root(root)
    dest = pm.materialized_dest(worktree, task_list)
    return materialize_with_resync(
        root,
        unit_id,
        task_list,
        dest,
        state=state,
        task_list=task_list,
    )


def resolve_task_list_path(root: Path, task_list: str) -> Path:
    """Resolve frozen task list inside the active worktree (R61, PRD 056 R17-R18)."""
    import planning_materialize as pm

    pm.ensure_run_entry_materialized(root, task_list)
    _resolved_rel, path = planning_path_redirect.resolve_readable_path(root, task_list)
    if path is None:
        logical = planning_path_redirect.resolve_path(root, task_list)
        fail(f"task list not found: {logical}")
    try:
        path.relative_to(root.resolve())
    except ValueError:
        fail(
            "task list must be readable inside the active worktree (R61)",
            exit_code=2,
        )
    return path


def run_base_preflight(root: Path, target_branch: str) -> dict[str, Any]:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "wave_preflight.py"),
            str(root),
            "base-check",
            "--target",
            target_branch,
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail(proc.stderr.strip() or proc.stdout.strip() or "base preflight failed")
    if proc.returncode != 0:
        fail(
            payload.get("error", "base-branch preflight failed"),
            exit_code=proc.returncode,
            **{k: v for k, v in payload.items() if k != "error"},
        )
    return payload


def run_capability_index_preflight(root: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "wave_preflight.py"),
            str(root),
            "capability-index-check",
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail(proc.stderr.strip() or proc.stdout.strip() or "capability index preflight failed")
    if proc.returncode != 0:
        fail(
            payload.get("error", "capability index preflight failed"),
            exit_code=proc.returncode,
            **{k: v for k, v in payload.items() if k != "error"},
        )
    return payload


def cmd_run(root: Path, args: list[str]) -> None:
    """Resolve deliver entry reference and materialize frozen task list (PRD 059 R1)."""
    import planning_materialize as pm

    task_list = resolve_task_list_arg(root, args)
    if not task_list:
        fail("provide --task-list, --unit-id, or --issue", exit_code=2, halt="disambiguation")
    result = pm.ensure_run_entry_materialized(root, task_list)
    emit(
        {
            "verdict": "pass",
            "action": "deliver-run-entry",
            "taskList": task_list,
            **result,
        }
    )


def cmd_preflight(root: Path, args: list[str]) -> None:
    mode = detect_mode(args)
    result: dict[str, Any] = {"verdict": "pass", "mode": mode}

    if mode == "phase":
        task_list = resolve_task_list_arg(root, args)
        assert task_list
        task_path = resolve_task_list_path(root, task_list)
        content = task_path.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        run_unit_planning_gate(root, task_list, args)
        phase_entry_currency_check(root, task_list)
        branch_type = resolve_type(args, fm)
        slug = feature_slug(fm, task_path)
        branch = f"{branch_type}/{slug}"
        phases = parse_phases(content)
        if not phases:
            fail("no phases found in task list (### N. headings)")
        dep_rows = parse_phase_dependencies(content)
        phase_files = parse_phase_files(content)
        edges, notices = deps_to_edges(phases, dep_rows, phase_files, root)
        contention = planning_paths.contention_default(root)
        waves, edges, injected, contention_notices, phase_files = apply_contention(
            content, phases, edges, contention, root
        )
        notices.extend(contention_notices)
        result.update(
            {
                "target": {"type": branch_type, "slug": slug, "branch": branch},
                "waves": waves,
                "phaseCount": len(phases),
                "notices": notices,
                "contention": {
                    **contention,
                    "injectedEdges": injected,
                    "phaseFiles": phase_files,
                },
            }
        )
        print(
            f"mode=phase target={branch} waves={len(waves)} phases={len(phases)}",
            file=sys.stderr,
        )
        for n in notices:
            print(f"notice: {n}", file=sys.stderr)
        if not has_flag(args, "--skip-base-check"):
            base_pf = run_base_preflight(root, branch)
            result["basePreflight"] = base_pf
        cap_pf = run_capability_index_preflight(root)
        result["capabilityIndexPreflight"] = cap_pf
        from wave_phase_pr import resolve_phase_pr_base
        phase_pr_base = resolve_phase_pr_base(root)
        if phase_pr_base.get("verdict") != "ok":
            fail_payload(phase_pr_base, "phase-pr-base", exit_code=20)
        result["phasePrBase"] = phase_pr_base
    elif mode == "combined":
        out = plan_combined(root, args, dry_run=True)
        result.update(
            {
                "target": out["target"],
                "waves": out["waves"],
                "phaseCount": sum(1 for i in out["items"] if i.get("kind") == "phase"),
                "itemCount": len(out["items"]),
                "notices": out.get("notices", []),
                "contention": out.get("contention"),
            }
        )
        print(
            f"mode=combined target={out['target']['branch']} waves={len(out['waves'])} items={len(out['items'])}",
            file=sys.stderr,
        )
        if not has_flag(args, "--skip-base-check"):
            base_pf = run_base_preflight(root, out["target"]["branch"])
            result["basePreflight"] = base_pf
        cap_pf = run_capability_index_preflight(root)
        result["capabilityIndexPreflight"] = cap_pf
    else:
        items_raw = parse_kv(args, "--items", "")
        items = [x.strip() for x in items_raw.split(",") if x.strip()]
        edges_raw = parse_kv(args, "--edges", "")
        edges_list: list[dict[str, str]] = []
        for pair in [x.strip() for x in edges_raw.split(",") if x.strip()]:
            if ":" not in pair:
                fail(f"invalid edge {pair!r}, want item:dependency")
            item, dep = pair.split(":", 1)
            edges_list.append({"from": dep.strip(), "to": item.strip()})
        waves = build_waves(items, edges_list) if items else []
        result.update({"waves": waves, "itemCount": len(items)})
        print(f"mode=multi-feature waves={len(waves)} items={len(items)}", file=sys.stderr)

    emit(result, 0)




def run_unit_planning_gate(root: Path, task_list: str, args: list[str]) -> None:
    """PRD 033 unit-level dependency gate + soft-enforce before plan/preflight."""
    import planning_deliver_gate as pdg

    task_path = resolve_task_list_path(root, task_list)
    flags = pdg.parse_gate_flags(args)
    pdg.run_start_revalidate(root, task_path)
    pdg.dependency_gate(
        root,
        task_path,
        override=bool(flags["override"]),
        override_reason=flags["override_reason"],
    )
    pdg.soft_enforce_confirm(root, task_path, confirmed=bool(flags["confirmed"]))


def cmd_next(root: Path, args: list[str]) -> None:
    import planning_deliver_gate as pdg

    pdg.cmd_next(root, args)


def cmd_dependency_gate(root: Path, args: list[str]) -> None:
    import planning_deliver_gate as pdg

    pdg.cmd_dependency_gate(root, args)

def cmd_plan(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run")
    from_phase = parse_kv(args, "--from")
    mode = detect_mode(args)

    if mode == "combined":
        out = plan_combined(root, args, dry_run=dry_run)
        print(
            f"mode=combined target={out['target']['branch']} waves={len(out['waves'])}",
            file=sys.stderr,
        )
        emit(out, 0)

    if mode == "phase":
        task_list = resolve_task_list_arg(root, args)
        assert task_list
        task_path = resolve_task_list_path(root, task_list)
        content = task_path.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        require_task_list_frozen(root, task_list, fm)

        run_unit_planning_gate(root, task_list, args)
        phase_entry_currency_check(root, task_list)

        branch_type = resolve_type(args, fm)
        slug = feature_slug(fm, task_path)
        branch = f"{branch_type}/{slug}"
        prd_num = prd_number_from_path(task_path, fm)
        phases = parse_phases(content)
        if not phases:
            fail("no phases found in task list")
        dep_rows = parse_phase_dependencies(content)
        phase_files_early = parse_phase_files(content)
        edges, notices = deps_to_edges(phases, dep_rows, phase_files_early, root)
        phase_ids = [p["id"] for p in phases]
        contention = planning_paths.contention_default(root)
        waves, edges, injected, contention_notices, phase_files = apply_contention(
            content, phases, edges, contention, root
        )
        notices.extend(contention_notices)

        if not has_flag(args, "--skip-base-check"):
            run_base_preflight(root, branch)

        if from_phase:
            if from_phase not in phase_ids:
                fail(f"--from phase {from_phase!r} not found in task list")
            statuses = phase_status_map(load_run_state(root))
            unmet: list[str] = []
            deps_of = {e["to"]: e["from"] for e in edges}
            # all upstream deps for from_phase must be green-merged
            needed = {e["from"] for e in edges if e["to"] == from_phase}
            for dep in sorted(needed, key=int):
                st = statuses.get(dep, "pending")
                if st != "green-merged":
                    unmet.append(dep)
            if unmet:
                fail(
                    f"--from {from_phase}: upstream phases not green-merged: {', '.join(unmet)}",
                    exit_code=2,
                    halt="from-prerequisite",
                    unmet=unmet,
                )

        items_out = []
        for p in phases:
            phase_branch = f"{branch}-phase-{p['slug']}"
            items_out.append(
                {
                    "id": p["id"],
                    "slug": p["slug"],
                    "title": p["title"],
                    "branch": phase_branch,
                    "files": phase_files.get(p["id"], []),
                }
            )

        out: dict[str, Any] = {
            "verdict": "pass",
            "mode": "phase",
            "source_task_list": task_list,
            "prd_number": prd_num,
            "target": {"type": branch_type, "slug": slug, "branch": branch},
            "items": items_out,
            "edges": edges,
            "waves": waves,
            "contention": {
                **contention,
                "injectedEdges": injected,
            },
            "notices": notices,
        }
        if dry_run:
            out["dry_run"] = True
            emit(out, 0)

        plan_path = root / ".cursor" / PLAN_PATH_NAME
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        persist_contention_feedback(root, branch, notices, injected)
        print(
            f"mode=phase target={branch} waves={len(waves)}",
            file=sys.stderr,
        )
        emit(out, 0)

    # multi-feature (legacy)
    items_raw = parse_kv(args, "--items", "")
    edges_raw = parse_kv(args, "--edges", "")
    items = [x.strip() for x in items_raw.split(",") if x.strip()]
    edges: list[dict[str, str]] = []
    for pair in [x.strip() for x in edges_raw.split(",") if x.strip()]:
        if ":" not in pair:
            fail(f"invalid edge {pair!r}, want item:dependency")
        item, dep = pair.split(":", 1)
        edges.append({"from": dep.strip(), "to": item.strip()})

    if not items:
        fail("multi-feature plan requires --items")

    waves = build_waves(items, edges)
    out = {
        "verdict": "pass",
        "mode": "multi-feature",
        "items": [{"id": i, "branch": f"feat/{i}"} for i in items],
        "edges": edges,
        "waves": waves,
        "contention": planning_paths.contention_default(root),
    }
    if dry_run:
        out["dry_run"] = True
        emit(out, 0)

    plan_path = root / ".cursor" / PLAN_PATH_NAME
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    emit(out, 0)


def cmd_schedule(root: Path, args: list[str]) -> None:
    plan_rel = parse_kv(args, "--plan", ".cursor/sw-deliver-plan.json")
    assert plan_rel
    plan_path = (root / plan_rel).resolve()
    if not plan_path.is_file():
        fail(f"plan not found: {plan_rel}")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid plan JSON: {exc}")

    ceiling = load_parallel_ceiling(root, args)
    waves = plan.get("waves") or []
    schedule: list[dict[str, Any]] = []
    for wave_index, wave in enumerate(waves, start=1):
        batches = greedy_wave_batches(list(wave), ceiling)
        schedule.append(
            {
                "wave": wave_index,
                "phases": wave,
                "batches": [
                    {
                        "parallel": batch,
                        "slotCount": len(batch),
                        "remainderQueued": index + 1 < len(batches),
                    }
                    for index, batch in enumerate(batches)
                ],
                "countsTowardCeiling": True,
            }
        )

    notices = [
        "wave-level /sw-ship phase worktrees count against worktree.parallelCeiling",
        "internal sub-agent dispatch within a phase does not consume ceiling slots",
        "scheduler never unwinds a running phase to admit a queued one",
    ]
    emit(
        {
            "verdict": "pass",
            "parallelCeiling": ceiling,
            "schedule": schedule,
            "notices": notices,
        },
        0,
    )




def phase_plan_fallback_canonical(root: Path, phase_type: str = "ship", phase_id: str | None = None) -> dict[str, Any]:
    """Fail-closed phase fallback — canonical chain from kernel classification (PRD 022 R6)."""
    from wave_plan_validate import phase_fallback_canonical_chain

    return phase_fallback_canonical_chain(root, phase_type=phase_type, phase_id=phase_id)


def wave_plan_fallback_canonical(frozen_plan: dict[str, Any], root: Path) -> dict[str, Any]:
    """Fail-closed wave fallback — canonical waves from frozen deliver plan (PRD 022 R32)."""
    from wave_plan_validate import wave_fallback_canonical_waves

    return wave_fallback_canonical_waves(frozen_plan, root)


def wave_plan_fallback_schedule(root: Path, frozen_plan: dict[str, Any], ceiling: int | None = None) -> dict[str, Any]:
    """Fail-closed wave fallback — ceiling-aware schedule batches (PRD 022 R32)."""
    from wave_plan_validate import wave_fallback_schedule

    return wave_fallback_schedule(root, frozen_plan, ceiling=ceiling)


def wave_plan_serialize_undeclared_overlaps(root: Path, task_list: str) -> dict[str, Any]:
    """Auto-serialize undeclared **File:** overlaps via contention edges (PRD 013 R14)."""
    from wave_plan_validate import apply_undeclared_overlap_serialization

    return apply_undeclared_overlap_serialization(root, task_list)


def cmd_integration(root: Path, args: list[str]) -> None:
    stamp = parse_kv(args, "--stamp")
    branches_raw = parse_kv(args, "--branches", "")
    if not stamp:
        fail("--stamp required")
    branches = [b.strip() for b in branches_raw.split(",") if b.strip()]
    emit(
        {
            "verdict": "pass",
            "integrationBranch": f"integration/{stamp}",
            "mergedBranches": branches,
            "note": "merge + whole-suite check delegated to orchestrator",
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_deliver.py <root> <command> [args...]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]

    if cmd == "run":
        cmd_run(root, args)
    elif cmd == "plan":
        cmd_plan(root, args)
    elif cmd == "preflight":
        cmd_preflight(root, args)
    elif cmd == "schedule":
        cmd_schedule(root, args)
    elif cmd == "integration":
        cmd_integration(root, args)
    elif cmd == "tasks-suggest":
        cmd_tasks_suggest(root, args)
    elif cmd == "next":
        cmd_next(root, args)
    elif cmd == "dependency-gate":
        cmd_dependency_gate(root, args)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
