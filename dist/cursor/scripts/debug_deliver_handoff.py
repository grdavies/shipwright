#!/usr/bin/env python3
"""Thin tasks-debug-<slug> materializer for /sw-debug → /sw-deliver handoff (PRD 067 R10–R13)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _sw.cli import run_module_main

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(raw: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (raw or "").strip().lower()).strip("-")
    return s or "debug-fix"


def unit_id_for(slug: str) -> str:
    return f"tasks-debug-{slug}"


def virtual_body_path(slug: str) -> str:
    return f"docs/prds/debug-{slug}/tasks-debug-{slug}.md"


def build_one_phase_task_body(
    *,
    slug: str,
    title: str,
    files: list[str],
    acceptance: list[str],
    regression_focus: str,
    rca_summary: str,
) -> str:
    """Frozen one-phase task list from redacted RCA brief (no full /sw-doc)."""
    file_lines = "\n".join(f"  - `{f}`" for f in files) or "  - `(unspecified)`"
    accept_lines = "\n".join(f"  - {a}" for a in acceptance) or "  - Fix verified against failing regression"
    return f"""---
frozen: true
artifactType: tasks
unitId: {unit_id_for(slug)}
source: debug-deliver-handoff
createdAt: {utc_now()}
---

# tasks-debug-{slug}

Thin one-phase pack from `/sw-debug` (PRD 067 R10). Not a full `/sw-doc` ceremony.

## Phase Dependencies

| Phase | Depends On |
| --- | --- |
| 1 | — |

### 1. `debug-fix` — {title}

- [ ] 1.1 Apply scoped fix from redacted RCA
  - **File:** {files[0] if files else '(unspecified)'}
  - **Expected:** {acceptance[0] if acceptance else 'Regression green'}
  - **Files:**
{file_lines}
  - **Acceptance:**
{accept_lines}
  - **Regression focus:** {regression_focus or 'repro from RCA brief'}
  - **RCA summary:** {rca_summary.strip() or '(redacted brief omitted)'}
"""


def materialize_debug_pack(
    root: Path,
    *,
    slug: str,
    title: str,
    files: list[str],
    acceptance: list[str],
    regression_focus: str = "",
    rca_summary: str = "",
    confirmed: bool = False,
) -> dict[str, Any]:
    """Write virtual body under .cursor/planning-materialized and return handoff payload."""
    slug = slugify(slug)
    unit_id = unit_id_for(slug)
    rel = virtual_body_path(slug)
    body = build_one_phase_task_body(
        slug=slug,
        title=title or f"Debug fix {slug}",
        files=files,
        acceptance=acceptance,
        regression_focus=regression_focus,
        rca_summary=rca_summary,
    )
    dest = root / ".cursor" / "planning-materialized" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")

    deliver_ref = f"--unit-id {unit_id}"
    resume = f"/sw-deliver run {deliver_ref}"
    out: dict[str, Any] = {
        "verdict": "ok",
        "action": "debug-deliver-materialize",
        "unitId": unit_id,
        "slug": slug,
        "bodyPath": rel,
        "materializedPath": str(dest.relative_to(root)),
        "frozen": True,
        "phaseCount": 1,
        "deliverEntryRef": deliver_ref,
        "resumeCommand": resume,
        "handoff": {
            "printCommand": resume,
            "sameTurnOnConfirm": True,
            "declineEndsDebug": True,
            "taskSpawnDeliverForbidden": True,
            "confirmed": confirmed,
        },
        "haltOwnership": "deliver",
        "note": "Post-handoff halts owned by /sw-deliver (R13); debug must not nest deliver Tasks (R11).",
    }
    if not confirmed:
        out["awaitConfirm"] = True
        out["prompt"] = (
            f"Materialized thin debug pack `{unit_id}`. "
            f"Confirm to run `{resume}` same-turn, or decline to end `/sw-debug`."
        )
    return out


def assert_pre_confirm_forbidden(step: str) -> dict[str, Any]:
    """R12: execute/ship forbidden before route confirm."""
    forbidden = {
        "sw-execute",
        "sw-ship",
        "sw-commit",
        "sw-pr",
        "merge-enqueue",
        "merge-run-next",
        "terminal-ship",
    }
    key = (step or "").strip()
    if key in forbidden:
        return {
            "verdict": "fail",
            "halt": "debug-pack:pre-confirm-forbidden",
            "step": key,
            "error": f"{key} forbidden before debug route confirm (R12)",
        }
    return {"verdict": "pass", "action": "pre-confirm-guard", "step": key}


def cmd_materialize(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    files = [f.strip() for f in (args.files or "").split(",") if f.strip()]
    acceptance = [a.strip() for a in (args.acceptance or "").split(";") if a.strip()]
    payload = materialize_debug_pack(
        root,
        slug=args.slug,
        title=args.title or "",
        files=files,
        acceptance=acceptance,
        regression_focus=args.regression or "",
        rca_summary=args.rca_summary or "",
        confirmed=bool(args.confirmed),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("verdict") == "ok" else 20


def cmd_pre_confirm_guard(args: argparse.Namespace) -> int:
    payload = assert_pre_confirm_forbidden(args.step)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("verdict") == "pass" else 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Debug → deliver thin pack handoff (PRD 067)")
    parser.add_argument("root", nargs="?", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)

    mat = sub.add_parser("materialize", help="Write tasks-debug-<slug> one-phase pack")
    mat.add_argument("--slug", required=True)
    mat.add_argument("--title", default="")
    mat.add_argument("--files", default="", help="Comma-separated file paths")
    mat.add_argument("--acceptance", default="", help="Semicolon-separated acceptance bullets")
    mat.add_argument("--regression", default="")
    mat.add_argument("--rca-summary", default="")
    mat.add_argument("--confirmed", action="store_true")
    mat.set_defaults(func=cmd_materialize)

    guard = sub.add_parser("pre-confirm-guard", help="Fail closed on execute/ship before confirm")
    guard.add_argument("--step", required=True)
    guard.set_defaults(func=cmd_pre_confirm_guard)

    ns = parser.parse_args(list(argv) if argv is not None else None)
    return int(ns.func(ns))


if __name__ == "__main__":
    run_module_main(main)
