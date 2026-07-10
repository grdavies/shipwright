#!/usr/bin/env python3
"""Single-authority cutover gate for planning discovery (PRD 046 R87, PRD 057 R5).

The gate's *default* signal is derived from committed state — the effective planning-store
backend (`workflow.config.json`, resolved via `resolve_effective_backend`) plus a structural
marker (whether the local file-store planning tree still holds tracked unit bodies) — so a
fresh CI checkout (which never has the gitignored state file below) computes the correct
authority without it. ``.cursor/hooks/state/planning-cutover-gate.json`` remains a supported
**local, gitignored override** for manual/operator testing (`cutover set`), but it is no longer
a CI authority: its absence must never produce a wrong default (PRD 057 D2).
"""

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


def _has_tracked_structural_units(root: Path) -> bool:
    """Structural marker: does the local file-store planning tree still hold unit bodies?

    Used to avoid flipping structural authority to ``issue`` purely off configured backend
    while a migration is mid-flight and local bodies are still tracked (PRD 057 R5).
    """
    worktree = pp.git_root(root)
    dirs = pp.load_planning_dirs(worktree)
    planning_root = worktree / dirs.planning
    if not planning_root.is_dir():
        return False
    for type_dir in planning_root.iterdir():
        if not type_dir.is_dir() or type_dir.name.startswith("."):
            continue
        for unit_dir in type_dir.iterdir():
            if unit_dir.is_dir() and any(unit_dir.iterdir()):
                return True
    return False


def derive_committed_gate(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, str]:
    """Derive the cutover-gate default from committed config + structural markers (R5).

    No new tracked file is introduced: the effective backend comes from the committed
    ``workflow.config.json`` and the structural signal comes from whether the file-store
    planning tree still holds tracked unit bodies on disk. This is the CI-authoritative
    default; ``load_cutover_gate`` may still layer a local override on top of it.
    """
    worktree = pp.git_root(root)
    workflow_cfg = cfg if cfg is not None else load_workflow_config(worktree)
    effective = resolve_effective_backend(worktree, workflow_cfg)
    gate = dict(DEFAULT_GATE)
    if effective.get("effective") == "issue-store" and not _has_tracked_structural_units(worktree):
        gate["discoverSource"] = "issue"
        gate["structural"] = "issue"
    return gate


def load_cutover_gate(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, str]:
    worktree = pp.git_root(root)
    gate = derive_committed_gate(worktree, cfg)
    path = gate_path(worktree)
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


def cmd_projection_gate(root: Path, _args: list[str]) -> None:
    cfg = load_workflow_config(pp.git_root(root))
    from planning_github_projects_v2 import projection_cutover_ready

    emit(projection_cutover_ready(root, cfg))


def cmd_doctor(root: Path, _args: list[str]) -> None:
    issues = doctor_dual_source(root)
    if issues:
        fail("dual-source detected", issues=issues, exit_code=20)
    emit({"verdict": "pass", "action": "cutover-doctor"})



def _parse_gate_overrides(args: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--discover-source" and i + 1 < len(args):
            overrides["discoverSource"] = args[i + 1]
            i += 2
            continue
        if token == "--structural" and i + 1 < len(args):
            overrides["structural"] = args[i + 1]
            i += 2
            continue
        if token == "--derived" and i + 1 < len(args):
            overrides["derived"] = args[i + 1]
            i += 2
            continue
        if token == "--in-flight" and i + 1 < len(args):
            overrides["inFlight"] = args[i + 1]
            i += 2
            continue
        if token == "--flip-to-issue":
            overrides.update({
                "discoverSource": "issue",
                "structural": "issue",
                "derived": "file",
                "inFlight": "deliver",
            })
            i += 1
            continue
        fail(f"unknown set flag: {token}")
    return overrides


def cmd_set(root: Path, args: list[str]) -> None:
    overrides = _parse_gate_overrides(args)
    if not overrides:
        fail("usage: planning_cutover.py <root> set [--flip-to-issue | --discover-source issue ...]")
    gate = load_cutover_gate(root)
    gate.update(overrides)
    save_cutover_gate(root, gate)
    emit({"verdict": "pass", "action": "cutover-set", "gate": gate})


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail("usage: planning_cutover.py <repo-root> <command>")
    root = Path(args[0]).resolve()
    if args[1] == "doctor":
        cmd_doctor(root, args[2:])
    elif args[1] == "show":
        emit({"verdict": "pass", "gate": load_cutover_gate(root)})
    elif args[1] == "set":
        cmd_set(root, args[2:])
    else:
        fail(f"unknown command: {args[1]}")


if __name__ == "__main__":
    main()
