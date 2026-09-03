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
import os
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
from wave_run_paths import GLOBAL_PLAN_REL

PLAN_PATH_NAME = Path(GLOBAL_PLAN_REL).name
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
DOC_KIND_TYPES = frozenset({"prd", "tasks", "brainstorm", "decision", "gap"})
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
    if planning_paths.is_human_authored_doc_path(left, root) and planning_paths.is_human_authored_doc_path(
        right, root
    ):
        return True, left
    return False, ""


def inject_shared_authored_doc_edges(
    phase_ids: list[str],
    phase_files: dict[str, list[str]],
    all_edges: list[dict[str, str]],
    existing: set[tuple[str, str]],
    root: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    """Serialize phases that share human-authored docs across waves (PRD 337 R22)."""
    injected: list[dict[str, str]] = []
    notices: list[str] = []

    def sort_key(item: str) -> tuple[int, str | int]:
        return (0, int(item)) if str(item).isdigit() else (1, str(item))

    ordered = sorted(phase_ids, key=sort_key)
    for i, left in enumerate(ordered):
        for right in ordered[i + 1 :]:
            shared = planning_paths.shared_human_authored_paths(
                phase_files.get(left, []), phase_files.get(right, []), root
            )
            if not shared:
                continue
            overlap = shared[0]
            if has_path(all_edges, right, left):
                fail(
                    "contention-cycle: shared-authored-doc overlap opposes declared ordering",
                    exit_code=20,
                    halt="contention-cycle",
                    phases=[left, right],
                    overlap=overlap,
                )
            if (left, right) in existing or has_path(all_edges, left, right):
                continue
            edge = {"from": left, "to": right, "kind": "shared-authored-doc"}
            injected.append(edge)
            all_edges.append(edge)
            existing.add((left, right))
            notices.append(
                f"shared-authored-doc: phases {left} and {right} serialized ({overlap})"
            )
    return all_edges, injected, notices


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

    all_edges, shared_injected, shared_notices = inject_shared_authored_doc_edges(
        phase_ids, phase_files, all_edges, existing, root
    )
    injected.extend(shared_injected)
    notices.extend(shared_notices)

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


def plan_target_type(root: Path, args: list[str]) -> str | None:
    plan_rel = parse_kv(args, "--plan") or GLOBAL_PLAN_REL
    plan_path = root / plan_rel
    if not plan_path.is_file():
        return None
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        raw = (data.get("target") or {}).get("type")
        return str(raw) if raw else None
    except (OSError, json.JSONDecodeError):
        return None


def resolve_type(
    args: list[str],
    frontmatter: dict[str, str],
    *,
    plan_target_type: str | None = None,
) -> str:
    explicit = parse_kv(args, "--type")
    fm_type = frontmatter.get("type")
    if explicit:
        branch_type = explicit
    elif plan_target_type and plan_target_type not in DOC_KIND_TYPES:
        branch_type = plan_target_type
    elif fm_type and fm_type not in DOC_KIND_TYPES:
        branch_type = fm_type
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


def orchestrator_worktree_name_for_target(target: str) -> str:
    slug = target.split("/", 1)[1] if "/" in target else target
    return f"{slug}-orchestrator"


def orchestrator_worktree_path_for_target(root: Path, target: str) -> Path:
    from wave_lifecycle import git_toplevel

    top = git_toplevel(root)
    return top / ".sw-worktrees" / orchestrator_worktree_name_for_target(target)


def is_bare_main_entry(root: Path) -> bool:
    """True when cwd would be blocked by sw-assert-worktree (bare default branch)."""
    script = SCRIPT_DIR / "sw-assert-worktree.py"
    if not script.is_file():
        return False
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 1


def resolve_run_entry_target(
    root: Path, task_list: str, args: list[str] | None = None
) -> dict[str, str]:
    """Derive integration target branch for deliver run entry (PRD 337 R7)."""
    loop_args = args or []
    task_path = _task_list_path_for_light_derive(root, task_list)
    fm: dict[str, str] = {}
    if task_path.is_file():
        fm = parse_frontmatter(task_path.read_text(encoding="utf-8"))
    else:
        stem = Path(task_list).name
        match = re.search(r"^tasks-\d+-(.+)\.md$", stem)
        if not match:
            fail(f"task list not found for run entry target: {task_list}", exit_code=2)
        slug = match.group(1)
        branch_type = resolve_type(
            loop_args, fm, plan_target_type=plan_target_type(root, loop_args)
        )
        return {"type": branch_type, "slug": slug, "branch": f"{branch_type}/{slug}"}
    branch_type = resolve_type(
        loop_args, fm, plan_target_type=plan_target_type(root, loop_args)
    )
    slug = feature_slug(fm, task_path)
    return {"type": branch_type, "slug": slug, "branch": f"{branch_type}/{slug}"}


def _orchestrator_shipwright_state_path(path: Path) -> Path | None:
    git_file = path / ".git"
    if not git_file.is_file():
        return None
    m = re.match(r"gitdir:\s*(.+)", git_file.read_text(encoding="utf-8").splitlines()[0])
    if not m:
        return None
    return Path(m.group(1).strip()) / "shipwright.json"


def _orchestrator_already_adopted(path: Path, target: str) -> bool:
    state_path = _orchestrator_shipwright_state_path(path)
    if state_path is None or not state_path.is_file():
        return False
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return (
        data.get("worktreeRole") == "orchestrator"
        and data.get("targetBranch") == target
    )


def _invoke_orchestrator_provision(root: Path, provision_args: list[str]) -> dict[str, Any]:
    """Run orchestrator provision and return JSON payload (PRD 337 R7)."""
    import io
    from contextlib import redirect_stdout

    from wave_lifecycle import cmd_orchestrator_provision

    buf = io.StringIO()
    exit_code = 0
    try:
        with redirect_stdout(buf):
            cmd_orchestrator_provision(root, provision_args)
    except SystemExit as exc:
        exit_code = int(exc.code) if isinstance(exc.code, int) else 1
        if exit_code != 0:
            raw = buf.getvalue().strip()
            payload: dict[str, Any] = {}
            if raw:
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"raw": raw}
            fail(
                payload.get("error") or "orchestrator provision failed",
                exit_code=exit_code,
                halt=payload.get("halt") or "orchestrator-provision",
                **{k: v for k, v in payload.items() if k not in ("verdict", "error", "halt")},
            )
    raw = buf.getvalue().strip()
    if not raw:
        fail("orchestrator provision returned no payload", exit_code=2)
    payload = json.loads(raw)
    if payload.get("verdict") != "pass":
        fail_payload(payload, "orchestrator provision failed", exit_code)
    return payload


