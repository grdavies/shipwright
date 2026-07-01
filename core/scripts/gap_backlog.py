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

GAP_ID = re.compile(r"^GAP-(\d+)$", re.I)
INDEX_COUNTS = re.compile(r"^\|\s*(resolved|scheduled|open)\s*\|\s*(\d+)\s*\|", re.I)


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


def default_gap_path(root: Path) -> Path:
    return root / "docs" / "prds" / "GAP-BACKLOG.md"


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


def flip_schedule(backlog: GapBacklog, *, gap_ids: list[str], prd: str, amendment: str | None = None) -> list[str]:
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
        elif row.is_scheduled and row.schedule == label:
            flipped.append(row.gap_id)
    return flipped


def resolve_for_prd(root: Path, prd: str, *, scope_note: str | None = None) -> dict[str, Any]:
    """Shared in-process gap-resolve for an absorbing PRD (PRD 048 R1)."""
    gap_path = default_gap_path(root)
    try:
        if not gap_path.is_file():
            return {"verdict": "pass", "flipped": [], "error": None}
        backlog = parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
        flipped = flip_resolve(backlog, prd=prd, scope_note=scope_note)
        if flipped:
            gap_path.write_text(render_gap_backlog(backlog), encoding="utf-8")
        return {"verdict": "pass", "flipped": flipped, "error": None}
    except Exception as exc:
        return {"verdict": "partial", "flipped": [], "error": str(exc)}


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


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    parser = argparse.ArgumentParser(prog="gap_backlog.py")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    p_flip = sub.add_parser("flip")
    p_flip.add_argument("--schedule", action="store_true")
    p_flip.add_argument("--resolve", action="store_true")
    p_flip.add_argument("--from-artifact", default="")
    p_flip.add_argument("--gaps", nargs="*", default=[])
    p_flip.add_argument("--prd", default="")
    p_flip.add_argument("--amendment", default="")
    p_flip.add_argument("--scope-note", default="")
    p_flip.add_argument("--gap-path", default="")
    ns = parser.parse_args(args)
    root = Path(ns.root).resolve()
    gap_path = Path(getattr(ns, "gap_path", "") or getattr(ns, "gap_path_global", "")) if (getattr(ns, "gap_path", "") or getattr(ns, "gap_path_global", "")) else default_gap_path(root)
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
        changed: list[str] = []
        if ns.schedule:
            gap_ids = list(ns.gaps)
            prd = ns.prd
            amendment = ns.amendment or None
            if ns.from_artifact:
                art = Path(ns.from_artifact)
                directives = doc_format.parse_frontmatter_directives(art.read_text(encoding="utf-8"))
                gap_ids = directives.get("absorbs") or []
                if not gap_ids:
                    print(json.dumps({"verdict": "pass", "action": "gap-backlog-flip-schedule", "flipped": []}))
                    return
                prd_p, am_p = prd_from_path(art)
                prd = prd or prd_p
                amendment = amendment or (am_p or "")
            changed = flip_schedule(backlog, gap_ids=gap_ids, prd=prd, amendment=amendment or None)
        elif ns.resolve:
            scope_note = ns.scope_note.strip() or None
            changed = flip_resolve(backlog, prd=ns.prd, scope_note=scope_note)
        if changed:
            gap_path.write_text(render_gap_backlog(backlog), encoding="utf-8")
        print(json.dumps({"verdict": "pass", "action": "gap-backlog-flip", "flipped": changed, "counts": backlog.counts()}))
        return
    parser.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
