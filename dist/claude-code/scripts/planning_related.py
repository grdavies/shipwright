#!/usr/bin/env python3
"""Related-units scanner + pull-in proposal flow (PRD 035 R1-R5, R7, R17, R22)."""
from __future__ import annotations
import argparse, getpass, json, os, re, socket, subprocess, sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import planning_graph as pg
import planning_index_gen as pig
import planning_paths as pp
import planning_visibility as pv
from host_lib import load_workflow_config
from wave_json_io import read_json, write_json
STATE_REL = Path(".cursor/hooks/state/planning-related.json")
CHOICES_REL = Path(".cursor/hooks/state/planning-pull-in-choices.json")
GAP_BACKLOG_REL = Path("docs/prds/GAP-BACKLOG.md")
EMISSION_POINT = "pull-in-confirm"
TERMINAL_STATUSES = frozenset({"complete", "resolved", "superseded", "cancelled"})
FROZEN_STATUSES = frozenset({"planned"})
GAP_ID_RE = re.compile(r"GAP-\d{3}")
PRD_NUM_RE = re.compile(r"prd-(\d{3})-|/(\d{3})-[^/]+/|PRD\s+(\d{3})")

@dataclass
class SourceContext:
    unit_id: str
    unit_type: str
    status: str
    frozen: bool
    path: str
    tags: tuple[str, ...] = ()
    related_files: tuple[str, ...] = ()
    prd_number: str | None = None
    topic: str | None = None
    body_excerpt: str = ""

@dataclass
class Proposal:
    candidate_id: str
    candidate_type: str
    title: str
    status: str
    visibility: str
    score: float
    reasons: list[str] = field(default_factory=list)
    stale: bool = False
    route: str = "absorb"
    metadata: dict[str, Any] = field(default_factory=dict)

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def actor_id() -> str:
    return f"{getpass.getuser()}@{socket.gethostname()}"

def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)

def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)

def state_path(root: Path) -> Path:
    return pp.git_root(root) / STATE_REL

def choices_path(root: Path) -> Path:
    return pp.git_root(root) / CHOICES_REL

def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        return {"staleFlagged": [], "confirmedChoices": []}
    data = read_json(path)
    return data if isinstance(data, dict) else {"staleFlagged": [], "confirmedChoices": []}

def save_state(root: Path, state: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, state)


