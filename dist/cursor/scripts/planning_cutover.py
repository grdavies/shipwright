#!/usr/bin/env python3
"""Single-authority cutover gate for planning discovery (PRD 046 R87)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths as pp  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from planning_store import resolve_effective_backend  # noqa: E402

CUTOVER_STATE_REL = ".cursor/hooks/state/planning-cutover-gate.json"
RegionAuthority = Literal["file", "issue", "deliver"]
DiscoverSource = Literal["file", "issue"]

DEFAULT_GATE: dict[str, str] = {
    "discoverSource": "file",
    "structural": "file",
    "derived": "file",
    "inFlight": "deliver",
    "legacyIndexDisposition": "reconciler-regenerated",
}


def gate_path(root: Path) -> Path:
    return pp.git_root(root) / CUTOVER_STATE_REL


def load_cutover_gate(root: Path) -> dict[str, str]:
    path = gate_path(root)
    gate = dict(DEFAULT_GATE)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, str) and value.strip():
                        gate[key] = value.strip()
        except json.JSONDecodeError:
            pass
    return gate


def save_cutover_gate(root: Path, gate: dict[str, str]) -> None:
    path = gate_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULT_GATE)
    merged.update(gate)
    path.write_text(json.dumps({"version": 1, **merged}, indent=2) + "\n", encoding="utf-8")


def region_authority(root: Path, region: str) -> RegionAuthority:
    gate = load_cutover_gate(root)
    value = gate.get(region, DEFAULT_GATE.get(region, "file"))
    if value in {"file", "issue", "deliver"}:
        return value  # type: ignore[return-value]
    return "file"


def doctor_dual_source(root: Path) -> list[dict[str, Any]]:
    """Detect simultaneous file+issue authority for the same region (R87)."""
    worktree = pp.git_root(root)
    cfg = load_workflow_config(worktree)
    effective = resolve_effective_backend(worktree, cfg)
    if effective.get("effective") != "issue-store":
        return []
    gate = load_cutover_gate(worktree)
    issues: list[dict[str, Any]] = []
    for region in ("structural", "derived", "inFlight"):
        authority = gate.get(region, DEFAULT_GATE[region])
        if authority == "issue":
            index_path = worktree / "docs" / "planning" / "INDEX.md"
            if index_path.is_file():
                text = index_path.read_text(encoding="utf-8")
                if "file-derived" in text and "issue-derived" in text:
                    issues.append(
                        {
                            "region": region,
                            "error": "dual-source-index-marker",
                            "remediation": "quiesce one source before cutover",
                        }
                    )
    discover = gate.get("discoverSource", "file")
    pinned_path = worktree / ".cursor/hooks/state/planning-discover-pinned.json"
    if pinned_path.is_file() and discover == "file":
        try:
            pinned = json.loads(pinned_path.read_text(encoding="utf-8"))
            if pinned.get("source") == "issue" and discover == "file":
                issues.append(
                    {
                        "error": "dual-discover-authority",
                        "pinned": pinned.get("source"),
                        "gate": discover,
                        "remediation": "align cutover gate with pinned discover source",
                    }
                )
        except json.JSONDecodeError:
            pass
    return issues


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def cmd_doctor(root: Path, _args: list[str]) -> None:
    issues = doctor_dual_source(root)
    if issues:
        fail("dual-source detected", issues=issues, exit_code=20)
    emit({"verdict": "pass", "action": "cutover-doctor"})


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail("usage: planning_cutover.py <repo-root> <command>")
    root = Path(args[0]).resolve()
    if args[1] == "doctor":
        cmd_doctor(root, args[2:])
    elif args[1] == "show":
        emit({"verdict": "pass", "gate": load_cutover_gate(root)})
    else:
        fail(f"unknown command: {args[1]}")


if __name__ == "__main__":
    main()