def ensure_run_entry_orchestrator(
    root: Path, task_list: str, args: list[str] | None = None
) -> dict[str, Any]:
    """Bare-main auto-provision and idempotent orchestrator adopt (PRD 337 R7)."""
    loop_args = args or []
    target_info = resolve_run_entry_target(root, task_list, loop_args)
    target = target_info["branch"]
    path = orchestrator_worktree_path_for_target(root, target)
    result: dict[str, Any] = {
        "target": target_info,
        "orchestratorPath": str(path),
    }

    if path.exists():
        if not path.is_dir() or not (path / ".git").exists():
            fail(
                f"orchestrator worktree path exists but is not a worktree: {path}",
                exit_code=20,
                halt="orchestrator-path-conflict",
                remediation=f"remove or relocate {path} before run entry",
                **result,
            )
        if _orchestrator_already_adopted(path, target):
            result.update({"adopted": True, "autoProvisioned": False, "idempotent": True})
            return result
        provision = _invoke_orchestrator_provision(root, ["--target", target])
        result.update(
            {
                "orchestratorProvision": provision,
                "adopted": bool(provision.get("adopted")),
                "autoProvisioned": False,
            }
        )
        return result

    if is_bare_main_entry(root):
        provision = _invoke_orchestrator_provision(root, ["--target", target])
        result.update(
            {
                "orchestratorProvision": provision,
                "adopted": bool(provision.get("adopted")),
                "autoProvisioned": True,
            }
        )
        return result

    result.update({"skipped": True, "reason": "orchestrator-not-required"})
    return result


RESUME_TERMINAL_VERDICTS = frozenset({"complete", "blocked", "rejected"})
NONTERMINAL_VERDICTS = frozenset({"running"})


def canonical_task_list_rel(root: Path, raw: str) -> str:
    path = Path(raw)
    if not path.is_absolute():
        path = (root / path).resolve()
    else:
        path = path.resolve()
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)


def target_branch_from_state(state: dict[str, Any]) -> str | None:
    target = state.get("target")
    if isinstance(target, str) and "/" in target:
        return target
    if isinstance(target, dict):
        branch = target.get("branch")
        if isinstance(branch, str) and branch:
            return branch
    return None


def unit_id_matches_target(
    unit_id: str, target_branch: str | None, task_list: str | None
) -> bool:
    if not unit_id or not target_branch:
        return True
    slug = target_branch.split("/", 1)[1] if "/" in target_branch else target_branch
    uid = unit_id.strip().lower()
    slug_l = slug.lower()
    if uid in (slug_l, f"tasks-{slug_l}"):
        return True
    m = re.match(r"tasks-\d+-(.+)$", uid)
    if m and m.group(1) == slug_l:
        return True
    if task_list:
        import planning_materialize as pm

        expected = pm.unit_id_from_task_list_rel(task_list).lower()
        if uid == expected:
            return True
        m2 = re.match(r"tasks-\d+-(.+)$", expected)
        if m2 and (uid == m2.group(1) or uid == expected):
            return True
    return False


def _task_list_path_for_light_derive(root: Path, task_list: str) -> Path:
    """Resolve a readable task list without run-entry materialize (avoids recursion)."""
    _rel, path = planning_path_redirect.resolve_readable_path(root, task_list)
    if path is not None and path.is_file():
        return path
    return Path(planning_path_redirect.resolve_path(root, task_list))