def pull_in_config(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    pull_in = planning.get("pullIn") if isinstance(planning.get("pullIn"), dict) else {}
    threshold_raw = pull_in.get("rankThreshold")
    threshold = float(threshold_raw) if isinstance(threshold_raw, (int, float)) else 0.35
    env_threshold = os.environ.get("SW_PULLIN_RANK_THRESHOLD", "").strip()
    if env_threshold:
        try:
            threshold = float(env_threshold)
        except ValueError:
            pass
    semantic = bool(pull_in.get("semanticMatching", False))
    if os.environ.get("SW_PULLIN_SEMANTIC", "").strip().lower() in {"1", "true", "yes"}:
        semantic = True
    widen = pull_in.get("semanticWidenFactor")
    widen_factor = float(widen) if isinstance(widen, (int, float)) else 0.15
    return {"rankThreshold": threshold, "semanticMatching": semantic, "semanticWidenFactor": widen_factor}

def parse_scalar_list(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(str(x).strip() for x in raw if str(x).strip())
    if isinstance(raw, str) and raw.strip():
        if raw.strip().startswith("[") and raw.strip().endswith("]"):
            inner = raw.strip()[1:-1]
            return tuple(x.strip().strip("'\"") for x in inner.split(",") if x.strip())
        return (raw.strip(),)
    return ()

def read_frontmatter(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return pig.parse_frontmatter(path.read_text(encoding="utf-8")) or {}

def body_excerpt(path: Path, limit: int = 400) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    return text[:limit]

def extract_prd_number(*hints: str) -> str | None:
    for hint in hints:
        if not hint:
            continue
        for match in PRD_NUM_RE.finditer(hint):
            for group in match.groups():
                if group:
                    return group
    return None

def resolve_source_path(root: Path, path_arg: str) -> Path:
    worktree = pp.git_root(root)
    path = Path(path_arg)
    if not path.is_absolute():
        path = worktree / path
    return path.resolve()

def source_from_path(root: Path, path_arg: str) -> SourceContext:
    path = resolve_source_path(root, path_arg)
    worktree = pp.git_root(root)
    rel = str(path.relative_to(worktree)) if path.is_relative_to(worktree) else str(path)
    fm = read_frontmatter(path)
    unit_id = str(fm.get("id", "")).strip() or path.parent.name
    frozen = fm.get("frozen") is True or str(fm.get("frozen", "")).lower() == "true"
    if not frozen and path.is_file():
        frozen = bool(re.search(r"^frozen:\s*true\s*$", path.read_text(encoding="utf-8")[:1200], re.MULTILINE))
    tags = parse_scalar_list(fm.get("tags"))
    related = parse_scalar_list(fm.get("relatedFiles") or fm.get("related_files"))
    prd_number = extract_prd_number(unit_id, rel, str(fm.get("amends", "")))
    return SourceContext(
        unit_id=unit_id,
        unit_type=str(fm.get("type", "prd")),
        status=str(fm.get("status", "proposed")),
        frozen=frozen,
        path=rel,
        tags=tags,
        related_files=related,
        prd_number=prd_number,
        topic=str(fm.get("topic", "")).strip() or None,
        body_excerpt=body_excerpt(path),
    )

def parse_gap_backlog_schedules(root: Path) -> dict[str, str]:
    path = pp.git_root(root) / GAP_BACKLOG_REL
    if not path.is_file():
        return {}
    schedules: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| GAP-"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 4:
            continue
        gap_id = parts[0]
        if GAP_ID_RE.fullmatch(gap_id):
            schedules[gap_id] = parts[2]
    return schedules

def gap_id_from_unit(unit_id: str) -> str | None:
    match = re.search(r"gap-(\d{3})", unit_id.lower())
    if match:
        return f"GAP-{match.group(1)}"
    if GAP_ID_RE.fullmatch(unit_id.upper()):
        return unit_id.upper()
    return None

def unit_file_map(root: Path) -> dict[str, Path]:
    worktree = pp.git_root(root)
    return {u.id: worktree / u.body_path for u in pig.discover_units(root)}

def is_frozen_unit(fm: dict[str, Any], path: Path) -> bool:
    if fm.get("frozen") is True or str(fm.get("frozen", "")).lower() == "true":
        return True
    return path.is_file() and bool(re.search(r"^frozen:\s*true\s*$", path.read_text(encoding="utf-8")[:1200], re.MULTILINE))

def absorbed_by_complete(units: list[pg.GraphUnit], candidate_id: str) -> bool:
    gap_key = gap_id_from_unit(candidate_id)
    for unit in units:
        if unit.status not in TERMINAL_STATUSES or unit.unit_type not in {"prd", "amendment"}:
            continue
        absorbs = set(unit.absorbs)
        if candidate_id in absorbs or (gap_key and gap_key in absorbs):
            return True
    return False

def shared_values(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    sa = {x.lower() for x in a if x}
    sb = {x.lower() for x in b if x}
    return tuple(sorted(sa & sb))

def jaccard_words(a: str, b: str) -> float:
    wa = {w.lower() for w in re.findall(r"[a-z0-9]{3,}", a)}
    wb = {w.lower() for w in re.findall(r"[a-z0-9]{3,}", b)}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def deterministic_score(source, unit, fm, schedules):
    score = 0.0
    reasons = []
    shared_tags = shared_values(source.tags, parse_scalar_list(fm.get("tags")))
    if shared_tags:
        score += min(0.45, 0.15 * len(shared_tags))
        reasons.append(f"shared-tags:{','.join(shared_tags)}")
    shared_files = shared_values(source.related_files, parse_scalar_list(fm.get("relatedFiles") or fm.get("related_files")))
    if shared_files:
        score += 0.4
        reasons.append(f"shared-files:{','.join(shared_files)}")
    elif source.path and unit.source_path and Path(source.path).name in unit.source_path:
        score += 0.2
        reasons.append("path-lineage")
    if source.unit_id in unit.depends or source.unit_id in unit.extends:
        score += 0.5
        reasons.append("id-edge")
    gap_key = gap_id_from_unit(unit.id)
    if gap_key and source.prd_number:
        schedule = schedules.get(gap_key, "")
        if source.prd_number in schedule or f"PRD {source.prd_number}" in schedule:
            score += 0.6
            reasons.append(f"gap-schedule:{schedule}")
    topic = str(fm.get("topic", "")).strip()
    if source.topic and topic and source.topic.lower() == topic.lower():
        score += 0.25
        reasons.append("shared-topic")
    if source.prd_number and unit.id.startswith(f"prd-{source.prd_number}-"):
        score += 0.15
        reasons.append("prd-lineage")
    return min(1.0, score), reasons

def semantic_bonus(source, fm, cfg):
    if not cfg.get("semanticMatching"):
        return 0.0, []
    bonus = jaccard_words(f"{source.unit_id} {source.body_excerpt}", str(fm.get("title", ""))) * float(cfg.get("semanticWidenFactor", 0.15))
    return (bonus, ["semantic-widen"]) if bonus > 0 else (0.0, [])

def candidate_is_stale(unit, schedules, units, state):
    if unit.status in TERMINAL_STATUSES or absorbed_by_complete(units, unit.id):
        return True
    gap_key = gap_id_from_unit(unit.id)
    if gap_key and schedules.get(gap_key, "").startswith("resolved"):
        return True
    stale_flagged = state.get("staleFlagged") or []
    return unit.id in stale_flagged or bool(gap_key and gap_key in stale_flagged)

def proposal_route(source, target_frozen, accept_frozen_impact):
    if (source.frozen or target_frozen) and not accept_frozen_impact:
        return "amendment"
    if source.frozen and accept_frozen_impact:
        return "absorb-frozen-impact"
    return "absorb"

def build_metadata(root, unit, fm, cfg):
    vis = pv.resolve_unit_visibility(fm, cfg)
    row = {"id": unit.id, "type": unit.unit_type, "title": str(fm.get("title", "")), "status": unit.status, "visibility": vis["visibility"],
           "edges": {"depends": list(unit.depends), "extends": list(unit.extends), "absorbs": list(unit.absorbs)}}
    opaque = fm.get("opaqueTitle")
    if opaque is True or str(opaque).lower() in {"true", "yes", "1"}:
        row["opaqueTitle"] = True
    redacted = pv.redact_index_row(row, vis["visibility"])
    emitted = pv.emit_through_point(EMISSION_POINT, {"visibility": vis["visibility"], "row": redacted})
    meta = emitted.get("row", redacted)
    meta.pop("body", None)
    return meta

def redact_untrusted_payload(root, text):
    worktree = pp.git_root(root)
    script = worktree / "scripts/memory-redact.py"
    if not script.is_file():
        return text
    proc = subprocess.run(["bash", str(script)], input=text, text=True, capture_output=True, cwd=str(worktree))
    return proc.stdout if proc.returncode == 0 else text

def format_confirm_list(proposals, redacted_context):
    lines = ["## Pull-in confirm list", "", "Review proposed absorptions/amendments. Nothing is applied until you confirm.", "",
             "```untrusted", redacted_context, "```", "", "| id | type | score | stale | route | reasons |", "| --- | --- | ---: | --- | --- | --- |"]
    for prop in proposals:
        lines.append(f"| {prop.candidate_id} | {prop.candidate_type} | {prop.score:.2f} | {'yes' if prop.stale else 'no'} | {prop.route} | {'; '.join(prop.reasons)} |")
    lines += ["", "Confirm with: `python3 scripts/planning-related.py confirm --path <source> --accept <id>[,...]`"]
    return "\n".join(lines)


def scan_related(root, source, *, mode, refresh_stale=False):
    cfg = load_workflow_config(pp.git_root(root))
    pull_cfg = pull_in_config(cfg)
    state = load_state(root)
    schedules = parse_gap_backlog_schedules(root)
    units = pg.discover_units(root)
    proposals = []
    suppressed = []
    files = unit_file_map(root)
    for unit in units:
        if unit.id == source.unit_id:
            continue
        if unit.unit_type not in {"gap", "prd", "amendment", "decision", "brainstorm"}:
            continue
        path = files.get(unit.id)
        fm = read_frontmatter(path) if path else {}
        det_score, det_reasons = deterministic_score(source, unit, fm, schedules)
        sem_score, sem_reasons = semantic_bonus(source, fm, pull_cfg)
        score = min(1.0, det_score + sem_score)
        if score < float(pull_cfg["rankThreshold"]):
            continue
        stale = candidate_is_stale(unit, schedules, units, state)
        if stale and not refresh_stale and unit.id in (state.get("staleFlagged") or []):
            suppressed.append(unit.id)
            continue
        target_frozen = is_frozen_unit(fm, path) if path else False
        route = "amendment" if mode == "tasks-rescan" and unit.unit_type == "gap" else "absorb"
        if target_frozen or source.frozen:
            route = proposal_route(source, target_frozen, False)
        meta = build_metadata(root, unit, fm, cfg)
        proposals.append(Proposal(unit.id, unit.unit_type, str(meta.get("title", fm.get("title", ""))), unit.status,
                                  str(meta.get("visibility", "private")), score, det_reasons + sem_reasons, stale, route, meta))
    proposals.sort(key=lambda p: (-p.score, p.candidate_id))
    state["staleFlagged"] = sorted(set((state.get("staleFlagged") or []) + [p.candidate_id for p in proposals if p.stale]))
    state["lastScan"] = {"at": utc_now(), "source": source.unit_id, "mode": mode, "proposalCount": len(proposals)}
    save_state(root, state)
    context_payload = json.dumps({"mode": mode, "source": source.unit_id,
        "proposals": [{"id": p.candidate_id, "score": p.score, "reasons": p.reasons, "metadata": p.metadata} for p in proposals]}, ensure_ascii=False)
    confirm_md = format_confirm_list(proposals, redact_untrusted_payload(root, context_payload))
    return {"verdict": "ok", "mode": mode, "emissionPoint": EMISSION_POINT, "autoAbsorb": False, "appliedEdges": [],
            "source": source.unit_id, "rankThreshold": pull_cfg["rankThreshold"], "semanticMatching": pull_cfg["semanticMatching"],
            "proposals": [{"id": p.candidate_id, "type": p.candidate_type, "title": p.title, "status": p.status, "visibility": p.visibility,
                           "score": round(p.score, 4), "stale": p.stale, "route": p.route, "reasons": p.reasons, "metadata": p.metadata} for p in proposals],
            "suppressedRepeat": suppressed, "confirmList": confirm_md}

def apply_absorb_edge(path, candidate_id):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False
    fm_lines = parts[1].splitlines()
    absorbs_idx = None
    items = []
    for i, line in enumerate(fm_lines):
        if line.strip().startswith("absorbs:"):
            absorbs_idx = i
            val = line.split(":", 1)[1].strip()
            if val.startswith("["):
                items = [x.strip().strip("'\"") for x in val.strip("[]").split(",") if x.strip()]
            elif val:
                items = [val]
            break
    gap_token = gap_id_from_unit(candidate_id) or candidate_id
    if gap_token in items or candidate_id in items:
        return False
    items.append(gap_token)
    new_line = "absorbs: [" + ", ".join(items) + "]"
    if absorbs_idx is None:
        fm_lines.append(new_line)
    else:
        fm_lines[absorbs_idx] = new_line
    path.write_text("---" + "\n".join(fm_lines) + "\n---" + parts[2], encoding="utf-8")
    return True


def confirm_choices(root, source, accept_ids, *, accept_frozen_impact=False):
    worktree = pp.git_root(root)
    source_path = worktree / source.path
    source_fm = read_frontmatter(source_path)
    source_frozen = is_frozen_unit(source_fm, source_path)
    mutations = []
    routes = []
    if source_frozen and not accept_frozen_impact:
        for cid in accept_ids:
            routes.append({"candidate": cid, "route": "amendment", "mutated": False, "reason": "frozen-source-routed-to-amendment"})
    else:
        for cid in accept_ids:
            route = proposal_route(source, source_frozen, accept_frozen_impact)
            if route == "amendment":
                routes.append({"candidate": cid, "route": "amendment", "mutated": False, "reason": "frozen-safe-amendment-track"})
                continue
            if not source_path.is_file():
                routes.append({"candidate": cid, "route": route, "mutated": False, "error": "missing-source"})
                continue
            changed = apply_absorb_edge(source_path, cid)
            mutations.append({"candidate": cid, "route": route, "mutated": changed})
            routes.append({"candidate": cid, "route": route, "mutated": changed})
    choices_state = read_json(choices_path(root)) if choices_path(root).is_file() else {}
    if not isinstance(choices_state, dict):
        choices_state = {}
    pending = choices_state.get("pending", [])
    if not isinstance(pending, list):
        pending = []
    record = {"at": utc_now(), "actor": actor_id(), "source": source.unit_id, "accept": accept_ids,
              "acceptFrozenImpact": accept_frozen_impact, "routes": routes}
    pending.append(record)
    choices_state["pending"] = pending
    choices_path(root).parent.mkdir(parents=True, exist_ok=True)
    write_json(choices_path(root), choices_state)
    reconcile_result = None
    graph_sh = SCRIPT_DIR / "planning-graph.sh"
    if mutations and any(m.get("mutated") for m in mutations) and graph_sh.is_file():
        proc = subprocess.run(["bash", str(graph_sh), "reconcile", "--dry-run"], cwd=str(worktree), capture_output=True, text=True)
        reconcile_result = {"dryRun": True, "exitCode": proc.returncode, "stdout": proc.stdout[-2000:] if proc.stdout else ""}
    state = load_state(root)
    confirmed = state.get("confirmedChoices") or []
    confirmed.append(record)
    state["confirmedChoices"] = confirmed
    save_state(root, state)
    return {"verdict": "ok", "autoAbsorb": False, "appliedEdges": [m for m in mutations if m.get("mutated")],
            "routes": routes, "reconciler": reconcile_result, "humanGated": True}

def cmd_scan(root, args):
    if not args.path:
        fail("--path required for scan")
    result = scan_related(root, source_from_path(root, args.path), mode=args.mode, refresh_stale=bool(args.refresh_stale))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

def cmd_confirm(root, args):
    if not args.path or not args.accept:
        fail("--path and --accept required for confirm")
    result = confirm_choices(root, source_from_path(root, args.path), [x.strip() for x in args.accept.split(",") if x.strip()],
                             accept_frozen_impact=bool(args.accept_frozen_impact))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

def cmd_emit_point(_root, _args):
    print(json.dumps({"points": pv.EMISSION_POINTS, "pullIn": EMISSION_POINT}, indent=2))
    return 0

def main(argv=None):
    parser = argparse.ArgumentParser(description="PRD 035 related-units scanner")
    parser.add_argument("root", nargs="?", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--path", required=True)
    p_scan.add_argument("--mode", choices=["creation", "tasks-rescan"], default="creation")
    p_scan.add_argument("--refresh-stale", action="store_true")
    p_scan.set_defaults(func=cmd_scan)
    p_confirm = sub.add_parser("confirm")
    p_confirm.add_argument("--path", required=True)
    p_confirm.add_argument("--accept", required=True)
    p_confirm.add_argument("--accept-frozen-impact", action="store_true")
    p_confirm.set_defaults(func=cmd_confirm)
    p_emit = sub.add_parser("list-emission-points")
    p_emit.set_defaults(func=cmd_emit_point)
    args = parser.parse_args(argv)
    return int(args.func(Path(args.root).resolve(), args))

if __name__ == "__main__":
    raise SystemExit(main())
