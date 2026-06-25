#!/usr/bin/env python3
"""Wave / deliver planning engine — multi-feature and phase-mode."""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

VALID_TYPES = frozenset(
    {"feat", "fix", "perf", "revert", "docs", "chore", "refactor", "test"}
)
PLAN_PATH_NAME = "sw-deliver-plan.json"
STATE_PATH_NAME = "sw-deliver-state.json"
CONTENTION_DEFAULT = {
    "serialized": ["docs/prds/INDEX.md", "docs/decisions/INDEX.md", "doc-numbering"],
}


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


def build_waves(items: list[str], edges: list[dict[str, str]]) -> list[list[str]]:
    item_set = set(items)
    deps = {i: {e["from"] for e in edges if e["to"] == i} for i in items}

    # cycle check (Kahn)
    indeg = {i: 0 for i in items}
    adj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        adj[e["from"]].append(e["to"])
        indeg[e["to"]] += 1
    q = deque([i for i in items if indeg[i] == 0])
    order: list[str] = []
    while q:
        n = q.popleft()
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    if len(order) != len(items):
        fail("dependency cycle detected", exit_code=20)

    waves: list[list[str]] = []
    remaining = set(items)
    while remaining:
        wave = sorted([i for i in remaining if not (deps[i] & remaining)])
        if not wave:
            fail("unable to assign wave", exit_code=20)
        waves.append(wave)
        remaining -= set(wave)
    return waves


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
    state_path = root / ".cursor" / STATE_PATH_NAME
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


def cmd_preflight(root: Path, args: list[str]) -> None:
    mode = detect_mode(args)
    result: dict[str, Any] = {"verdict": "pass", "mode": mode}

    if mode == "phase":
        task_list = parse_kv(args, "--task-list")
        assert task_list
        task_path = (root / task_list).resolve()
        if not task_path.is_file():
            fail(f"task list not found: {task_list}")
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
        phase_ids = [p["id"] for p in phases]
        waves = build_waves(phase_ids, edges)
        result.update(
            {
                "target": {"type": branch_type, "slug": slug, "branch": branch},
                "waves": waves,
                "phaseCount": len(phases),
                "notices": notices,
            }
        )
        print(
            f"mode=phase target={branch} waves={len(waves)} phases={len(phases)}",
            file=sys.stderr,
        )
        for n in notices:
            print(f"notice: {n}", file=sys.stderr)
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
        task_path = (root / task_list).resolve()
        if not task_path.is_file():
            fail(f"task list not found: {task_list}")
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
        waves = build_waves(phase_ids, edges)

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
            "contention": CONTENTION_DEFAULT.copy(),
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
        "items": [{"id": i, "branch": f"pf/{i}"} for i in items],
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
    elif cmd == "integration":
        cmd_integration(root, args)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
