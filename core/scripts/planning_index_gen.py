#!/usr/bin/env python3
"""Deterministic dual-region planning INDEX generator (PRD 031 R5/R9/R24)."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths  # noqa: E402
import planning_visibility as pv  # noqa: E402

GENERATION_STATE_REL = ".cursor/hooks/state/planning-index-generation.json"

SCHEMA_MARKER = "<!-- planning-index:schema v1 -->"
PRIVATE_INDEX_NOTE = (
    "<!-- Private/memory rows redact body bytes via planning_visibility (PRD 034 R4). -->"
)

STATUS_PRECEDENCE_DOC = (
    "<!-- Status precedence: lifecycle units read derived.status when populated, "
    "else structural status; gap units use structural status only. -->"
)

REGION_MARKERS: dict[str, tuple[str, str]] = {
    "structural": (
        "<!-- planning-index:structural begin -->",
        "<!-- planning-index:structural end -->",
    ),
    "derived": (
        "<!-- planning-index:derived begin -->",
        "<!-- planning-index:derived end -->",
    ),
    "inFlight": (
        "<!-- planning-index:inFlight begin -->",
        "<!-- planning-index:inFlight end -->",
    ),
}

VALID_WRITERS = frozenset({"generator", "structural", "reconciler", "derived", "deliver", "inFlight"})
WRITER_REGION: dict[str, str] = {
    "generator": "structural",
    "structural": "structural",
    "reconciler": "derived",
    "derived": "derived",
    "deliver": "inFlight",
    "inFlight": "inFlight",
}

UNIT_TYPES = frozenset({"brainstorm", "gap", "prd", "decision", "amendment"})
EDGE_KEYS = ("depends", "blocks", "supersedes", "extends", "absorbs", "prd", "amends", "brainstorm")


@dataclass(frozen=True)
class IndexRegions:
    structural: str
    derived: str
    inFlight: str
    prefix: str
    suffix: str


@dataclass(frozen=True)
class PlanningUnit:
    id: str
    type: str
    status: str
    title: str
    visibility: str
    edges: str
    body_path: str
    opaque_title: bool = False
    edge_map: dict[str, Any] | None = None
    source: str = ""
    schedule: str = ""


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def index_rel(root: Path) -> str:
    dirs = planning_paths.load_planning_dirs(root)
    return planning_paths.join_rel(dirs.planning, "INDEX.md")


def index_path(root: Path) -> Path:
    return planning_paths.git_root(root) / index_rel(root)


def extract_region(content: str, region: str) -> str:
    start, end = REGION_MARKERS[region]
    if start not in content or end not in content:
        raise ValueError(f"missing {region} region markers")
    return content.split(start, 1)[1].split(end, 1)[0]


def parse_regions(content: str) -> IndexRegions:
    prefix = content
    suffix = ""
    first_region = REGION_MARKERS["structural"][0]
    if first_region in content:
        prefix = content.split(first_region, 1)[0]
    last_end = REGION_MARKERS["inFlight"][1]
    if last_end in content:
        suffix = content.split(last_end, 1)[1]
    return IndexRegions(
        structural=extract_region(content, "structural"),
        derived=extract_region(content, "derived"),
        inFlight=extract_region(content, "inFlight"),
        prefix=prefix,
        suffix=suffix,
    )


def render_region(region: str, body: str) -> str:
    start, end = REGION_MARKERS[region]
    return f"{start}\n{body}{end}"




def replace_region_inner(content: str, region: str, new_inner: str) -> str:
    """Splice one region inner body; preserve marker bytes and sibling regions."""
    start, end = REGION_MARKERS[region]
    if start not in content or end not in content:
        raise ValueError(f"missing {region} region markers")
    pre, rest = content.split(start, 1)
    _, post = rest.split(end, 1)
    return pre + start + "\n" + new_inner + end + post

def assemble_index(regions: IndexRegions) -> str:
    header = regions.prefix.rstrip("\n")
    if SCHEMA_MARKER not in header:
        header = (
            "# Planning units INDEX\n\n"
            f"{SCHEMA_MARKER}\n"
            f"{STATUS_PRECEDENCE_DOC}\n"
            f"{PRIVATE_INDEX_NOTE}\n"
        )
    parts = [header, ""]
    for name in ("structural", "derived", "inFlight"):
        body = getattr(regions, name)
        parts.append(render_region(name, body))
    parts.append(regions.suffix.lstrip("\n"))
    text = "\n".join(parts)
    if not text.endswith("\n"):
        text += "\n"
    return text


def parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return ""
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in re.split(r",\s*", inner) if item.strip()]
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


def parse_frontmatter(text: str) -> dict[str, Any] | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm: dict[str, Any] = {}
    for line in parts[1].splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = parse_scalar(value)
    return fm


def body_file_for_unit_dir(unit_dir: Path) -> Path | None:
    for path in sorted(unit_dir.glob("*.md")):
        if path.name.startswith("tasks-"):
            continue
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm and fm.get("id"):
            return path
    return None


def format_edges(fm: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in EDGE_KEYS:
        value = fm.get(key)
        if not value:
            continue
        if isinstance(value, list):
            if value:
                parts.append(f"{key}:{','.join(str(v) for v in value)}")
        else:
            parts.append(f"{key}:{value}")
    return "; ".join(parts)


def parse_opaque_title(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"true", "yes", "1"}
    return False


def unit_frontmatter_dict(unit: PlanningUnit) -> dict[str, Any]:
    fm: dict[str, Any] = {
        "id": unit.id,
        "type": unit.type,
        "status": unit.status,
        "title": unit.title,
    }
    if unit.visibility:
        fm["visibility"] = unit.visibility
    if unit.opaque_title:
        fm["opaqueTitle"] = True
    if unit.edge_map:
        fm.update(unit.edge_map)
    return fm


def resolved_visibility(unit: PlanningUnit, root: Path) -> str:
    from host_lib import load_workflow_config

    cfg = load_workflow_config(planning_paths.git_root(root))
    return pv.resolve_unit_visibility(unit_frontmatter_dict(unit), cfg)["visibility"]


def index_row_dict(unit: PlanningUnit, root: Path) -> dict[str, Any]:
    vis = resolved_visibility(unit, root)
    title = unit.title
    opaque = unit.opaque_title
    if pv.body_is_redacted(vis):
        title = f"{unit.id}: [private]"
        opaque = True
    row: dict[str, Any] = {
        "id": unit.id,
        "type": unit.type,
        "title": title,
        "status": unit.status,
        "visibility": vis,
    }
    if opaque:
        row["opaqueTitle"] = True
    if unit.edge_map:
        for key in EDGE_KEYS:
            val = unit.edge_map.get(key)
            if val:
                row[key] = val
    return pv.redact_index_row(row, vis)



def generation_state_path(root: Path) -> Path:
    return planning_paths.git_root(root) / GENERATION_STATE_REL


def read_generation_state(root: Path) -> dict[str, Any]:
    path = generation_state_path(root)
    if not path.is_file():
        return {"version": 1, "generation": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, TypeError):
        return {"version": 1, "generation": 0}
    return data if isinstance(data, dict) else {"version": 1, "generation": 0}


def write_generation_state(root: Path, state: dict[str, Any]) -> None:
    if not _generation_persist_allowed(root):
        return
    path = generation_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + chr(10), encoding="utf-8")


def mark_index_incomplete(root: Path, reason: str) -> None:
    """Always persist fail-closed incomplete signal (R86), even in hermetic repos."""
    state = read_generation_state(root)
    state["indexIncomplete"] = True
    state["indexIncompleteReason"] = reason
    path = generation_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def clear_index_incomplete(root: Path) -> None:
    state = read_generation_state(root)
    state.pop("indexIncomplete", None)
    state.pop("indexIncompleteReason", None)
    write_generation_state(root, state)


def index_is_complete(root: Path) -> bool:
    return not bool(read_generation_state(root).get("indexIncomplete"))


def read_generation(root: Path) -> int:
    try:
        return int(read_generation_state(root).get("generation", 0))
    except (TypeError, ValueError):
        return 0

def _generation_persist_allowed(root: Path) -> bool:
    """Skip durable generation state when path is not gitignored (hermetic temp repos)."""
    import subprocess

    state_path = generation_state_path(root)
    worktree = planning_paths.git_root(root)
    proc = subprocess.run(
        ["git", "-C", str(worktree), "check-ignore", "-q", str(state_path)],
        capture_output=True,
    )
    return proc.returncode == 0



def bump_generation(root: Path) -> int:
    """Monotonic generation token for serialized INDEX regeneration (R88)."""
    if not _generation_persist_allowed(root):
        return read_generation(root)
    path = generation_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = read_generation(root)
    next_gen = current + 1
    path.write_text(
        json.dumps({"version": 1, "generation": next_gen}, indent=2) + "\n",
        encoding="utf-8",
    )
    return next_gen


def validate_generation(root: Path, expected: int) -> bool:
    """Readers reject non-monotonic generation (R88)."""
    return read_generation(root) >= expected


def discover_units(root: Path) -> list[PlanningUnit]:
    from planning_discover import discover_units as shared_discover

    return shared_discover(root)


def render_index_table(units: list[PlanningUnit], root: Path) -> str:
    lines = [
        "| id | type | title | status | visibility | edges |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for unit in units:
        row = index_row_dict(unit, root)
        title = str(row.get("title", "")).replace("|", "\\|")
        edges = unit.edges.replace("|", "\\|")
        lines.append(
            "| {id} | {type} | {title} | {status} | {visibility} | {edges} |".format(
                id=row["id"],
                type=row["type"],
                title=title,
                status=row["status"],
                visibility=row["visibility"],
                edges=edges,
            )
        )
    return "\n".join(lines) + "\n"

def render_structural_table(units: list[PlanningUnit], root: Path | None = None) -> str:
    if root is None:
        return render_index_table(units, Path("."))
    return render_index_table(units, root)



def parse_derived_status_map(derived_body: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for line in derived_body.splitlines():
        line = line.strip()
        if not line or line.startswith("|") or line.startswith("-"):
            continue
        if ":" in line:
            unit_id, _, status = line.partition(":")
            unit_id = unit_id.strip()
            status = status.strip()
            if unit_id and status:
                statuses[unit_id] = status
    return statuses


def resolve_consumer_status(unit: PlanningUnit, derived_body: str) -> str:
    """Status precedence (R9): derived when populated for lifecycle units; gaps use structural only."""
    if unit.type == "gap":
        return unit.status
    derived = parse_derived_status_map(derived_body)
    return derived.get(unit.id, unit.status)


def read_merge_write(
    existing: str | None,
    *,
    writer: str,
    new_region_body: str,
    root: Path | None = None,
) -> str:
    if writer not in VALID_WRITERS:
        fail(f"invalid writer: {writer!r}", valid=sorted(VALID_WRITERS))
    region_key = WRITER_REGION[writer]
    if existing and all(marker[0] in existing for marker in REGION_MARKERS.values()):
        return replace_region_inner(existing, region_key, new_region_body)
    empty = IndexRegions(
        structural=new_region_body if region_key == "structural" else render_structural_table([], root or Path(".")),
        derived=new_region_body if region_key == "derived" else "\n",
        inFlight=new_region_body if region_key == "inFlight" else "\n",
        prefix="",
        suffix="",
    )
    return assemble_index(empty)


def generate_index(root: Path, *, writer: str = "generator") -> str:
    if not index_is_complete(root):
        fail("index-incomplete: refuse partial INDEX generation", exit_code=20)
    units = discover_units(root)
    structural = render_structural_table(units, root)
    path = index_path(root)
    existing = path.read_text(encoding="utf-8") if path.is_file() else None
    return read_merge_write(existing, writer=writer, new_region_body=structural, root=root)


def write_index(root: Path, content: str, *, dry_run: bool = False) -> Path:
    path = index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not dry_run:
        prior = read_generation(root)
        path.write_text(content, encoding="utf-8")
        generation = bump_generation(root)
        if prior and not validate_generation(root, prior):
            fail("non-monotonic generation token", prior=prior, current=generation)
    return path


def cmd_generate(root: Path, args: list[str]) -> None:
    writer = "generator"
    dry_run = "--dry-run" in args
    if "--writer" in args:
        i = args.index("--writer")
        writer = args[i + 1] if i + 1 < len(args) else writer
    content = generate_index(root, writer=writer)
    rel = index_rel(root)
    if not dry_run:
        write_index(root, content)
    emit(
        {
            "verdict": "pass",
            "action": "planning-index-generate",
            "path": rel,
            "writer": writer,
            "unitCount": len(discover_units(root)),
            "dryRun": dry_run,
        }
    )


def cmd_write_region(root: Path, args: list[str]) -> None:
    if "--region-body" not in args or "--writer" not in args:
        fail("--writer and --region-body required")
    writer = args[args.index("--writer") + 1]
    body_path = Path(args[args.index("--region-body") + 1])
    if not body_path.is_file():
        fail(f"region body not found: {body_path}")
    body = body_path.read_text(encoding="utf-8")
    dry_run = "--dry-run" in args
    path = index_path(root)
    existing = path.read_text(encoding="utf-8") if path.is_file() else None
    content = read_merge_write(existing, writer=writer, new_region_body=body, root=root)
    if not dry_run:
        write_index(root, content)
    emit(
        {
            "verdict": "pass",
            "action": "planning-index-write-region",
            "writer": writer,
            "path": index_rel(root),
            "dryRun": dry_run,
        }
    )


def cmd_resolve_status(root: Path, args: list[str]) -> None:
    unit_id = None
    if "--unit" in args:
        unit_id = args[args.index("--unit") + 1]
    if not unit_id:
        fail("--unit required")
    units = {u.id: u for u in discover_units(root)}
    unit = units.get(unit_id)
    if not unit:
        fail(f"unit not found: {unit_id}", exit_code=20)
    path = index_path(root)
    derived_body = ""
    if path.is_file():
        derived_body = parse_regions(path.read_text(encoding="utf-8")).derived
    status = resolve_consumer_status(unit, derived_body)
    emit(
        {
            "verdict": "pass",
            "action": "resolve-status",
            "unit": unit_id,
            "type": unit.type,
            "structuralStatus": unit.status,
            "consumerStatus": status,
        }
    )


def cmd_parse(root: Path, args: list[str]) -> None:
    path = index_path(root)
    if "--path" in args:
        rel = args[args.index("--path") + 1]
        path = planning_paths.resolve_contained(root, rel)
    if not path.is_file():
        fail(f"INDEX not found: {path}")
    regions = parse_regions(path.read_text(encoding="utf-8"))
    emit(
        {
            "verdict": "pass",
            "action": "parse-regions",
            "regions": {
                "structural": regions.structural,
                "derived": regions.derived,
                "inFlight": regions.inFlight,
            },
        }
    )


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail("usage: planning_index_gen.py <repo-root> <command> ...")
    root = Path(args[0]).resolve()
    cmd_args = args[2:]
    command = args[1]
    commands = {
        "generate": lambda: cmd_generate(root, cmd_args),
        "write-region": lambda: cmd_write_region(root, cmd_args),
        "resolve-status": lambda: cmd_resolve_status(root, cmd_args),
        "parse": lambda: cmd_parse(root, cmd_args),
    }
    handler = commands.get(command)
    if not handler:
        fail(f"unknown command: {command}")
    handler()


if __name__ == "__main__":
    main()
