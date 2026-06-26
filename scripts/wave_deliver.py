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

PLAN_PATH_NAME = "sw-deliver-plan.json"
STATE_PATH_NAME = "sw-deliver-state.json"
SCRIPT_DIR = Path(__file__).resolve().parent

_FALLBACK_TYPES = frozenset(
    {"feat", "fix", "perf", "revert", "docs", "chore", "refactor", "test"}
)


def _load_valid_types() -> frozenset[str]:
    """Single-source allowed branch/commit types from release-please-config.json
    (PRD 007 R24 — kept in lockstep with scripts/branch-name-guard.sh)."""
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
CONTENTION_DEFAULT = {
    "serialized": [
        "docs/prds/INDEX.md",
        "docs/decisions/INDEX.md",
        "CHANGELOG.md",
        "version.txt",
        "doc-numbering",
    ],
}
MIGRATION_DIRS = (
    "db/migrate/",
    "supabase/migrations/",
    "prisma/migrations/",
)
RELEASE_BOOKKEEPING = ("CHANGELOG.md", "version.txt")
INDEX_PATHS = ("docs/prds/INDEX.md", "docs/decisions/INDEX.md")


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
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[`/]", " ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_frontmatter(content: str) -> dict[str, str]:
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    block = content[3:end].strip()
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        out[key.strip()] = val.strip()
    return out


def parse_phases(content: str) -> list[dict[str, str]]:
    phases: list[dict[str, str]] = []
    for m in re.finditer(r"^###\s+(\d+)\.\s+(.+)$", content, re.MULTILINE):
        num, title = m.group(1), m.group(2).strip()
        phases.append(
            {
                "id": num,
                "title": title,
                "slug": slugify(title),
            }
        )
    return phases


def parse_phase_dependencies(content: str) -> list[dict[str, str]] | None:
    m = re.search(
        r"^## Phase Dependencies\s*\n+\|[^\n]+\|\n\|[-| ]+\|\n((?:\|[^\n]+\|\n?)+)",
        content,
        re.MULTILINE,
    )
    if not m:
        return None
    rows: list[dict[str, str]] = []
    for line in m.group(1).strip().splitlines():
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 2:
            continue
        phase, depends = parts[0], parts[1]
        if not re.match(r"^\d+$", phase):
            continue
        rows.append({"phase": phase, "depends_on": depends})
    return rows if rows else None


def normalize_file_path(raw: str) -> str:
    path = raw.strip().strip("`").strip()
    path = re.sub(r"\s*→\s*.*$", "", path).strip()
    return path


def parse_phase_files(content: str) -> dict[str, list[str]]:
    """Map phase id -> normalized **File:** paths under that phase section."""
    sections: dict[str, str] = {}
    parts = re.split(r"^###\s+(\d+)\.\s+", content, flags=re.MULTILINE)
    i = 1
    while i + 1 < len(parts):
        sections[parts[i]] = parts[i + 1]
        i += 2

    out: dict[str, list[str]] = {}
    for phase_id, body in sections.items():
        section_body = re.split(
            r"^###\s+\d+\.|^##\s+", body, maxsplit=1, flags=re.MULTILINE
        )[0]
        paths: list[str] = []
        for m in re.finditer(r"\*\*File:\*\*\s*(.+)$", section_body, re.MULTILINE):
            raw = m.group(1).strip()
            for part in re.split(r"[,]|(?:\s+and\s+)", raw):
                part = part.strip().strip("`").strip()
                if not part:
                    continue
                paths.append(normalize_file_path(part))
        out[phase_id] = paths
    return out


def migration_dir(path: str) -> str | None:
    for prefix in MIGRATION_DIRS:
        if path.startswith(prefix) or f"/{prefix}" in path:
            return prefix
    return None


def phase_touches_doc_numbering(paths: list[str]) -> bool:
    for path in paths:
        if path.startswith("docs/prds/") or path.startswith("docs/decisions/"):
            if not path.endswith("INDEX.md"):
                return True
    return False


def paths_contend(
    left: str, right: str, serialized: list[str]
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
    for index in INDEX_PATHS:
        if index in left and index in right:
            return True, index
    if "doc-numbering" in serialized:
        if phase_touches_doc_numbering([left]) and phase_touches_doc_numbering([right]):
            return True, "doc-numbering"
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
    indeg = {i: 0 for i in items}
    adj: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adj[edge["from"]].append(edge["to"])
        indeg[edge["to"]] += 1
    q = deque([i for i in items if indeg[i] == 0])
    order: list[str] = []
    while q:
        node = q.popleft()
        order.append(node)
        for nxt in adj[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    return len(order) != len(items)


def inject_contention_edges(
    phase_ids: list[str],
    declared_edges: list[dict[str, str]],
    phase_files: dict[str, list[str]],
    contention: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    serialized = list(contention.get("serialized", CONTENTION_DEFAULT["serialized"]))
    notices: list[str] = []
    injected: list[dict[str, str]] = []
    existing = {(e["from"], e["to"]) for e in declared_edges}
    all_edges = [dict(e) for e in declared_edges]

    declared_waves = assign_waves(phase_ids, declared_edges)

    for wave in declared_waves:
        if len(wave) < 2:
            continue
        for left in wave:
            for right in wave:
                if int(left) >= int(right):
                    continue
                files_left = phase_files.get(left, [])
                files_right = phase_files.get(right, [])
                overlap = ""
                contend = False
                for fl in files_left:
                    for fr in files_right:
                        hit, detail = paths_contend(fl, fr, serialized)
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

    if graph_has_cycle(phase_ids, all_edges):
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
) -> tuple[list[list[str]], list[dict[str, str]], list[dict[str, str]], list[str], dict[str, list[str]]]:
    phase_ids = [p["id"] for p in phases]
    phase_files = parse_phase_files(content)
    edges, injected, contention_notices = inject_contention_edges(
        phase_ids, declared_edges, phase_files, contention
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
    phases: list[dict[str, str]], dep_rows: list[dict[str, str]] | None
) -> tuple[list[dict[str, str]], list[str]]:
    notices: list[str] = []
    phase_ids = {p["id"] for p in phases}
    edges: list[dict[str, str]] = []

    if dep_rows is None:
        notices.append(
            "missing Phase Dependencies table — sequential fallback edges 2:1, 3:2, …"
        )
        sorted_ids = sorted(phase_ids, key=int)
        for i in range(1, len(sorted_ids)):
            edges.append({"from": sorted_ids[i - 1], "to": sorted_ids[i]})
        return edges, notices

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


def assign_waves(items: list[str], edges: list[dict[str, str]]) -> list[list[str]]:
    deps = {i: {e["from"] for e in edges if e["to"] == i} for i in items}
    if graph_has_cycle(items, edges):
        fail("dependency cycle detected", exit_code=20)
    waves: list[list[str]] = []
    remaining = set(items)
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


def detect_mode(args: list[str]) -> str:
    task_list = parse_kv(args, "--task-list")
    items = parse_kv(args, "--items", "")
    edges = parse_kv(args, "--edges", "")
    plan_file = parse_kv(args, "--plan")
    has_multi = bool(items.strip() or edges.strip() or plan_file)
    has_phase = bool(task_list)
    if has_phase and has_multi:
        fail(
            "ambiguous input: both task-list and multi-feature item set; disambiguate",
            exit_code=2,
            halt="disambiguation",
        )
    if has_phase:
        return "phase"
    if has_multi or has_flag(args, "--items"):
        return "multi-feature"
    fail("mode undetected: provide --task-list or --items")


def resolve_task_list_path(root: Path, task_list: str) -> Path:
    """Resolve frozen task list inside the active worktree (R61)."""
    if ".." in Path(task_list).parts:
        fail(
            "task list must not traverse outside the worktree (R61)",
            exit_code=2,
        )
    task_path = Path(task_list)
    resolved = task_path.resolve() if task_path.is_absolute() else (root / task_list).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        fail(
            "task list must be readable inside the active worktree (R61)",
            exit_code=2,
        )
    if not resolved.is_file():
        fail(f"task list not found: {task_list}")
    return resolved


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


def cmd_preflight(root: Path, args: list[str]) -> None:
    mode = detect_mode(args)
    result: dict[str, Any] = {"verdict": "pass", "mode": mode}

    if mode == "phase":
        task_list = parse_kv(args, "--task-list")
        assert task_list
        task_path = resolve_task_list_path(root, task_list)
        content = task_path.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        branch_type = resolve_type(args, fm)
        slug = feature_slug(fm, task_path)
        branch = f"{branch_type}/{slug}"
        phases = parse_phases(content)
        if not phases:
            fail("no phases found in task list (### N. headings)")
        dep_rows = parse_phase_dependencies(content)
        edges, notices = deps_to_edges(phases, dep_rows)
        contention = CONTENTION_DEFAULT.copy()
        waves, edges, injected, contention_notices, phase_files = apply_contention(
            content, phases, edges, contention
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


def cmd_plan(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run")
    from_phase = parse_kv(args, "--from")
    mode = detect_mode(args)

    if mode == "phase":
        task_list = parse_kv(args, "--task-list")
        assert task_list
        task_path = resolve_task_list_path(root, task_list)
        content = task_path.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)

        if fm.get("frozen", "").lower() != "true":
            fail(
                "task list is not frozen; run /sw-freeze first",
                exit_code=2,
                halt="unfrozen",
            )

        branch_type = resolve_type(args, fm)
        slug = feature_slug(fm, task_path)
        branch = f"{branch_type}/{slug}"
        prd_num = prd_number_from_path(task_path, fm)
        phases = parse_phases(content)
        if not phases:
            fail("no phases found in task list")
        dep_rows = parse_phase_dependencies(content)
        edges, notices = deps_to_edges(phases, dep_rows)
        phase_ids = [p["id"] for p in phases]
        contention = CONTENTION_DEFAULT.copy()
        waves, edges, injected, contention_notices, phase_files = apply_contention(
            content, phases, edges, contention
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
        "contention": CONTENTION_DEFAULT.copy(),
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

    if cmd == "plan":
        cmd_plan(root, args)
    elif cmd == "preflight":
        cmd_preflight(root, args)
    elif cmd == "schedule":
        cmd_schedule(root, args)
    elif cmd == "integration":
        cmd_integration(root, args)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