def derive_target_branch_light(
    root: Path, task_list: str, args: list[str] | None = None
) -> str:
    """Derive integration target branch without base-branch preflight (PRD 068 R1)."""
    loop_args = args or []
    task_path = _task_list_path_for_light_derive(root, task_list)
    fm: dict[str, str] = {}
    if task_path.is_file():
        fm = parse_frontmatter(task_path.read_text(encoding="utf-8"))
    else:
        # Issue-store may not have a local body yet — only the tasks-NNN-slug form
        # is safe to derive without reading content. Bare names (e.g. tasks.md)
        # must fail closed so callers fall back to legacy state / full preflight.
        stem = Path(task_list).name
        match = re.search(r"^tasks-\d+-(.+)\.md$", stem)
        if not match:
            fail(f"task list not found for light derive: {task_list}", exit_code=2)
        return f"feat/{match.group(1)}"
    branch_type = resolve_type(loop_args, fm, plan_target_type=plan_target_type(root, loop_args))
    slug = feature_slug(fm, task_path)
    return f"{branch_type}/{slug}"


def deliver_state_consumable(
    root: Path,
    state: dict[str, Any],
    *,
    task_list: str | None,
    unit_id: str | None = None,
) -> dict[str, Any]:
    """Consumable-state predicate for resume short-circuit (PRD 068 R1)."""
    if not isinstance(state, dict) or not state:
        return {"consumable": False, "reason": "state-empty"}
    verdict = state.get("verdict")
    if verdict in RESUME_TERMINAL_VERDICTS:
        return {
            "consumable": False,
            "reason": "terminal-verdict",
            "verdict": verdict,
            "reenterPreflight": True,
        }
    if verdict != "running" or not state.get("phases"):
        return {"consumable": False, "reason": "not-resumable"}
    target = target_branch_from_state(state)
    if not target:
        return {"consumable": False, "reason": "missing-target"}
    existing_tl = state.get("source_task_list")
    if task_list and existing_tl:
        if canonical_task_list_rel(root, str(existing_tl)) != canonical_task_list_rel(
            root, task_list
        ):
            return {
                "consumable": False,
                "halt": True,
                "cause": "resume:foreign-state",
                "remediation": (
                    "remove scoped deliver state or resume with matching --task-list / --unit-id"
                ),
            }
    if unit_id and not unit_id_matches_target(unit_id, target, task_list):
        return {
            "consumable": False,
            "halt": True,
            "cause": "resume:wrong-slug",
            "expectedBranch": target,
            "unitId": unit_id,
        }
    return {
        "consumable": True,
        "target": target,
        "reason": "resume:consumable",
        "verdict": verdict,
    }


def load_scoped_state_for_task_list(
    root: Path, task_list: str, args: list[str] | None = None
) -> tuple[dict[str, Any], Path | None, str | None]:
    """Load scoped deliver state without nested full preflight (PRD 068 R1)."""
    from wave_json_io import StateCorruptError
    from wave_state import load_state_file, scoped_paths

    try:
        target = derive_target_branch_light(root, task_list, args)
    except SystemExit:
        return {}, None, None
    path = scoped_paths(root, target)["state"]
    if not path.is_file():
        return {}, path, target
    try:
        from wave_json_io import read_json

        return read_json(path), path, target
    except StateCorruptError as exc:
        fail(
            f"corrupt durable state: {exc}",
            exit_code=20,
            halt="resume:state-corrupt",
            cause="resume:state-corrupt",
            path=str(path),
        )
        return {}, path, target


def evaluate_resume_short_circuit(root: Path, args: list[str]) -> dict[str, Any]:
    """Resume consumable check for preflight/run short-circuit (PRD 068 R1)."""
    task_list = resolve_task_list_arg(root, args)
    unit_id = parse_kv(args, "--unit-id")
    if not task_list:
        return {"consumable": False, "reason": "no-task-list"}
    state, state_path, target_branch = load_scoped_state_for_task_list(root, task_list, args)
    if not state_path or not state_path.is_file():
        return {"consumable": False, "reason": "state-missing", "taskList": task_list}
    check = deliver_state_consumable(
        root, state, task_list=task_list, unit_id=unit_id
    )
    check["taskList"] = task_list
    if target_branch:
        check["targetBranch"] = target_branch
    if state_path:
        check["statePath"] = str(state_path)
    if check.get("consumable"):
        check["state"] = state
    return check


