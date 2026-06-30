#!/usr/bin/env python3
"""SoT-aware decision memory audit helpers (PRD 015 R9, R11)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_DECISION_PATH_RE = re.compile(r"docs/decisions/\d{3}-[a-z0-9-]+\.md")
_POINTER_HINT_RE = re.compile(r"^(pointer|see|refers to)\b", re.I)


def emit(obj: dict, exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2) -> None:
    emit({"verdict": "fail", "error": error}, exit_code)


def git_root(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("not a git repository")
    return Path(proc.stdout.strip())


def resolve_sot(root: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(root / "scripts/memory-sot.py"), "resolve", "--class", "decision", "--json"],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("memory-sot resolve failed", stderr=proc.stderr.strip())
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail("memory-sot returned invalid JSON")
    if data.get("verdict") != "pass":
        fail("memory-sot resolve did not pass", detail=data)
    return data


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip()
    return meta


def list_git_decision_records(root: Path) -> list[str]:
    decisions = root / "docs" / "decisions"
    if not decisions.is_dir():
        return []
    return sorted(
        p.relative_to(root).as_posix()
        for p in decisions.glob("*.md")
        if p.name not in ("INDEX.md",) and not p.name.startswith(".")
    )


def scan_in_repo_decision_memories(root: Path) -> list[dict]:
    store = root / ".cursor" / "sw-memory" / "memories"
    hits: list[dict] = []
    if not store.is_dir():
        return hits
    for mem in sorted(store.glob("*.md")):
        text = mem.read_text(encoding="utf-8", errors="replace")
        meta = parse_frontmatter(text)
        category = meta.get("category", "").lower()
        if category and category != "decision":
            continue
        body = text.split("---\n", 2)[-1] if text.startswith("---") else text
        related = [m.group(0) for m in _DECISION_PATH_RE.finditer(text)]
        word_count = len(body.split())
        pointerish = word_count <= 80 or bool(_POINTER_HINT_RE.search(body.strip()[:120]))
        hits.append(
            {
                "path": mem.relative_to(root).as_posix(),
                "category": category or "unknown",
                "relatedFiles": related,
                "wordCount": word_count,
                "likelyPointer": pointerish and bool(related),
            }
        )
    return hits


def cmd_audit_conflicts(root: Path) -> None:
    sot = resolve_sot(root)
    effective = str(sot.get("effective", "repo"))
    knob = str(sot.get("sourceOfTruth", "auto"))
    provider = sot.get("provider")
    records = list_git_decision_records(root)
    memories = scan_in_repo_decision_memories(root)

    conflicts: list[dict] = []
    for mem in memories:
        if effective == "repo":
            if mem["wordCount"] > 120 and not mem["likelyPointer"]:
                conflicts.append(
                    {
                        "kind": "content-bearing-under-repo-sot",
                        "memory": mem["path"],
                        "problem": "decision memory appears content-bearing while git record is authoritative",
                        "proposedAction": "collapse-to-pointer",
                        "relatedFiles": mem["relatedFiles"] or records[:1],
                    }
                )
            elif not mem["relatedFiles"] and records:
                conflicts.append(
                    {
                        "kind": "missing-pointer-link",
                        "memory": mem["path"],
                        "problem": "decision memory lacks relatedFiles pointer to git record",
                        "proposedAction": "add-relatedFiles",
                    }
                )
        else:
            if mem["likelyPointer"] and mem["relatedFiles"]:
                conflicts.append(
                    {
                        "kind": "pointer-under-memory-sot",
                        "memory": mem["path"],
                        "problem": "decision memory is pointer-shaped while provider should be authoritative",
                        "proposedAction": "promote-to-content-bearing",
                    }
                )

    emit(
        {
            "verdict": "pass",
            "action": "audit-conflicts",
            "effective": effective,
            "sourceOfTruth": knob,
            "provider": provider,
            "gitDecisionRecords": len(records),
            "decisionMemories": len(memories),
            "conflicts": conflicts,
            "noChange": effective == "repo" and knob == "auto" and provider in (None, "in-repo") and not conflicts,
        }
    )


def cmd_legacy_reconcile_plan(root: Path, target_knob: str | None) -> None:
    sot = resolve_sot(root)
    effective = str(sot.get("effective", "repo"))
    knob = target_knob or str(sot.get("sourceOfTruth", "auto"))
    if knob not in ("repo", "memory", "auto"):
        fail("target must be repo, memory, or auto")

    audit_proc = subprocess.run(
        [sys.executable, str(root / "scripts/memory_sot_audit.py"), "audit-conflicts", "--root", str(root)],
        text=True,
        capture_output=True,
    )
    audit = json.loads(audit_proc.stdout) if audit_proc.returncode == 0 else {"conflicts": []}

    steps: list[dict] = []
    if knob == "auto" and effective == "repo":
        steps.append({"step": "noop", "note": "default auto+in-repo — no migration required"})
    else:
        for conflict in audit.get("conflicts", []):
            steps.append(
                {
                    "step": "reconcile",
                    "memory": conflict.get("memory"),
                    "action": conflict.get("proposedAction"),
                    "kind": conflict.get("kind"),
                }
            )
        if not steps:
            steps.append({"step": "verify", "note": "run audit-conflicts after mode switch"})

    emit(
        {
            "verdict": "pass",
            "action": "legacy-reconcile-plan",
            "currentEffective": effective,
            "targetSourceOfTruth": knob,
            "oneTime": True,
            "steps": steps,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="SoT-aware memory audit helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit-conflicts", help="Flag decision memory vs git SoT conflicts")
    audit.add_argument("--root", type=Path, default=None)

    legacy = sub.add_parser("legacy-reconcile-plan", help="One-time migration plan on mode switch")
    legacy.add_argument("--target", choices=("repo", "memory", "auto"), default=None)
    legacy.add_argument("--root", type=Path, default=None)

    args = parser.parse_args()
    root = git_root(args.root or Path.cwd())

    if args.command == "audit-conflicts":
        cmd_audit_conflicts(root)
    elif args.command == "legacy-reconcile-plan":
        cmd_legacy_reconcile_plan(root, args.target)


if __name__ == "__main__":
    main()
