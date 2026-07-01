#!/usr/bin/env python3
"""Canonical gap unit capture from feedback signals (PRD 033 R15; PRD 041 meta channel)."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig
import planning_paths as pp
import sw_state_write_lib as writer


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "feedback-gap"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def meta_inbox_path(root: Path, signal_id: str) -> Path:
    return root / ".cursor" / "sw-meta-inbox" / f"{signal_id}.json"


def load_meta_draft(root: Path, signal_id: str) -> dict[str, Any]:
    path = meta_inbox_path(root, signal_id)
    if not path.is_file():
        fail("meta inbox draft not found", signalId=signal_id, halt="meta-draft-missing")
    return writer.load_store(path)


def next_gap_number(units: list[pig.PlanningUnit]) -> int:
    max_n = 0
    for unit in units:
        m = re.match(r"gap-(\d+)-", unit.id)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def capture_gap(
    root: Path,
    *,
    signal_id: str,
    title: str,
    pr_number: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    dirs = pp.load_planning_dirs(root)
    worktree = pp.git_root(root)
    units = pig.discover_units(root)
    num = next_gap_number(units)
    unit_id = f"gap-{num:03d}-{slugify(title)}"
    unit_dir = worktree / dirs.planning / "gap" / unit_id
    body_path = unit_dir / f"{unit_id}.md"
    fm = [
        "---",
        f"id: {unit_id}",
        "type: gap",
        "status: open",
        f"title: {title}",
        "visibility: public",
        f"tags: [source:feedback, signal:{signal_id}]",
    ]
    if pr_number is not None:
        fm.append(f"source_pr: {pr_number}")
    fm.extend(["---", "", f"# {title}", "", f"_Captured from feedback signal `{signal_id}`._", ""])
    content = "\n".join(fm) + "\n"
    if not dry_run:
        unit_dir.mkdir(parents=True, exist_ok=True)
        body_path.write_text(content, encoding="utf-8")
    return {"unitId": unit_id, "path": str(body_path.relative_to(worktree)), "signalId": signal_id}


def capture_meta_draft(
    root: Path,
    *,
    signal_id: str,
    title: str,
    summary: str = "",
) -> dict[str, Any]:
    draft = {
        "signalId": signal_id,
        "destination": "meta-shipwright",
        "gapClass": "plugin-self",
        "title": title,
        "status": "draft",
        "capturedAt": utc_now(),
    }
    if summary:
        draft["summary"] = summary
    writer.cmd_write(
        root,
        store="meta-inbox-draft",
        data=draft,
        rel=f"{signal_id}.json",
    )
    return {
        "signalId": signal_id,
        "destination": "meta-shipwright",
        "path": str(meta_inbox_path(root, signal_id).relative_to(root)),
    }


def confirm_meta_draft(root: Path, *, signal_id: str) -> dict[str, Any]:
    draft = load_meta_draft(root, signal_id)
    if draft.get("status") == "materialized":
        fail("draft already materialized", signalId=signal_id)
    draft["status"] = "confirmed"
    draft["confirmedAt"] = utc_now()
    writer.cmd_write(
        root,
        store="meta-inbox-draft",
        data=draft,
        rel=f"{signal_id}.json",
    )
    return {"signalId": signal_id, "status": "confirmed"}


def materialize_meta_gap(
    root: Path,
    *,
    signal_id: str,
    title: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    draft = load_meta_draft(root, signal_id)
    if draft.get("status") != "confirmed":
        fail("materialize requires confirmed draft", signalId=signal_id, status=draft.get("status"))
    dirs = pp.load_planning_dirs(root)
    worktree = pp.git_root(root)
    gap_root = Path(pp.plugin_self_gap_dir(dirs))
    units = pig.discover_units(root)
    num = next_gap_number(units)
    unit_id = f"gap-{num:03d}-{slugify(title)}"
    unit_dir = worktree / gap_root / unit_id
    body_path = unit_dir / f"{unit_id}.md"
    fm = [
        "---",
        f"id: {unit_id}",
        "type: gap",
        "status: open",
        f"title: {title}",
        "visibility: public",
        "tags: [plugin-self, meta-shipwright, source:feedback, signal:" + signal_id + "]",
        "---",
        "",
        f"# {title}",
        "",
        f"_Materialized from meta-shipwright signal `{signal_id}`._",
        "",
    ]
    if draft.get("summary"):
        fm.extend(["## Summary", "", str(draft["summary"]), ""])
    content = "\n".join(fm) + "\n"
    if not dry_run:
        unit_dir.mkdir(parents=True, exist_ok=True)
        body_path.write_text(content, encoding="utf-8")
        draft["status"] = "materialized"
        draft["materializedUnitId"] = unit_id
        writer.cmd_write(
            root,
            store="meta-inbox-draft",
            data=draft,
            rel=f"{signal_id}.json",
        )
    return {
        "unitId": unit_id,
        "path": str(body_path.relative_to(worktree)),
        "signalId": signal_id,
        "gapClass": "plugin-self",
    }


def parse_flags(rest: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"dry_run": False}
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--dry-run":
            out["dry_run"] = True
            i += 1
        elif tok == "--signal-id" and i + 1 < len(rest):
            out["signal_id"] = rest[i + 1]
            i += 2
        elif tok == "--title" and i + 1 < len(rest):
            out["title"] = rest[i + 1]
            i += 2
        elif tok == "--summary" and i + 1 < len(rest):
            out["summary"] = rest[i + 1]
            i += 2
        elif tok == "--destination" and i + 1 < len(rest):
            out["destination"] = rest[i + 1]
            i += 2
        elif tok == "--pr" and i + 1 < len(rest):
            out["pr_number"] = int(rest[i + 1])
            i += 2
        else:
            i += 1
    return out


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail(
            "usage: planning_gap_capture.py <repo-root> "
            "<capture|confirm|materialize> [options]"
        )
    root = Path(args[0]).resolve()
    command = args[1]
    flags = parse_flags(args[2:])

    if command == "capture":
        signal_id = flags.get("signal_id")
        title = flags.get("title")
        if not signal_id or not title:
            fail("--signal-id and --title required for capture")
        if flags.get("destination") == "meta-shipwright":
            out = capture_meta_draft(
                root,
                signal_id=signal_id,
                title=title,
                summary=str(flags.get("summary") or ""),
            )
            emit({"verdict": "pass", "action": "meta-capture", **out})
            return
        out = capture_gap(
            root,
            signal_id=signal_id,
            title=title,
            pr_number=flags.get("pr_number"),
            dry_run=bool(flags.get("dry_run")),
        )
        emit({"verdict": "pass", "action": "gap-capture", **out})

    if command == "confirm":
        signal_id = flags.get("signal_id")
        if not signal_id:
            fail("--signal-id required for confirm")
        out = confirm_meta_draft(root, signal_id=signal_id)
        emit({"verdict": "pass", "action": "meta-confirm", **out})

    if command == "materialize":
        signal_id = flags.get("signal_id")
        title = flags.get("title")
        if not signal_id or not title:
            fail("--signal-id and --title required for materialize")
        out = materialize_meta_gap(
            root,
            signal_id=signal_id,
            title=title,
            dry_run=bool(flags.get("dry_run")),
        )
        emit({"verdict": "pass", "action": "meta-materialize", **out})

    fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