def resume_preflight_payload(
    root: Path,
    state: dict[str, Any],
    *,
    task_list: str,
    target_branch: str,
) -> dict[str, Any]:
    """Lightweight preflight fields when durable state is consumable (PRD 068 R1)."""
    task_path = resolve_task_list_path(root, task_list)
    content = task_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(content)
    phases = parse_phases(content)
    dep_rows = parse_phase_dependencies(content)
    phase_files = parse_phase_files(content)
    edges, notices = deps_to_edges(phases, dep_rows, phase_files, root)
    contention = planning_paths.contention_default(root)
    waves, edges, injected, contention_notices, phase_files = apply_contention(
        content, phases, edges, contention, root
    )
    notices.extend(contention_notices)
    slug = feature_slug(fm, task_path)
    branch_type = target_branch.split("/", 1)[0] if "/" in target_branch else "feat"
    return {
        "verdict": "pass",
        "mode": "phase",
        "resumeShortCircuit": True,
        "target": {"type": branch_type, "slug": slug, "branch": target_branch},
        "waves": waves,
        "phaseCount": len(phases),
        "notices": notices,
        "contention": {
            **contention,
            "injectedEdges": injected,
            "phaseFiles": phase_files,
        },
        "basePreflight": {"skipped": True, "reason": "resume-consumable"},
        "capabilityIndexPreflight": {"skipped": True, "reason": "resume-consumable"},
        "deliverState": {
            "verdict": state.get("verdict"),
            "currentWave": state.get("currentWave"),
            "nextAction": state.get("nextAction"),
        },
    }


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
    from wave_state import load_deliver_state, relative_under_anchor, resolve_state_path

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
            "statePath": relative_under_anchor(
                resolve_state_path(root, target=target, task_list=task_list), root
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

    if has_flag(args, "--skip-base-check"):
        # R6: reuse cached probe when present; otherwise skip without re-probing
        cached_base_preflight(root, branch)
    else:
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
        # Scope by task list so a legacy breadcrumb / other-run state cannot
        # trigger currency rematerialize + frozen-hash verify for the wrong unit.
        state_path = resolve_state_path(root, task_list=task_list)
        if not state_path.is_file():
            return None
        state = load_deliver_state(root, task_list=task_list)
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


def phase_ship_tasks_currency_auto_repair(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Phase-ship auto-heal for tasks-currency-divergence (PRD 278 R1/D2)."""
    from phase_ship_hygiene import try_auto_repair_tasks_currency_divergence

    return try_auto_repair_tasks_currency_divergence(root, state, plan)


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



def preflight_timeout_seconds(root: Path) -> int:
    """deliver.preflight.timeoutSeconds — default 90 (PRD 067 R5)."""
    cfg = load_workflow_config(root)
    deliver = cfg.get("deliver") if isinstance(cfg.get("deliver"), dict) else {}
    preflight = deliver.get("preflight") if isinstance(deliver.get("preflight"), dict) else {}
    raw = preflight.get("timeoutSeconds", 90)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 90


def preflight_cache_path(root: Path) -> Path:
    return root / ".cursor" / "sw-deliver-preflight-cache.json"


def load_preflight_cache(root: Path) -> dict:
    path = preflight_cache_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_preflight_cache(root: Path, cache: dict) -> None:
    path = preflight_cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")


def cached_base_preflight(root: Path, target_branch: str) -> dict | None:
    """Return cached base-check probe when --skip-base-check (PRD 067 R6)."""
    cache = load_preflight_cache(root)
    entry = cache.get(target_branch)
    if not isinstance(entry, dict):
        return None
    return entry.get("basePreflight") if isinstance(entry.get("basePreflight"), dict) else None


def run_base_preflight(root: Path, target_branch: str) -> dict[str, Any]:
    timeout = preflight_timeout_seconds(root)
    try:
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
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        fail(
            f"base-branch preflight timed out after {timeout}s",
            exit_code=20,
            halt="preflight-timeout",
            resumeCommand="/sw-deliver run",
            timeoutSeconds=timeout,
            target=target_branch,
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail(proc.stderr.strip() or proc.stdout.strip() or "base preflight failed")
    if proc.returncode != 0:
        fail(
            payload.get("error", "base-branch preflight failed"),
            exit_code=proc.returncode,
            resumeCommand="/sw-deliver run",
            **{k: v for k, v in payload.items() if k != "error"},
        )
    cache = load_preflight_cache(root)
    cache[target_branch] = {"basePreflight": payload, "cachedAt": utc_now_iso()}
    save_preflight_cache(root, cache)
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


def derive_run_stage(state: dict[str, Any]) -> str | None:
    stage = state.get("nextAction")
    if isinstance(stage, str) and stage.strip():
        return stage.strip()
    phases = state.get("phases")
    if isinstance(phases, dict):
        for meta in phases.values():
            if isinstance(meta, dict) and meta.get("status") == "in-flight":
                return "phase-in-flight"
    return None


def derive_unit_id(state: dict[str, Any]) -> str | None:
    task_list = state.get("source_task_list")
    if not isinstance(task_list, str) or not task_list.strip():
        return None
    try:
        import planning_materialize as pm

        return pm.unit_id_from_task_list_rel(task_list)
    except Exception:
        stem = Path(task_list).stem
        return stem if stem else None


def is_nonterminal_verdict(verdict: str | None) -> bool:
    return verdict in NONTERMINAL_VERDICTS


def requires_legacy_adoption(root: Path, entry: dict[str, Any]) -> bool:
    from wave_run_paths import state_path as run_state_path

    run_id = entry.get("runId")
    if not isinstance(run_id, str) or not run_id:
        return bool(entry.get("legacy"))
    path = run_state_path(root, run_id)
    if not path.is_file():
        return True
    try:
        from wave_json_io import read_json
        from wave_state import _is_migration_breadcrumb

        data = read_json(path)
        if _is_migration_breadcrumb(data):
            return True
        return not bool(data.get("legacyAdopted") or data.get("adoptedPlanHash"))
    except Exception:
        return True


def enrich_run_entry(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    from wave_state import read_lock_meta, scoped_paths, target_branch_from_state

    state = entry.get("state") if isinstance(entry.get("state"), dict) else {}
    target = entry.get("target") or target_branch_from_state(state)
    unit = entry.get("unit") or derive_unit_id(state) or entry.get("taskList")
    stage = entry.get("stage") or derive_run_stage(state)
    verdict = entry.get("verdict") or state.get("verdict")
    legacy = bool(entry.get("legacy")) or requires_legacy_adoption(root, entry)
    lock = entry.get("lock") or {}
    if not lock and isinstance(target, str) and "/" in target:
        lock_path = scoped_paths(root, target)["lock"]
        meta = read_lock_meta(lock_path) if lock_path.is_file() else {}
        lock = {"held": bool(meta), "holder": meta or None}
    return {
        "runId": entry.get("runId"),
        "targetBranch": target,
        "unit": unit,
        "stage": stage,
        "lock": lock,
        "terminalStatus": verdict,
        "requiresAdoption": legacy,
        "statePath": entry.get("statePath"),
        "taskList": entry.get("taskList") or state.get("source_task_list"),
    }


def list_deliver_runs(root: Path) -> list[dict[str, Any]]:
    from wave_json_io import read_json
    from wave_state import _is_migration_breadcrumb, enumerate_run_scoped_dirs, enumerate_scoped_runs

    runs: list[dict[str, Any]] = []
    for entry in enumerate_run_scoped_dirs(root):
        state_path = root / str(entry.get("statePath") or "")
        state = read_json(state_path) if state_path.is_file() else {}
        payload = {
            **entry,
            "state": state,
            "legacy": requires_legacy_adoption(root, entry),
        }
        runs.append(enrich_run_entry(root, payload))
    seen = {str(r.get("runId") or "") for r in runs if r.get("runId")}
    for entry in enumerate_scoped_runs(root):
        slug = str(entry.get("slug") or "")
        legacy_key = f"legacy-{slug}" if slug else "legacy-global"
        if legacy_key in seen:
            continue
        state_path = root / str(entry.get("statePath") or "")
        state = read_json(state_path) if state_path.is_file() else {}
        if _is_migration_breadcrumb(state):
            continue
        payload = {
            "runId": legacy_key,
            "slug": slug,
            "statePath": entry.get("statePath"),
            "taskList": entry.get("taskList"),
            "verdict": entry.get("verdict"),
            "target": entry.get("target"),
            "state": state,
            "legacy": True,
            "lock": {
                "held": bool(entry.get("lockHeld")),
                "holder": entry.get("lockHolder"),
            },
        }
        runs.append(enrich_run_entry(root, payload))
        seen.add(legacy_key)
    return runs


def nonterminal_deliver_runs(root: Path) -> list[dict[str, Any]]:
    return [r for r in list_deliver_runs(root) if is_nonterminal_verdict(r.get("terminalStatus"))]


def locate_run(root: Path, run_id: str) -> dict[str, Any] | None:
    rid = run_id.strip()
    for entry in list_deliver_runs(root):
        if entry.get("runId") == rid:
            return entry
    return None


def resolve_resume_cardinality(root: Path, args: list[str]) -> dict[str, Any]:
    """Resume locator with explicit run id or single nonterminal cardinality (R21)."""
    explicit = parse_kv(args, "--run-id")
    if explicit:
        located = locate_run(root, explicit)
        if not located:
            fail(
                f"run not found: {explicit}",
                exit_code=20,
                halt="resume:run-not-found",
                runId=explicit,
                runs=list_deliver_runs(root),
            )
        if not is_nonterminal_verdict(located.get("terminalStatus")):
            fail(
                "resume refused: run is terminal",
                exit_code=20,
                halt="resume:terminal-run",
                run=located,
            )
        return {"verdict": "pass", "run": located, "runId": explicit}

    candidates = nonterminal_deliver_runs(root)
    if not candidates:
        fail(
            "no nonterminal deliver runs to resume",
            exit_code=20,
            halt="resume:none",
            runs=list_deliver_runs(root),
        )
    if len(candidates) > 1:
        fail(
            "multiple nonterminal deliver runs; pass --run-id",
            exit_code=20,
            halt="resume:ambiguous",
            runs=candidates,
        )
    only = candidates[0]
    return {
        "verdict": "pass",
        "run": only,
        "runId": only.get("runId"),
        "taskList": only.get("taskList"),
    }


def cmd_list(root: Path, args: list[str]) -> None:
    runs = list_deliver_runs(root)
    emit({"verdict": "pass", "action": "list", "runs": runs, "count": len(runs)})


def cmd_resume_locate(root: Path, args: list[str]) -> None:
    emit(resolve_resume_cardinality(root, args))


def cmd_finalize(root: Path, args: list[str]) -> None:
    """Finalize a deliver run after verified terminal merge (PRD 081 R24)."""
    import wave_terminal as wt

    run_id = parse_kv(args, "--run-id") or os.environ.get("SW_RUN_ID") or os.environ.get(
        "SW_DELIVER_RUN_ID", ""
    )
    if not run_id:
        fail("--run-id or SW_RUN_ID required", exit_code=2, halt="finalize:missing-run-id")
    from wave_state import ensure_run_scoped_state_mirrored, load_run_scoped_state

    state = load_run_scoped_state(root, run_id)
    if not state:
        mirrored = ensure_run_scoped_state_mirrored(root)
        if mirrored and str(mirrored.get("runId") or "") == run_id:
            state = mirrored
        else:
            # Force mirror under the requested run id when slug state exists.
            slug_state = ensure_run_scoped_state_mirrored(root, {"runId": run_id})
            if slug_state:
                state = load_run_scoped_state(root, run_id) or slug_state
    if not state:
        fail(f"run state not found: {run_id}", exit_code=20, halt="finalize:run-not-found")
    payload = wt.finalize_run(
        root,
        run_id,
        state,
        dry_run=has_flag(args, "--dry-run"),
    )
    if payload.get("verdict") == "fail":
        fail(
            payload.get("error", "terminal merge unverified"),
            exit_code=10,
            halt=payload.get("halt") or "finalize:merge-unverified",
            **{k: v for k, v in payload.items() if k not in ("verdict", "error", "halt")},
        )
    emit(payload)


def cmd_run(root: Path, args: list[str]) -> None:
    """Resolve deliver entry reference and materialize frozen task list (PRD 059 R1)."""
    import planning_materialize as pm

    task_list = resolve_task_list_arg(root, args)
    run_id = parse_kv(args, "--run-id")
    if not task_list and not run_id:
        resolved = resolve_resume_cardinality(root, args)
        task_list = str(resolved.get("taskList") or "")
        run_id = str(resolved.get("runId") or "") or None
    elif run_id and not task_list:
        located = locate_run(root, run_id)
        if not located:
            fail(f"run not found: {run_id}", exit_code=20, halt="resume:run-not-found")
        task_list = str(located.get("taskList") or "")
    if not task_list:
        fail("provide --task-list, --unit-id, --issue, or --run-id", exit_code=2, halt="disambiguation")
    resume = evaluate_resume_short_circuit(root, args)
    if resume.get("halt"):
        fail(
            f"resume blocked: {resume.get('cause')}",
            exit_code=20,
            halt=resume.get("cause", "resume-blocked"),
            cause=resume.get("cause"),
            **{k: v for k, v in resume.items() if k not in ("halt", "consumable", "state")},
        )
    if resume.get("consumable"):
        emit(
            {
                "verdict": "pass",
                "action": "deliver-run-entry",
                "taskList": task_list,
                "resumeShortCircuit": True,
                "target": resume.get("target") or resume.get("targetBranch"),
                "deliverState": {
                    "verdict": (resume.get("state") or {}).get("verdict"),
                    "nextAction": (resume.get("state") or {}).get("nextAction"),
                },
            }
        )
    result = pm.ensure_run_entry_materialized(root, task_list)
    orch = ensure_run_entry_orchestrator(root, task_list, args)
    emit(
        {
            "verdict": "pass",
            "action": "deliver-run-entry",
            "taskList": task_list,
            **result,
            "runEntry": orch,
        }
    )


def cmd_preflight(root: Path, args: list[str]) -> None:
    mode = detect_mode(args)
    result: dict[str, Any] = {"verdict": "pass", "mode": mode}

    if mode == "phase":
        task_list = resolve_task_list_arg(root, args)
        assert task_list
        resume = evaluate_resume_short_circuit(root, args)
        if resume.get("halt"):
            fail(
                f"resume blocked: {resume.get('cause')}",
                exit_code=20,
                halt=resume.get("cause", "resume-blocked"),
                cause=resume.get("cause"),
                **{k: v for k, v in resume.items() if k not in ("halt", "consumable", "state")},
            )
        if resume.get("consumable"):
            state = resume["state"]
            target_branch = str(resume.get("targetBranch") or resume.get("target") or "")
            payload = resume_preflight_payload(
                root,
                state,
                task_list=task_list,
                target_branch=target_branch,
            )
            result.update(payload)
            print(
                f"mode=phase target={target_branch} waves={len(payload.get('waves') or [])} resume=short-circuit",
                file=sys.stderr,
            )
            emit(result, 0)
        task_path = resolve_task_list_path(root, task_list)
        content = task_path.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        run_unit_planning_gate(root, task_list, args)
        phase_entry_currency_check(root, task_list)
        branch_type = resolve_type(args, fm, plan_target_type=plan_target_type(root, args))
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
        if has_flag(args, "--skip-base-check"):
            cached = cached_base_preflight(root, branch)
            if cached is not None:
                result["basePreflight"] = {**cached, "fromCache": True}
            else:
                result["basePreflight"] = {"skipped": True, "reason": "skip-base-check-no-cache"}
        else:
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
        if has_flag(args, "--skip-base-check"):
            cached = cached_base_preflight(root, out["target"]["branch"])
            if cached is not None:
                result["basePreflight"] = {**cached, "fromCache": True}
            else:
                result["basePreflight"] = {"skipped": True, "reason": "skip-base-check-no-cache"}
        else:
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


def cmd_plan_shared_docs(root: Path, args: list[str]) -> None:
    """Detect shared human-authored docs and emit serialization plan (PRD 337 R22)."""
    task_list = resolve_task_list_arg(root, args)
    assert task_list
    task_path = resolve_task_list_path(root, task_list)
    content = task_path.read_text(encoding="utf-8")
    phases = parse_phases(content)
    if not phases:
        fail("no phases found in task list")
    phase_ids = [p["id"] for p in phases]
    dep_rows = parse_phase_dependencies(content)
    phase_files = parse_phase_files(content)
    declared_edges, _ = deps_to_edges(phases, dep_rows, phase_files, root)
    contention = planning_paths.contention_default(root)
    waves, edges, injected, notices, expanded_files = apply_contention(
        content, phases, declared_edges, contention, root
    )
    collisions: list[dict[str, Any]] = []
    for left in phase_ids:
        for right in phase_ids:
            if left >= right:
                continue
            shared = planning_paths.shared_human_authored_paths(
                expanded_files.get(left, []), expanded_files.get(right, []), root
            )
            if not shared:
                continue
            collisions.append(
                {
                    "phaseA": left,
                    "phaseB": right,
                    "sharedPaths": shared,
                    "serialized": any(
                        e.get("from") == left and e.get("to") == right for e in injected
                    ),
                }
            )
    task_list_arg = task_list
    emit(
        {
            "verdict": "pass",
            "action": "plan-shared-docs",
            "collisions": collisions,
            "injectedEdges": injected,
            "notices": notices,
            "waves": waves,
            "preUnionRecommended": bool(collisions),
            "remediationCommand": (
                f"python3 scripts/wave.py plan --task-list {task_list_arg}"
                if collisions
                else None
            ),
        },
        0,
    )


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

        branch_type = resolve_type(args, fm, plan_target_type=plan_target_type(root, args))
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

        resume = evaluate_resume_short_circuit(root, args)
        if resume.get("consumable"):
            pass
        elif has_flag(args, "--skip-base-check"):
            # R6: reuse cached probe when present; otherwise skip without re-probing
            cached_base_preflight(root, branch)
        else:
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
    plan_rel = parse_kv(args, "--plan", GLOBAL_PLAN_REL)
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




def cmd_closure_close_phases(root: Path, args: list[str]) -> None:
    """Close done phase sub-issues from deliver ledger + issue-store fallback (PRD 060 R5)."""
    from host_lib import load_workflow_config
    from planning_store import close_done_phase_sub_issues
    from wave_state import load_deliver_state

    prd_unit = parse_kv(args, "--prd-unit")
    if not prd_unit:
        fail("--prd-unit required")
    dry_run = "--dry-run" in args
    cfg = load_workflow_config(root)
    state = load_deliver_state(root)
    result = close_done_phase_sub_issues(root, cfg, prd_unit, state=state, dry_run=dry_run)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result.get("verdict") == "fail":
        fail(result.get("error", "closure-close-phases failed"))

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


def _graph_from_plan_document(plan: dict[str, Any]) -> dict[str, Any]:
    """Compile a deliver plan document into WorkflowGraph IR (read-only)."""
    from graph.legacy_adapters import compile_legacy_plan

    if plan.get("kind") == "WorkflowGraph" or plan.get("apiVersion") == "shipwright.dev/v1alpha1":
        return plan
    if isinstance(plan.get("graph"), dict):
        return plan["graph"]
    phases = plan.get("items") or plan.get("phases")
    if isinstance(phases, list):
        payload = {
            "phases": [
                {
                    "id": item.get("id", index),
                    "slug": item.get("slug") or item.get("name") or item.get("id"),
                    "name": item.get("title") or item.get("slug") or item.get("id"),
                }
                for index, item in enumerate(phases)
                if isinstance(item, dict)
            ],
            "maxConcurrency": (
                (plan.get("contention") or {}).get("maxConcurrency")
                or plan.get("maxConcurrency")
                or 1
            ),
            "maxDurationSeconds": plan.get("maxDurationSeconds", 86400),
            "safety": plan.get("safety")
            or {"humanMergeGate": True, "lockOwner": "explain-plan", "resumeCursor": "explain"},
        }
        return compile_legacy_plan(payload, plan_type="delivery").graph
    if isinstance(plan.get("steps"), list):
        return compile_legacy_plan(plan, plan_type="ship").graph
    fail("explain-plan: plan has no phases/items/steps/graph")


def _load_estimates_from_corpus(
    root: Path, node_ids: list[str]
) -> dict[str, int]:
    """Historical per-node duration percentiles from the durable receipt corpus."""
    from graph.execution_receipts import ExecutionReceiptJournal, default_store_root

    store = default_store_root(root)
    if not store.is_dir():
        return {}
    durations: dict[str, list[int]] = {node_id: [] for node_id in node_ids}
    try:
        journal = ExecutionReceiptJournal(store)
        for receipt in journal.list_receipts():
            node_id = str(receipt.get("nodeId") or "")
            if node_id not in durations:
                continue
            if receipt.get("state") != "complete":
                continue
            durations[node_id].append(int(receipt.get("durationMs") or 0))
    except OSError:
        return {}
    estimates: dict[str, int] = {}
    for node_id, samples in durations.items():
        if not samples:
            continue
        samples.sort()
        # p50 historical duration
        estimates[node_id] = samples[len(samples) // 2]
    return estimates


def cmd_explain_plan(root: Path, args: list[str]) -> None:
    """Read-only graph plan explanation (PRD 269 R10/R12). Does not mutate run state."""
    from graph.observability import GraphObservability, render_graph_text

    # Refuse accidental mutation flags; this surface is intentionally read-only.
    if has_flag(args, "--write") or has_flag(args, "--persist"):
        fail("explain-plan is read-only; refuse --write/--persist")

    graph_json = parse_kv(args, "--graph-json")
    plan_path_arg = parse_kv(args, "--plan")
    task_list = resolve_task_list_arg(root, args)
    compact = has_flag(args, "--compact")
    text_only = has_flag(args, "--text")

    plan: dict[str, Any] | None = None
    if graph_json:
        graph = json.loads(Path(graph_json).read_text(encoding="utf-8"))
    else:
        if plan_path_arg:
            plan_path = Path(plan_path_arg)
            if not plan_path.is_absolute():
                plan_path = root / plan_path
        elif task_list:
            # Build a transient plan from the task list without writing PLAN_PATH.
            task_path = resolve_task_list_path(root, task_list)
            content = task_path.read_text(encoding="utf-8")
            phases = parse_phases(content)
            plan = {
                "items": [
                    {
                        "id": phase["id"],
                        "slug": phase["slug"],
                        "title": phase.get("title") or phase["slug"],
                    }
                    for phase in phases
                ],
                "maxConcurrency": 1,
                "safety": {
                    "humanMergeGate": True,
                    "lockOwner": "explain-plan",
                    "resumeCursor": "explain",
                },
            }
            plan_path = None
        else:
            plan_path = root / ".cursor" / PLAN_PATH_NAME
        if plan is None:
            if plan_path is None or not plan_path.is_file():
                fail(
                    "explain-plan requires --graph-json, --plan, --task-list, "
                    "or an existing deliver plan"
                )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        graph = _graph_from_plan_document(plan)

    node_ids = [str(node["id"]) for node in graph.get("spec", {}).get("nodes", [])]
    estimates = _load_estimates_from_corpus(root, node_ids)
    # Merge declared duration hints already handled inside GraphObservability.
    obs = GraphObservability(graph, receipts=[], estimated_durations=estimates)
    payload = obs.explain_plan()
    if text_only:
        print(render_graph_text(payload, compact=compact, mode="plan"))
        sys.exit(0)
    if compact:
        payload["text"] = render_graph_text(payload, compact=True, mode="plan")
    emit(payload, 0)


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_deliver.py <root> <command> [args...]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]

    # `/sw-deliver --explain-plan ...` — flag form before the subcommand.
    if cmd == "--explain-plan":
        cmd_explain_plan(root, args)
        return

    if cmd == "run":
        if has_flag(args, "--explain-plan"):
            # Prefer explain over mutation when both are present.
            filtered = [item for item in args if item != "--explain-plan"]
            cmd_explain_plan(root, filtered)
            return
        cmd_run(root, args)
    elif cmd == "plan":
        if args and args[0] == "shared-docs":
            cmd_plan_shared_docs(root, args[1:])
            return
        if has_flag(args, "--explain-plan"):
            filtered = [item for item in args if item != "--explain-plan"]
            cmd_explain_plan(root, filtered)
            return
        cmd_plan(root, args)
    elif cmd == "explain-plan":
        cmd_explain_plan(root, args)
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
    elif cmd == "closure-close-phases":
        cmd_closure_close_phases(root, args)
    elif cmd == "list":
        cmd_list(root, args)
    elif cmd == "resume-locate":
        cmd_resume_locate(root, args)
    elif cmd == "finalize":
        cmd_finalize(root, args)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
