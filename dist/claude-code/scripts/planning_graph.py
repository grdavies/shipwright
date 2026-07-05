#!/usr/bin/env python3
"""Pure dependency graph module for planning units (PRD 033 R3/R4/R5/R6/R19/R27).

Offline, deterministic: DAG build, cycle detection, blocked derivation, priority+topo ordering.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
import planning_paths as pp  # noqa: E402
import planning_lifecycle as plc  # noqa: E402

TERMINAL_STATUSES = frozenset({"complete", "superseded", "cancelled", "resolved"})
DEPENDENCY_DEAD_TARGET_STATUSES = frozenset({"superseded", "cancelled"})
SATISFIED_STATUSES = frozenset({"complete", "resolved"})


def parse_edge_list(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(str(x) for x in raw if str(x).strip())
    if raw:
        return (str(raw).strip(),)
    return ()


@dataclass(frozen=True)
class GraphUnit:
    id: str
    unit_type: str
    status: str
    priority: int
    depends: tuple[str, ...] = ()
    blocks: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    extends: tuple[str, ...] = ()
    absorbs: tuple[str, ...] = ()
    source_path: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def is_eligible_status(self) -> bool:
        return self.status not in frozenset({"superseded", "cancelled", "deferred", "complete", "resolved"})


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def unit_from_frontmatter(fm: dict[str, Any], source_path: str = "") -> GraphUnit:
    priority = fm.get("priority")
    if not isinstance(priority, int):
        priority = 0
    return GraphUnit(
        id=str(fm.get("id", "")).strip(),
        unit_type=str(fm.get("type", "")),
        status=str(fm.get("status", "")),
        priority=priority,
        depends=parse_edge_list(fm.get("depends")),
        blocks=parse_edge_list(fm.get("blocks")),
        supersedes=parse_edge_list(fm.get("supersedes")),
        extends=parse_edge_list(fm.get("extends")),
        absorbs=parse_edge_list(fm.get("absorbs")),
        source_path=source_path,
    )


def index_units(units: Iterable[GraphUnit]) -> dict[str, GraphUnit]:
    by_id: dict[str, GraphUnit] = {}
    for unit in units:
        if unit.id:
            by_id[unit.id] = unit
    return by_id


def dependency_satisfied(dep: GraphUnit) -> bool:
    return dep.status in SATISFIED_STATUSES


def unmet_dependencies(unit: GraphUnit, by_id: dict[str, GraphUnit]) -> list[str]:
    unmet: list[str] = []
    for dep_id in unit.depends:
        dep = by_id.get(dep_id)
        if dep is None:
            unmet.append(dep_id)
            continue
        if dep.status in DEPENDENCY_DEAD_TARGET_STATUSES:
            continue
        if not dependency_satisfied(dep):
            unmet.append(dep_id)
    return unmet


def is_dependency_dead(unit: GraphUnit, by_id: dict[str, GraphUnit]) -> bool:
    for dep_id in unit.depends:
        dep = by_id.get(dep_id)
        if dep and dep.status in DEPENDENCY_DEAD_TARGET_STATUSES:
            return True
    return False


def derive_blocked(unit: GraphUnit, by_id: dict[str, GraphUnit]) -> bool:
    """R3 — blocked is computed solely from unmet depends edges."""
    if is_dependency_dead(unit, by_id):
        return False
    return bool(unmet_dependencies(unit, by_id))


def is_eligible(unit: GraphUnit, by_id: dict[str, GraphUnit]) -> bool:
    if not unit.is_eligible_status:
        return False
    if derive_blocked(unit, by_id):
        return False
    return not unmet_dependencies(unit, by_id)


def detect_cycle(units: Iterable[GraphUnit]) -> list[str] | None:
    """Return offending cycle path or None when DAG is valid."""
    by_id = index_units(units)
    state: dict[str, int] = {uid: 0 for uid in by_id}
    parent: dict[str, str | None] = {uid: None for uid in by_id}
    cycle_path: list[str] | None = None

    def dfs(node: str) -> bool:
        nonlocal cycle_path
        state[node] = 1
        unit = by_id.get(node)
        if unit:
            for dep in unit.depends:
                if dep not in by_id:
                    continue
                if state[dep] == 0:
                    parent[dep] = node
                    if dfs(dep):
                        return True
                elif state[dep] == 1:
                    path: list[str] = [dep]
                    cur: str | None = node
                    while cur and cur != dep:
                        path.append(cur)
                        cur = parent.get(cur)
                    path.reverse()
                    cycle_path = path
                    return True
        state[node] = 2
        return False

    for uid in sorted(by_id):
        if state[uid] == 0 and dfs(uid):
            return cycle_path
    return None


def topological_order(units: Iterable[GraphUnit]) -> list[str]:
    by_id = index_units(units)
    indegree: dict[str, int] = {uid: 0 for uid in by_id}
    dependents: dict[str, list[str]] = {uid: [] for uid in by_id}
    for unit in by_id.values():
        for dep in unit.depends:
            if dep in by_id:
                indegree[unit.id] += 1
                dependents[dep].append(unit.id)
    queue = deque(sorted(uid for uid, deg in indegree.items() if deg == 0))
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for child in sorted(dependents.get(node, [])):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(order) != len(by_id):
        return []
    return order



def absorption_gap_status(absorber_derived: str, gap_status: str) -> str:
    return plc.gap_absorption_target(absorber_derived, gap_status)


@dataclass(frozen=True)
class EdgeEffects:
    derived: dict[str, str]
    supersede_edges: tuple[tuple[str, str], ...]
    extend_edges: tuple[tuple[str, str], ...]


def apply_edge_effects(units: Iterable[GraphUnit], base_derived: dict[str, str]) -> EdgeEffects:
    """R10/R11 — supersession flips, extends lineage, absorbs gap progression."""
    by_id = index_units(units)
    derived = dict(base_derived)
    supersede_edges: list[tuple[str, str]] = []
    extend_edges: list[tuple[str, str]] = []

    for unit in by_id.values():
        for target_id in unit.extends:
            extend_edges.append((target_id, unit.id))
        for target_id in unit.supersedes:
            supersede_edges.append((target_id, unit.id))
            if target_id in derived:
                derived[target_id] = "superseded"
            elif target_id in by_id:
                derived[target_id] = "superseded"

    for unit in by_id.values():
        if not unit.absorbs:
            continue
        absorber_status = derived.get(unit.id, unit.status)
        for gap_id in unit.absorbs:
            gap = by_id.get(gap_id)
            if not gap or gap.unit_type != "gap":
                continue
            current = derived.get(gap_id, gap.status)
            derived[gap_id] = absorption_gap_status(absorber_status, current)

    return EdgeEffects(
        derived=derived,
        supersede_edges=tuple(sorted(supersede_edges)),
        extend_edges=tuple(sorted(extend_edges)),
    )

def order_eligible(units: Iterable[GraphUnit]) -> list[str]:
    """R6 — priority desc, then topo order, stable tie-break on unit id."""
    by_id = index_units(units)
    eligible = [u for u in by_id.values() if is_eligible(u, by_id)]
    topo = topological_order(by_id.values())
    topo_rank = {uid: i for i, uid in enumerate(topo)}
    eligible.sort(key=lambda u: (-u.priority, topo_rank.get(u.id, 10**9), u.id))
    return [u.id for u in eligible]


def discover_units(root: Path) -> list[GraphUnit]:
    discovered = pig.discover_units(root)
    units: list[GraphUnit] = []
    worktree = pp.git_root(root)
    for du in discovered:
        if du.body_path.startswith("issue:") or du.body_path.startswith("issue-cache:"):
            priority = 0
            fm = {
                "id": du.id,
                "type": du.type,
                "status": du.status,
                "priority": priority,
            }
            if du.edge_map:
                fm.update(du.edge_map)
            units.append(unit_from_frontmatter(fm, du.body_path))
            continue
        body = worktree / du.body_path
        if not body.is_file():
            continue
        fm = pig.parse_frontmatter(body.read_text(encoding="utf-8")) or {}
        units.append(unit_from_frontmatter(fm, du.body_path))
    return units


def parse_frontmatter_file(path: Path) -> GraphUnit | None:
    text = path.read_text(encoding="utf-8")
    fm = pig.parse_frontmatter(text)
    if not fm or not fm.get("id"):
        return None
    return unit_from_frontmatter(fm, str(path))


def staged_unit_paths(root: Path) -> list[Path]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=str(pp.git_root(root)),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    worktree = pp.git_root(root)
    paths: list[Path] = []
    for line in proc.stdout.splitlines():
        rel = line.strip()
        if not rel.endswith(".md"):
            continue
        path = worktree / rel
        if path.is_file():
            paths.append(path)
    return paths


def build_graph_from_repo(root: Path, overlay: dict[str, GraphUnit] | None = None) -> list[GraphUnit]:
    by_id = index_units(discover_units(root))
    if overlay:
        by_id.update(overlay)
    return list(by_id.values())


def cmd_cycle_check(root: Path, args: list[str]) -> None:
    staged_only = "--staged" in args
    overlay: dict[str, GraphUnit] = {}
    if staged_only:
        for path in staged_unit_paths(root):
            unit = parse_frontmatter_file(path)
            if unit:
                overlay[unit.id] = unit
    units = build_graph_from_repo(root, overlay or None)
    cycle = detect_cycle(units)
    if cycle:
        fail("dependency cycle detected", cycle=cycle, exit_code=20)
    emit({"verdict": "pass", "action": "cycle-check", "unitCount": len(units)})


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail("usage: planning_graph.py <repo-root> <command> ...")
    root = Path(args[0]).resolve()
    command = args[1]
    rest = args[2:]
    if command == "cycle-check":
        cmd_cycle_check(root, rest)
    elif command == "reconcile":
        from planning_reconcile import cmd_reconcile

        cmd_reconcile(root, rest)
    elif command == "doctor":
        from planning_reconcile import cmd_doctor

        cmd_doctor(root, rest)
    elif command == "relief-check":
        from planning_reconcile import cmd_relief_check

        cmd_relief_check(root, rest)
    elif command == "schedule-next":
        from planning_scheduler import cmd_next

        cmd_next(root, rest)
    else:
        fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
