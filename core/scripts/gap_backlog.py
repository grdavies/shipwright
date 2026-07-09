#!/usr/bin/env python3
"""GAP-BACKLOG parser/writer — sole mutation surface for gap row lifecycle (PRD 035 A2 R51–R54)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doc_format
import planning_paths as pp

try:
    # PRD 057 R1/R4: optional dependency — gap_backlog.py stays importable in
    # vendored/standalone contexts where the migration engine isn't present.
    from planning_migrate_issue_store import (
        close_gap_issue,
        gap_backlog_is_readonly,
        gap_unit_ids_scheduled_for_prd,
        issue_store_separate_project,
    )
except ImportError:  # pragma: no cover - defensive fallback, see try_sunset below
    close_gap_issue = None  # type: ignore[assignment]
    gap_backlog_is_readonly = None  # type: ignore[assignment]
    gap_unit_ids_scheduled_for_prd = None  # type: ignore[assignment]
    issue_store_separate_project = None  # type: ignore[assignment]

GAP_ID = re.compile(r"^GAP-(\d+)$", re.I)
CANONICAL_GAP_ID = re.compile(r"^gap-\d+-", re.I)
INDEX_COUNTS = re.compile(r"^\|\s*(resolved|scheduled|open)\s*\|\s*(\d+)\s*\|", re.I)
POLICY_SCHEDULE_PREFIXES = ("deferred", "config:")


@dataclass
class GapRow:
    gap_id: str
    status: str
    schedule: str
    title: str

    @property
    def is_open(self) -> bool:
        return self.status.lower() == "open"

    @property
    def is_scheduled(self) -> bool:
        return self.status.lower() == "scheduled"


@dataclass
class GapBacklog:
    preamble: list[str] = field(default_factory=list)
    index_lines: list[str] = field(default_factory=list)
    table_header: list[str] = field(default_factory=list)
    rows: list[GapRow] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"resolved": 0, "scheduled": 0, "open": 0}
        for row in self.rows:
            key = row.status.lower()
            if key in out:
                out[key] += 1
        return out


def _worktree_base(root: Path) -> Path:
    try:
        return pp.git_root(root)
    except pp.PathEscapeError:
        return root.resolve()


def default_gap_path(root: Path) -> Path:
    dirs = pp.load_planning_dirs(root)
    return _worktree_base(root) / dirs.prds / "GAP-BACKLOG.md"


def canonical_gap_root(root: Path) -> Path:
    dirs = pp.load_planning_dirs(root)
    return _worktree_base(root) / dirs.prds / "gap"


def is_legacy_gap_id(gap_id: str) -> bool:
    return bool(GAP_ID.match(gap_id))


def is_canonical_gap_ref(ref: str) -> bool:
    return bool(CANONICAL_GAP_ID.match(ref.strip()))


def partition_gap_refs(gap_ids: list[str]) -> tuple[list[str], list[str]]:
    legacy: list[str] = []
    canonical: list[str] = []
    for ref in gap_ids:
        ref = ref.strip()
        if not ref:
            continue
        if is_legacy_gap_id(ref):
            legacy.append(ref)
        else:
            canonical.append(ref)
    return legacy, canonical


def update_frontmatter_field(content: str, key: str, value: str) -> str:
    fm, body = doc_format.split_frontmatter(content)
    if fm is None:
        return content
    lines = fm.splitlines()
    out_lines: list[str] = []
    found = False
    for line in lines:
        if line.split(":", 1)[0].strip() == key:
            out_lines.append(f"{key}: {value}")
            found = True
        else:
            out_lines.append(line)
    if not found:
        out_lines.append(f"{key}: {value}")
    return "---\n" + "\n".join(out_lines) + "\n---\n" + body


def resolve_canonical_unit_id(root: Path, ref: str) -> str | None:
    ref = ref.strip()
    gap_root = canonical_gap_root(root)
    if not gap_root.is_dir():
        return None
    exact = gap_root / ref / f"{ref}.md"
    if exact.is_file():
        return ref
    for unit_dir in sorted(gap_root.iterdir()):
        if not unit_dir.is_dir():
            continue
        if unit_dir.name == ref or unit_dir.name.startswith(ref):
            body = unit_dir / f"{unit_dir.name}.md"
            if body.is_file():
                return unit_dir.name
    return None


def canonical_gap_body_path(root: Path, unit_id: str) -> Path:
    return canonical_gap_root(root) / unit_id / f"{unit_id}.md"


def build_legacy_canonical_alias_map(root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    gap_root = canonical_gap_root(root)
    if not gap_root.is_dir():
        return mapping
    for unit_dir in gap_root.iterdir():
        if not unit_dir.is_dir():
            continue
        body = unit_dir / f"{unit_dir.name}.md"
        if not body.is_file():
            continue
        text = body.read_text(encoding="utf-8")
        legacy_id = doc_format.parse_frontmatter_scalar(text, "legacy_gap_id")
        if legacy_id:
            mapping[legacy_id.upper()] = unit_dir.name
    return mapping


def unresolved_legacy_rows(root: Path, backlog: GapBacklog | None = None) -> list[dict[str, str]]:
    if backlog is None:
        gap_path = default_gap_path(root)
        if not gap_path.is_file():
            return []
        backlog = parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
    alias = build_legacy_canonical_alias_map(root)
    unresolved: list[dict[str, str]] = []
    for row in backlog.rows:
        if row.status.lower() not in ("open", "scheduled"):
            continue
        if row.gap_id in alias:
            continue
        sched = row.schedule.strip().lower()
        if sched.startswith(POLICY_SCHEDULE_PREFIXES):
            continue
        unresolved.append({"gapId": row.gap_id, "status": row.status, "schedule": row.schedule})
    return unresolved


def migration_gate_check(root: Path) -> dict[str, Any]:
    unresolved = unresolved_legacy_rows(root)
    return {
        "verdict": "pass" if not unresolved else "fail",
        "action": "gap-backlog-migration-gate",
        "unresolved": unresolved,
        "unresolvedCount": len(unresolved),
    }


def parse_gap_backlog(text: str) -> GapBacklog:
    backlog = GapBacklog()
    lines = text.splitlines()
    mode = "preamble"
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "| ID | Status | Schedule | Title |":
            backlog.table_header = [line, lines[i + 1]] if i + 1 < len(lines) else [line]
            mode = "table"
            i += 2
            continue
        if mode == "table" and line.startswith("| GAP-"):
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 4:
                backlog.rows.append(GapRow(parts[0].upper(), parts[1], parts[2], parts[3]))
            i += 1
            continue
        if mode == "preamble":
            backlog.preamble.append(line)
            if line.startswith("| resolved |") or line.startswith("| scheduled |") or line.startswith("| open |"):
                backlog.index_lines.append(line)
        i += 1
    return backlog


def render_gap_backlog(backlog: GapBacklog) -> str:
    counts = backlog.counts()
    out: list[str] = []
    in_index = False
    index_replaced = False
    for line in backlog.preamble:
        if line.strip() == "| Status | Count |":
            in_index = True
            out.append(line)
            continue
        if in_index and INDEX_COUNTS.match(line):
            if not index_replaced:
                out.append(f"| resolved | {counts['resolved']} |")
                out.append(f"| scheduled | {counts['scheduled']} |")
                out.append(f"| open | {counts['open']} |")
                index_replaced = True
            continue
        if in_index and line.startswith("|---"):
            out.append(line)
            continue
        if in_index and line.strip() == "":
            continue
        if in_index and index_replaced:
            in_index = False
        if "next ID:" in line:
            max_n = max((int(GAP_ID.match(r.gap_id).group(1)) for r in backlog.rows if GAP_ID.match(r.gap_id)), default=0)
            out.append(re.sub(r"`GAP-\d+`", f"`GAP-{max_n + 1:03d}`", line))
            continue
        out.append(line)
    if backlog.table_header:
        out.extend(backlog.table_header)
    for row in backlog.rows:
        out.append(f"| {row.gap_id} | {row.status} | {row.schedule} | {row.title} |")
    return "\n".join(out) + ("\n" if out else "")


def schedule_label(prd: str, amendment: str | None = None) -> str:
    prd_n = prd.zfill(3) if prd.isdigit() else prd
    return f"PRD {prd_n} {amendment.upper()}" if amendment else f"PRD {prd_n}"


def prd_from_path(path: Path) -> tuple[str, str | None]:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"docs/prds/(\d{3})-", str(path))
    prd = m.group(1) if m else ""
    am = None
    if "/amendments/" in str(path):
        am_m = re.search(r"A(\d+)", path.name, re.I)
        if am_m:
            am = f"A{am_m.group(1)}"
    if not prd:
        fm = doc_format.split_frontmatter(text)[0]
        if fm:
            for line in fm.splitlines():
                if line.startswith("amends:"):
                    pm = re.search(r"/(\d{3})-", line.split(":", 1)[1])
                    if pm:
                        prd = pm.group(1)
    return prd, am


def flip_schedule(
    backlog: GapBacklog,
    *,
    gap_ids: list[str],
    prd: str,
    amendment: str | None = None,
    force: bool = False,
) -> list[str]:
    label = schedule_label(prd, amendment)
    flipped: list[str] = []
    want = {g.upper() for g in gap_ids}
    for row in backlog.rows:
        if row.gap_id.upper() not in want:
            continue
        if row.is_open:
            row.status = "scheduled"
            row.schedule = label
            flipped.append(row.gap_id)
        elif force and row.is_scheduled:
            row.schedule = label
            flipped.append(row.gap_id)
        elif row.is_scheduled and row.schedule == label:
            flipped.append(row.gap_id)
    return flipped


def flip_canonical_schedule(
    root: Path,
    *,
    unit_refs: list[str],
    prd: str,
    amendment: str | None = None,
    force: bool = False,
) -> list[str]:
    label = schedule_label(prd, amendment)
    flipped: list[str] = []
    for ref in unit_refs:
        unit_id = resolve_canonical_unit_id(root, ref)
        if not unit_id:
            continue
        path = canonical_gap_body_path(root, unit_id)
        text = path.read_text(encoding="utf-8")
        status = (doc_format.parse_frontmatter_scalar(text, "status") or "open").lower()
        if status == "open":
            text = update_frontmatter_field(text, "status", "scheduled")
            text = update_frontmatter_field(text, "schedule", label)
            path.write_text(text, encoding="utf-8")
            flipped.append(unit_id)
        elif force and status == "scheduled":
            text = update_frontmatter_field(text, "schedule", label)
            path.write_text(text, encoding="utf-8")
            flipped.append(unit_id)
        elif status == "scheduled" and (doc_format.parse_frontmatter_scalar(text, "schedule") or "") == label:
            flipped.append(unit_id)
    return flipped


def flip_canonical_resolve(
    root: Path,
    *,
    prd: str,
    scope_note: str | None = None,
    unit_refs: list[str] | None = None,
) -> list[str]:
    prd_n = str(int(prd)) if prd.isdigit() else prd.lstrip("0") or prd
    sched_re = re.compile(
        rf"^PRD\s+0*{re.escape(str(int(prd_n))) if prd_n.isdigit() else re.escape(prd_n)}(?:\s+A\d+)?$",
        re.I,
    )
    resolved: list[str] = []
    gap_root = canonical_gap_root(root)
    if not gap_root.is_dir():
        return resolved
    want = {resolve_canonical_unit_id(root, r) for r in (unit_refs or []) if r}
    want.discard(None)
    for unit_dir in sorted(gap_root.iterdir()):
        if not unit_dir.is_dir():
            continue
        unit_id = unit_dir.name
        if want and unit_id not in want and not any(unit_id.startswith(w) for w in want if w):
            continue
        path = unit_dir / f"{unit_id}.md"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        status = (doc_format.parse_frontmatter_scalar(text, "status") or "").lower()
        schedule = (doc_format.parse_frontmatter_scalar(text, "schedule") or "").strip()
        if status != "scheduled":
            continue
        if sched_re.match(schedule):
            new_schedule = f"— ({scope_note})" if scope_note else "—"
            text = update_frontmatter_field(text, "status", "resolved")
            text = update_frontmatter_field(text, "schedule", new_schedule)
            path.write_text(text, encoding="utf-8")
            resolved.append(unit_id)
    return resolved


def resolve_for_prd(root: Path, prd: str, *, scope_note: str | None = None) -> dict[str, Any]:
    """Shared in-process gap-resolve for an absorbing PRD (PRD 048 R1; PRD 057 R4).

    Issue-store ``separate-project`` has no local canonical gap file to flip, so
    resolution closes + labels the scheduled gap issues directly instead of
    silently no-oping; ``same-repo`` keeps the pre-existing frontmatter/row edits.
    """
    if issue_store_separate_project is not None and issue_store_separate_project(root):
        return _resolve_for_prd_issue_store(root, prd)
    gap_path = default_gap_path(root)
    try:
        flipped: list[str] = flip_canonical_resolve(root, prd=prd, scope_note=scope_note)
        if not gap_path.is_file():
            return {"verdict": "pass", "flipped": flipped, "error": None}
        backlog = parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
        flipped.extend(flip_resolve(backlog, prd=prd, scope_note=scope_note))
        if flipped and gap_path.is_file():
            gap_path.write_text(render_gap_backlog(backlog), encoding="utf-8")
        return {"verdict": "pass", "flipped": flipped, "error": None}
    except Exception as exc:
        return {"verdict": "partial", "flipped": [], "error": str(exc)}


def _resolve_for_prd_issue_store(root: Path, prd: str) -> dict[str, Any]:
    """Issue-store ``separate-project`` resolution path for ``resolve_for_prd`` (R4).

    Closes + labels every gap issue scheduled for ``prd`` via the shared
    ``close_gap_issue`` helper (idempotent — already-closed/labeled issues are a
    no-op). Any per-issue failure aggregates into an overall ``resolution-partial``
    verdict rather than raising, so callers (``reconcile_lib.set_index_status``)
    can distinguish this from a generic exception-based ``partial``.
    """
    try:
        unit_ids = gap_unit_ids_scheduled_for_prd(root, prd)
    except Exception as exc:
        return {"verdict": "resolution-partial", "flipped": [], "error": str(exc)}
    flipped: list[str] = []
    errors: list[str] = []
    for unit_id in unit_ids:
        outcome = close_gap_issue(root, unit_id)
        if outcome.get("verdict") == "pass":
            flipped.append(unit_id)
        else:
            errors.append(f"{unit_id}: {outcome.get('error')}")
    if errors:
        return {"verdict": "resolution-partial", "flipped": flipped, "error": "; ".join(errors)}
    return {"verdict": "pass", "flipped": flipped, "error": None}


GAP_051_LEGACY_ID = "GAP-051"
PRD_058_GAP_051_PHASE_SLUG = "gap-051-dependency-gate-unit-id-derivation-regression-coverage-r1-r6"
GAP_082_LEGACY_ID = "GAP-082"
PRD_058_GAP_082_PHASE_SLUG = "gap-082-tests-resolve-r16-r17"
GAP_083_LEGACY_ID = "GAP-083"
PRD_058_GAP_083_PHASE_SLUG = "gap-083-tests-resolve-r31-r32"


def flip_resolve_by_gap_ids(
    backlog: GapBacklog,
    *,
    gap_ids: list[str],
    scope_note: str | None = None,
) -> list[str]:
    """Resolve explicit legacy GAP-xxx rows (PRD 058 R6 partial phase delivery)."""
    want = {gid.strip().upper() for gid in gap_ids if gid.strip()}
    resolved: list[str] = []
    for row in backlog.rows:
        if row.gap_id.upper() not in want:
            continue
        if row.status.lower() not in ("open", "scheduled"):
            continue
        row.status = "resolved"
        row.schedule = f"— ({scope_note})" if scope_note else "—"
        resolved.append(row.gap_id)
    return resolved


def resolve_gap_051_for_prd_058(root: Path, *, scope_note: str | None = None) -> dict[str, Any]:
    """Close GAP-051 after PRD 058 gap-051 phase verification (R6)."""
    note = scope_note or "PRD 058 gap-051"
    gap_path = default_gap_path(root)
    if not gap_path.is_file():
        return {"verdict": "pass", "flipped": [], "error": None}
    backlog = parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
    for row in backlog.rows:
        if row.gap_id.upper() == GAP_051_LEGACY_ID and row.is_open:
            row.status = "scheduled"
            row.schedule = schedule_label("058")
    flipped = flip_resolve_by_gap_ids(backlog, gap_ids=[GAP_051_LEGACY_ID], scope_note=note)
    if flipped:
        gap_path.write_text(render_gap_backlog(backlog), encoding="utf-8")
    return {"verdict": "pass", "flipped": flipped, "error": None}


def resolve_gap_082_for_prd_058(root: Path, *, scope_note: str | None = None) -> dict[str, Any]:
    """Close GAP-082 after PRD 058 gap-082 phase verification (R17)."""
    note = scope_note or "PRD 058 gap-082"
    gap_path = default_gap_path(root)
    if not gap_path.is_file():
        return {"verdict": "pass", "flipped": [], "error": None}
    backlog = parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
    for row in backlog.rows:
        if row.gap_id.upper() == GAP_082_LEGACY_ID and row.is_open:
            row.status = "scheduled"
            row.schedule = schedule_label("058")
    flipped = flip_resolve_by_gap_ids(backlog, gap_ids=[GAP_082_LEGACY_ID], scope_note=note)
    if flipped:
        gap_path.write_text(render_gap_backlog(backlog), encoding="utf-8")
    return {"verdict": "pass", "flipped": flipped, "error": None}



def resolve_gap_083_for_prd_058(root: Path, *, scope_note: str | None = None) -> dict[str, Any]:
    """Close gap-083 after PRD 058 Task-dispatch compression verification (R32).

    Resolution is scoped to the Task-dispatch boundary only and does not wait on
    the R30 default-flip parity milestone (Phase 12).
    """
    note = scope_note or "PRD 058 gap-083 Task-dispatch boundary"
    flipped = flip_canonical_resolve(root, prd="058", scope_note=note, unit_refs=["gap-083"])
    gap_path = default_gap_path(root)
    if not gap_path.is_file():
        return {"verdict": "pass", "flipped": flipped, "error": None}
    backlog = parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
    for row in backlog.rows:
        if row.gap_id.upper() == GAP_083_LEGACY_ID and row.is_open:
            row.status = "scheduled"
            row.schedule = schedule_label("058")
    legacy = flip_resolve_by_gap_ids(backlog, gap_ids=[GAP_083_LEGACY_ID], scope_note=note)
    if legacy:
        gap_path.write_text(render_gap_backlog(backlog), encoding="utf-8")
    flipped.extend(legacy)
    return {"verdict": "pass", "flipped": flipped, "error": None}

def flip_resolve(backlog: GapBacklog, *, prd: str, scope_note: str | None = None) -> list[str]:
    prd_n = str(int(prd)) if prd.isdigit() else prd.lstrip("0") or prd
    sched_re = re.compile(rf"^PRD\s+0*{re.escape(str(int(prd_n))) if prd_n.isdigit() else re.escape(prd_n)}(?:\s+A\d+)?$", re.I)
    resolved: list[str] = []
    for row in backlog.rows:
        if not row.is_scheduled:
            continue
        if sched_re.match(row.schedule.strip()):
            row.status = "resolved"
            row.schedule = f"— ({scope_note})" if scope_note else "—"
            resolved.append(row.gap_id)
    return resolved


def check_integrity(backlog: GapBacklog) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    counts = backlog.counts()
    parsed_index: dict[str, int] = {}
    for line in backlog.index_lines:
        m = INDEX_COUNTS.match(line)
        if m:
            parsed_index[m.group(1).lower()] = int(m.group(2))
    if parsed_index:
        for key in ("resolved", "scheduled", "open"):
            if key in parsed_index and parsed_index[key] != counts[key]:
                issues.append({"kind": "index-table-mismatch", "status": key, "index": parsed_index[key], "table": counts[key]})
    seen: set[str] = set()
    for row in backlog.rows:
        if row.gap_id in seen:
            issues.append({"kind": "duplicate-gap-id", "gapId": row.gap_id})
        seen.add(row.gap_id)
    return issues




def assert_gap_backlog_writable(root: Path, *, projection: bool = False) -> None:
  # PRD 057 R1: --projection is an explicit operator opt-in to retain the legacy
  # row even when the store-authoritative guard would otherwise block the write.
  if projection or gap_backlog_is_readonly is None:
    return
  if gap_backlog_is_readonly(root):
    print(json.dumps({
      "verdict": "fail",
      "error": "GAP-BACKLOG is read-only under issue-store separate-project (or migration transition)",
      "halt": "gap-backlog-readonly-shim",
      "remediation": "capture gaps via planning_gap_capture.py, complete migration, or pass --projection to retain the legacy row",
    }))
    sys.exit(20)

def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    parser = argparse.ArgumentParser(prog="gap_backlog.py")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    sub.add_parser("migration-gate")
    sub.add_parser("projection-cutover-ready")
    p_flip = sub.add_parser("flip")
    p_flip.add_argument("--schedule", action="store_true")
    p_flip.add_argument("--force", action="store_true")
    p_flip.add_argument("--resolve", action="store_true")
    p_flip.add_argument("--from-artifact", default="")
    p_flip.add_argument("--gaps", nargs="*", default=[])
    p_flip.add_argument("--prd", default="")
    p_flip.add_argument("--amendment", default="")
    p_flip.add_argument("--scope-note", default="")
    p_flip.add_argument("--gap-path", default="")
    p_flip.add_argument("--projection", action="store_true")
    ns = parser.parse_args(args)
    root = Path(ns.root).resolve()
    if ns.cmd == "migration-gate":
        out = migration_gate_check(root)
        print(json.dumps(out))
        sys.exit(0 if out["verdict"] == "pass" else 1)
        return
    if ns.cmd == "projection-cutover-ready":
        out = migration_gate_check(root)
        out["action"] = "projection-cutover-ready"
        print(json.dumps(out))
        sys.exit(0 if out["verdict"] == "pass" else 1)
        return
    gap_path = Path(getattr(ns, "gap_path", "") or "") if getattr(ns, "gap_path", "") else default_gap_path(root)
    if not gap_path.is_file():
        print(json.dumps({"verdict": "fail", "error": f"GAP-BACKLOG not found: {gap_path}"}))
        sys.exit(2)
    backlog = parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
    if ns.cmd == "list":
        print(json.dumps({"verdict": "pass", "action": "gap-backlog-list", "counts": backlog.counts(), "rows": [{"id": r.gap_id, "status": r.status, "schedule": r.schedule} for r in backlog.rows]}))
        return
    if ns.cmd == "check":
        issues = check_integrity(backlog)
        out = {"verdict": "fail" if issues else "pass", "action": "gap-backlog-check", "issues": issues, "counts": backlog.counts()}
        print(json.dumps(out))
        sys.exit(1 if issues else 0)
    if ns.cmd == "flip":
        assert_gap_backlog_writable(root, projection=bool(ns.projection))
        changed: list[str] = []
        legacy_changed = False
        if ns.schedule:
            gap_ids = list(ns.gaps)
            prd = ns.prd
            amendment = ns.amendment or None
            if ns.from_artifact:
                art = Path(ns.from_artifact)
                if not art.is_absolute():
                    art = root / art
                directives = doc_format.parse_frontmatter_directives(art.read_text(encoding="utf-8"))
                gap_ids = directives.get("absorbs") or []
                if not gap_ids:
                    print(json.dumps({"verdict": "pass", "action": "gap-backlog-flip-schedule", "flipped": []}))
                    return
                prd_p, am_p = prd_from_path(art)
                prd = prd or prd_p
                amendment = amendment or (am_p or "")
            legacy_ids, canonical_ids = partition_gap_refs(gap_ids)
            if legacy_ids:
                flipped_legacy = flip_schedule(backlog, gap_ids=legacy_ids, prd=prd, amendment=amendment, force=bool(ns.force))
                if flipped_legacy:
                    legacy_changed = True
                changed.extend(flipped_legacy)
            if canonical_ids:
                changed.extend(
                    flip_canonical_schedule(
                        root,
                        unit_refs=canonical_ids,
                        prd=prd,
                        amendment=amendment,
                        force=bool(ns.force),
                    )
                )
        elif ns.resolve:
            scope_note = ns.scope_note.strip() or None
            changed.extend(flip_canonical_resolve(root, prd=ns.prd, scope_note=scope_note))
            flipped_legacy = flip_resolve(backlog, prd=ns.prd, scope_note=scope_note)
            if flipped_legacy:
                legacy_changed = True
            changed.extend(flipped_legacy)
        if legacy_changed:
            gap_path.write_text(render_gap_backlog(backlog), encoding="utf-8")
        print(json.dumps({"verdict": "pass", "action": "gap-backlog-flip", "flipped": changed, "counts": backlog.counts()}))
        return
    parser.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
