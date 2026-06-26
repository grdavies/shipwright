#!/usr/bin/env python3
"""Distilled /sw-deliver wave learnings for memory-preflight (R62)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def read_run_log(root: Path, limit: int = 200) -> list[dict[str, Any]]:
    log_path = root / ".cursor" / "sw-deliver-runs" / "run.log"
    if not log_path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").strip().splitlines()[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def distill_learnings(root: Path) -> dict[str, Any]:
    from wave_state import load_deliver_state

    state = load_deliver_state(root)
    plan = read_json(root / ".cursor" / "sw-deliver-plan.json")
    target = state.get("target") or plan.get("target") or {}
    patterns: list[dict[str, str]] = []

    for notice in plan.get("notices") or []:
        text = str(notice)
        if "contention:" in text:
            patterns.append({"kind": "contention", "summary": text})

    contention = plan.get("contention") or {}
    for edge in contention.get("injectedEdges") or []:
        patterns.append(
            {
                "kind": "contention-edge",
                "summary": f"phases {edge.get('from')}→{edge.get('to')} serialized ({edge.get('kind', 'contention')})",
            }
        )

    for entry in read_run_log(root):
        event = entry.get("event")
        if event == "blast-radius":
            patterns.append(
                {
                    "kind": "blast-radius",
                    "summary": (
                        f"upstream {entry.get('sourcePhaseSlug')} blocked dependents "
                        f"{[b.get('phaseSlug') for b in entry.get('blockedDependents', [])]}"
                    ),
                }
            )
        elif event == "phase-revert":
            patterns.append(
                {
                    "kind": "revert",
                    "summary": f"phase {entry.get('phaseSlug')} reverted ({entry.get('cause', 'bad-merge')})",
                }
            )
        elif event == "forward-merge-blocked":
            patterns.append(
                {
                    "kind": "dependent-conflict",
                    "summary": str(entry.get("cause") or "forward-merge conflict"),
                }
            )

    for meta in (state.get("phases") or {}).values():
        if meta.get("status") == "blocked" and meta.get("cause"):
            cause = str(meta["cause"])
            if cause.startswith("blast-radius:"):
                continue
            patterns.append(
                {
                    "kind": "blocked-phase",
                    "summary": f"{meta.get('slug', '?')}: {cause}",
                }
            )

    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in patterns:
        key = item["summary"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return {
        "category": "learning",
        "surface": "sw-deliver",
        "targetBranch": target.get("branch"),
        "prd_number": state.get("prd_number") or plan.get("prd_number"),
        "source_task_list": state.get("source_task_list") or plan.get("source_task_list"),
        "patterns": unique,
        "memoryGuidance": (
            "Distilled wave patterns only — route through memory-preflight after "
            "scripts/memory-redact.sh; never store raw logs or transcripts (R62)"
        ),
    }


def cmd_learnings_distill(root: Path, _args: list[str]) -> None:
    payload = distill_learnings(root)
    emit({"verdict": "pass", "action": "learnings-distill", "learnings": payload})


def cmd_learnings_prepare(root: Path, args: list[str]) -> None:
    payload = distill_learnings(root)
    if not payload.get("patterns"):
        emit(
            {
                "verdict": "pass",
                "action": "learnings-prepare",
                "note": "no distilled patterns to persist",
                "patterns": [],
            }
        )
    lines = [
        f"# Deliver wave learnings ({payload.get('targetBranch', 'unknown')})",
        "",
        f"PRD: {payload.get('prd_number', 'n/a')} | task list: {payload.get('source_task_list', 'n/a')}",
        "",
    ]
    for item in payload["patterns"]:
        lines.append(f"- **{item['kind']}**: {item['summary']}")
    lines.append("")
    lines.append(payload["memoryGuidance"])
    raw = "\n".join(lines)
    proc = subprocess.run(
        [str(SCRIPT_DIR / "memory-redact.sh")],
        input=raw,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or "memory-redact failed")
    redacted = proc.stdout
    out_path = parse_kv(args, "--out")
    if out_path:
        Path(out_path).write_text(redacted, encoding="utf-8")
    emit(
        {
            "verdict": "pass",
            "action": "learnings-prepare",
            "patternCount": len(payload["patterns"]),
            "redactedMarkdown": redacted,
            "memoryWrite": "invoke memory-preflight write with category learning + tags deliver,sw-deliver",
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_memory.py <root> <command> [args...]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]
    if cmd == "learnings":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "distill":
            cmd_learnings_distill(root, rest)
        elif sub == "prepare":
            cmd_learnings_prepare(root, rest)
        else:
            fail("learnings subcommand required: distill|prepare")
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
