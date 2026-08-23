#!/usr/bin/env python3
"""Intent-aware merge conflict resolver (PRD 323 R11–R15, R21)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import merge_provenance as mp  # noqa: E402
import planning_paths  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402

INTENT_CLASSES = frozenset({"deterministic-regen", "compatible-merge", "semantic-ambiguous"})
SIDE_VALUES = frozenset({"LEFT", "RIGHT"})
CLASS_PRIORITY = {"semantic-ambiguous": 0, "deterministic-regen": 1, "compatible-merge": 2}
AMBIGUOUS_INTENT_EXIT = 20

DETERMINISTIC_REGEN_RELPATHS = (
    "core/sw-reference/deterministic-regen-paths.json",
    ".sw/deterministic-regen-paths.json",
)

DEFAULT_VERIFICATION_COMMANDS = (
    "PYTHONPATH=scripts python3 scripts/test/_runner.py verify --scope phase",
)


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def intent_merge_enabled(root: Path) -> bool:
    env = os.environ.get("SW_INTENT_MERGE_ENABLED", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    cfg = load_workflow_config(root)
    deliver = cfg.get("deliver") if isinstance(cfg.get("deliver"), dict) else {}
    block = deliver.get("intentMerge") if isinstance(deliver.get("intentMerge"), dict) else {}
    return bool(block.get("enabled", False))


def load_deterministic_regen_config(root: Path) -> dict[str, Any]:
    for rel in DETERMINISTIC_REGEN_RELPATHS:
        path = root / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            continue
    return {"allowlist": list(planning_paths.GENERATOR_OUTPUT_GLOBS)}


def path_in_allowlist(path: str, allowlist: list[str]) -> bool:
    norm = path.replace("\\", "/")
    for entry in allowlist:
        if planning_paths.path_matches_serialized_token(norm, entry):
            return True
        if norm == entry:
            return True
    return False


def _intent_descriptor(record: dict[str, Any], *, side: str) -> dict[str, Any]:
    return {
        "side": side,
        "path": str(record.get("path") or ""),
        "taskRef": str(record.get("taskRef") or ""),
        "phaseSlug": str(record.get("phaseSlug") or ""),
        "intent": str(record.get("intent") or record.get("taskRef") or mp.UNATTRIBUTED_INTENT),
    }


def detect_ambiguous_intent(
    *,
    conflict_paths: list[str],
    left_records: list[dict[str, Any]],
    right_records: list[dict[str, Any]],
    path_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    by_left = {str(item.get("path")): item for item in left_records}
    by_right = {str(item.get("path")): item for item in right_records}
    conflicting_paths: list[str] = []
    intents: list[dict[str, Any]] = []
    seen_intent_keys: set[tuple[str, str, str]] = set()

    for path in conflict_paths:
        left = by_left.get(path, {"path": path, "side": "LEFT"})
        right = by_right.get(path, {"path": path, "side": "RIGHT"})
        left_ref = str(left.get("taskRef") or "")
        right_ref = str(right.get("taskRef") or "")
        if left_ref and right_ref and left_ref != right_ref:
            conflicting_paths.append(path)
            for descriptor in (_intent_descriptor(left, side="LEFT"), _intent_descriptor(right, side="RIGHT")):
                key = (descriptor["side"], descriptor["path"], descriptor["taskRef"])
                if key in seen_intent_keys:
                    continue
                seen_intent_keys.add(key)
                intents.append(descriptor)

    if path_decisions is not None:
        chosen_sides = {
            str(decision.get("chosenSide"))
            for decision in path_decisions
            if decision.get("intentClass") == "compatible-merge" and decision.get("chosenSide")
        }
        if len(chosen_sides) > 1:
            for decision in path_decisions:
                if decision.get("intentClass") != "compatible-merge":
                    continue
                path = str(decision.get("path") or "")
                if path and path not in conflicting_paths:
                    conflicting_paths.append(path)
                left = decision.get("left") if isinstance(decision.get("left"), dict) else {}
                right = decision.get("right") if isinstance(decision.get("right"), dict) else {}
                for descriptor in (
                    _intent_descriptor(left, side="LEFT"),
                    _intent_descriptor(right, side="RIGHT"),
                ):
                    key = (descriptor["side"], descriptor["path"], descriptor["taskRef"])
                    if key in seen_intent_keys:
                        continue
                    seen_intent_keys.add(key)
                    intents.append(descriptor)

    if not conflicting_paths and not intents:
        return None
    return {
        "verdict": "halt",
        "reason": "ambiguous-intent",
        "paths": sorted(dict.fromkeys(conflicting_paths)),
        "intents": sorted(intents, key=lambda item: (item["path"], item["side"], item["taskRef"])),
    }


def halt_ambiguous_intent_payload(
    *,
    conflict_paths: list[str],
    left_records: list[dict[str, Any]],
    right_records: list[dict[str, Any]],
    path_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = detect_ambiguous_intent(
        conflict_paths=conflict_paths,
        left_records=left_records,
        right_records=right_records,
        path_decisions=path_decisions,
    )
    if payload is None:
        payload = {
            "verdict": "halt",
            "reason": "ambiguous-intent",
            "paths": sorted(conflict_paths),
            "intents": [],
        }
    payload["conflictPaths"] = sorted(conflict_paths)
    return payload


def aggregate_intent_class(classes: list[str]) -> str:
    if not classes:
        return "semantic-ambiguous"
    return min(classes, key=lambda item: CLASS_PRIORITY.get(item, 99))


def _normalize_rationale(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def _records_compatible(left: dict[str, Any], right: dict[str, Any], *, merging_phase_slug: str) -> bool:
    left_ref = str(left.get("taskRef") or "")
    right_ref = str(right.get("taskRef") or "")
    if left_ref and right_ref and left_ref != right_ref:
        return False
    if left_ref and right_ref and left_ref == right_ref:
        left_rat = _normalize_rationale(str(left.get("rationale") or left.get("expected") or ""))
        right_rat = _normalize_rationale(str(right.get("rationale") or right.get("expected") or ""))
        if left_rat and right_rat and left_rat != right_rat:
            return False
        return True
    left_phase = str(left.get("phaseSlug") or "")
    right_phase = str(right.get("phaseSlug") or "")
    left_rat = _normalize_rationale(str(left.get("rationale") or left.get("expected") or ""))
    right_rat = _normalize_rationale(str(right.get("rationale") or right.get("expected") or ""))
    if left_rat and right_rat and left_rat != right_rat:
        return False
    if left_phase and right_phase and left_phase == right_phase and left_rat and left_rat == right_rat:
        return True
    if right.get("resolved") and right_phase == merging_phase_slug and not left.get("resolved"):
        return True
    if left.get("resolved") and left_phase == merging_phase_slug and not right.get("resolved"):
        return True
    return False


def choose_side(left: dict[str, Any], right: dict[str, Any], *, merging_phase_slug: str) -> str:
    right_phase = str(right.get("phaseSlug") or "")
    left_phase = str(left.get("phaseSlug") or "")
    if right_phase == merging_phase_slug:
        return "RIGHT"
    if left_phase == merging_phase_slug:
        return "LEFT"
    return "RIGHT"


def classify_path_intent(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    path: str,
    allowlist: list[str],
    merging_phase_slug: str,
) -> tuple[str, str | None]:
    if path_in_allowlist(path, allowlist):
        return "deterministic-regen", None
    if _records_compatible(left, right, merging_phase_slug=merging_phase_slug):
        return "compatible-merge", choose_side(left, right, merging_phase_slug=merging_phase_slug)
    return "semantic-ambiguous", None


def merged_intent_summary(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    path: str,
    chosen_side: str,
    intent_class: str,
) -> str:
    chosen = left if chosen_side == "LEFT" else right
    other = right if chosen_side == "LEFT" else left
    task_ref = chosen.get("taskRef") or other.get("taskRef") or "unknown"
    phase_slug = chosen.get("phaseSlug") or other.get("phaseSlug") or "unknown"
    rationale = chosen.get("rationale") or chosen.get("expected") or other.get("rationale") or ""
    return (
        f"{intent_class} for {path}: keep {chosen_side} intent "
        f"(task {task_ref}, phase {phase_slug}; {rationale})"
    )


def verification_commands(root: Path) -> list[str]:
    cfg = load_workflow_config(root)
    verify = cfg.get("verify") if isinstance(cfg.get("verify"), dict) else {}
    test_cmd = str(verify.get("test") or DEFAULT_VERIFICATION_COMMANDS).strip()
    return [test_cmd] if test_cmd else [DEFAULT_VERIFICATION_COMMANDS]


def build_proposal(
    root: Path,
    *,
    conflict_paths: list[str],
    left_records: list[dict[str, Any]],
    right_records: list[dict[str, Any]],
    path_decisions: list[dict[str, Any]],
    intent_class: str,
    phase_slug: str,
    phase_branch: str,
    target: str,
    task_list: str,
) -> dict[str, Any]:
    chosen_side = None
    summaries: list[str] = []
    if intent_class == "compatible-merge":
        sides = {decision.get("chosenSide") for decision in path_decisions if decision.get("chosenSide")}
        chosen_side = next(iter(sides)) if len(sides) == 1 else "RIGHT"
        for decision in path_decisions:
            if decision.get("mergedIntentSummary"):
                summaries.append(str(decision["mergedIntentSummary"]))
    return {
        "verdict": "pass",
        "intentClass": intent_class,
        "generatedAt": utc_now(),
        "phaseSlug": phase_slug,
        "phaseBranch": phase_branch,
        "target": target,
        "taskList": task_list,
        "conflictPaths": conflict_paths,
        "chosenSide": chosen_side,
        "mergedIntentSummary": "; ".join(summaries) if summaries else None,
        "verificationCommands": verification_commands(root),
        "records": {"left": left_records, "right": right_records},
        "pathDecisions": path_decisions,
    }


def proposal_path(root: Path, phase_slug: str) -> Path:
    return root / ".cursor" / "sw-deliver-runs" / phase_slug / "merge-intent-proposal.json"


def write_proposal(root: Path, phase_slug: str, proposal: dict[str, Any]) -> Path:
    path = proposal_path(root, phase_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def resolve_intent_records(
    root: Path,
    *,
    conflict_paths: list[str],
    task_list: str,
    left_head: str | None,
    right_head: str | None,
    deliver_state: dict[str, Any] | None,
) -> dict[str, Any]:
    if not task_list.strip():
        return {
            "verdict": "fail",
            "error": "task list required for intent merge",
            "cause": "intent-merge:missing-task-list",
        }
    batch = mp.resolve_paths(
        root,
        conflict_paths,
        left_head=left_head,
        right_head=right_head,
        task_list=task_list,
        deliver_state=deliver_state,
    )
    left_records = list(batch.get("records", {}).get("left") or [])
    right_records = list(batch.get("records", {}).get("right") or [])
    return {
        "verdict": "pass",
        "taskList": task_list,
        "leftRecords": left_records,
        "rightRecords": right_records,
    }


def classify_conflict_from_records(
    root: Path,
    *,
    conflict_paths: list[str],
    left_records: list[dict[str, Any]],
    right_records: list[dict[str, Any]],
    merging_phase_slug: str,
) -> tuple[str, list[dict[str, Any]]]:
    allowlist = [str(x) for x in (load_deterministic_regen_config(root).get("allowlist") or [])]
    by_left = {str(item.get("path")): item for item in left_records}
    by_right = {str(item.get("path")): item for item in right_records}
    path_decisions: list[dict[str, Any]] = []
    classes: list[str] = []
    for path in conflict_paths:
        left = by_left.get(path, {"path": path, "side": "LEFT", "resolved": False})
        right = by_right.get(path, {"path": path, "side": "RIGHT", "resolved": False})
        intent_class, chosen_side = classify_path_intent(
            left,
            right,
            path=path,
            allowlist=allowlist,
            merging_phase_slug=merging_phase_slug,
        )
        classes.append(intent_class)
        decision: dict[str, Any] = {
            "path": path,
            "intentClass": intent_class,
            "left": left,
            "right": right,
        }
        if chosen_side:
            decision["chosenSide"] = chosen_side
            decision["mergedIntentSummary"] = merged_intent_summary(
                left,
                right,
                path=path,
                chosen_side=chosen_side,
                intent_class=intent_class,
            )
        path_decisions.append(decision)
    return aggregate_intent_class(classes), path_decisions


def git_run(args: list[str], *, cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=check,
    )


def apply_compatible_merge(wt: Path, proposal: dict[str, Any]) -> tuple[bool, str]:
    path_decisions = proposal.get("pathDecisions") or []
    if not path_decisions:
        return False, "missing pathDecisions"
    for decision in path_decisions:
        if decision.get("intentClass") != "compatible-merge":
            return False, f"non-compatible path: {decision.get('path')}"
        rel = str(decision.get("path") or "")
        side = str(decision.get("chosenSide") or proposal.get("chosenSide") or "RIGHT")
        if side not in SIDE_VALUES:
            return False, f"invalid chosen side: {side}"
        checkout_flag = "--theirs" if side == "RIGHT" else "--ours"
        proc = git_run(["checkout", checkout_flag, "--", rel], cwd=wt, check=False)
        if proc.returncode != 0:
            return False, proc.stderr.strip() or proc.stdout.strip() or f"checkout failed: {rel}"
        git_run(["add", rel], cwd=wt, check=False)
    return True, "compatible-merge-applied"


def build_resume_command(
    root: Path,
    state: dict[str, Any],
    *,
    proposal_file: Path,
    phase_slug: str,
    phase_branch: str,
    target: str,
    orchestrator_worktree: Path,
) -> str:
    from wave_failure import resume_deliver_command

    deliver_cmd = resume_deliver_command(root, state)
    merge_cmd = (
        f"python3 scripts/wave.py merge exec --phase-slug {phase_slug} "
        f"--phase-branch {phase_branch} --target {target} "
        f"--orchestrator-worktree {orchestrator_worktree}"
    )
    return (
        f"# Review merge intent proposal at {proposal_file}; "
        f"after resolution run: {merge_cmd}; then: {deliver_cmd}"
    )


def semantic_halt_payload(
    result: dict[str, Any],
    root: Path,
    state: dict[str, Any],
    *,
    phase_slug: str,
    phase_branch: str,
    target: str,
    orchestrator_worktree: Path,
) -> dict[str, Any]:
    proposal_file = Path(str(result.get("proposalPath") or proposal_path(root, phase_slug)))
    return {
        "intentClass": "semantic-ambiguous",
        "proposalPath": str(proposal_file),
        "proposal": result.get("proposal"),
        "conflictPaths": result.get("conflictPaths") or [],
        "resumeCommand": build_resume_command(
            root,
            state,
            proposal_file=proposal_file,
            phase_slug=phase_slug,
            phase_branch=phase_branch,
            target=target,
            orchestrator_worktree=orchestrator_worktree,
        ),
    }


def attempt_intent_resolve(
    root: Path,
    wt: Path,
    state: dict[str, Any],
    *,
    conflict_paths: list[str],
    phase_slug: str,
    phase_branch: str,
    target: str,
    left_head: str | None,
    right_head: str | None,
    task_list: str,
    regen_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not intent_merge_enabled(root):
        return {"verdict": "skip", "reason": "intent-merge-disabled"}
    record_result = resolve_intent_records(
        root,
        conflict_paths=conflict_paths,
        task_list=task_list,
        left_head=left_head,
        right_head=right_head,
        deliver_state=state,
    )
    if record_result.get("verdict") != "pass":
        return record_result
    left_records = list(record_result.get("leftRecords") or [])
    right_records = list(record_result.get("rightRecords") or [])
    ambiguous = detect_ambiguous_intent(
        conflict_paths=conflict_paths,
        left_records=left_records,
        right_records=right_records,
    )
    if ambiguous is not None:
        return halt_ambiguous_intent_payload(
            conflict_paths=conflict_paths,
            left_records=left_records,
            right_records=right_records,
        )
    intent_class, path_decisions = classify_conflict_from_records(
        root,
        conflict_paths=conflict_paths,
        left_records=left_records,
        right_records=right_records,
        merging_phase_slug=phase_slug,
    )
    ambiguous = detect_ambiguous_intent(
        conflict_paths=conflict_paths,
        left_records=left_records,
        right_records=right_records,
        path_decisions=path_decisions,
    )
    if ambiguous is not None:
        return halt_ambiguous_intent_payload(
            conflict_paths=conflict_paths,
            left_records=left_records,
            right_records=right_records,
            path_decisions=path_decisions,
        )
    proposal = build_proposal(
        root,
        conflict_paths=conflict_paths,
        left_records=left_records,
        right_records=right_records,
        path_decisions=path_decisions,
        intent_class=intent_class,
        phase_slug=phase_slug,
        phase_branch=phase_branch,
        target=target,
        task_list=task_list,
    )
    proposal_file = write_proposal(root, phase_slug, proposal)
    payload: dict[str, Any] = {
        "verdict": "pass",
        "intentClass": intent_class,
        "proposalPath": str(proposal_file),
        "proposal": proposal,
        "conflictPaths": conflict_paths,
        "regenDetail": regen_detail or {},
    }
    if intent_class == "compatible-merge":
        ok, reason = apply_compatible_merge(wt, proposal)
        payload["applied"] = ok
        payload["applyReason"] = reason
        if not ok:
            payload["verdict"] = "fail"
            payload["error"] = reason
            payload["cause"] = "intent-merge:apply-failed"
        return payload
    if intent_class == "semantic-ambiguous":
        payload["verdict"] = "halt"
        payload["cause"] = "merge-queue:semantic-ambiguous"
        payload["resumeCommand"] = build_resume_command(
            root,
            state,
            proposal_file=proposal_file,
            phase_slug=phase_slug,
            phase_branch=phase_branch,
            target=target,
            orchestrator_worktree=wt,
        )
        return payload
    payload["verdict"] = "fail"
    payload["cause"] = "merge-queue:deterministic-regen"
    payload["reason"] = (regen_detail or {}).get("reason") or "deterministic-regen-required"
    return payload


def load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return doc if isinstance(doc, dict) else {}


def ensure_no_ambiguous_intent(
    *,
    conflict_paths: list[str],
    left_records: list[dict[str, Any]],
    right_records: list[dict[str, Any]],
    path_decisions: list[dict[str, Any]] | None = None,
) -> None:
    ambiguous = detect_ambiguous_intent(
        conflict_paths=conflict_paths,
        left_records=left_records,
        right_records=right_records,
        path_decisions=path_decisions,
    )
    if ambiguous is not None:
        emit(
            halt_ambiguous_intent_payload(
                conflict_paths=conflict_paths,
                left_records=left_records,
                right_records=right_records,
                path_decisions=path_decisions,
            ),
            AMBIGUOUS_INTENT_EXIT,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Intent-aware merge resolver (PRD 323 R11–R15, R21)")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    classify_p = sub.add_parser("classify", help="Classify conflict paths")
    classify_p.add_argument("--paths", required=True, help="Comma-separated repo-relative paths")
    classify_p.add_argument("--tasks", required=True)
    classify_p.add_argument("--phase-slug", required=True)
    classify_p.add_argument("--left-head")
    classify_p.add_argument("--right-head")
    classify_p.add_argument("--deliver-state")

    proposal_p = sub.add_parser("proposal", help="Build proposal artifact")
    proposal_p.add_argument("--paths", required=True)
    proposal_p.add_argument("--tasks", required=True)
    proposal_p.add_argument("--phase-slug", required=True)
    proposal_p.add_argument("--phase-branch", required=True)
    proposal_p.add_argument("--target", required=True)
    proposal_p.add_argument("--left-head")
    proposal_p.add_argument("--right-head")
    proposal_p.add_argument("--deliver-state")
    proposal_p.add_argument("--out")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    deliver_state = load_json(getattr(args, "deliver_state", None))
    paths = [p.strip().replace("\\", "/").lstrip("/") for p in args.paths.split(",") if p.strip()]

    if args.command == "classify":
        records = resolve_intent_records(
            root,
            conflict_paths=paths,
            task_list=args.tasks,
            left_head=args.left_head,
            right_head=args.right_head,
            deliver_state=deliver_state,
        )
        if records.get("verdict") != "pass":
            emit(records, 2)
        left_records = list(records.get("leftRecords") or [])
        right_records = list(records.get("rightRecords") or [])
        ensure_no_ambiguous_intent(
            conflict_paths=paths,
            left_records=left_records,
            right_records=right_records,
        )
        intent_class, path_decisions = classify_conflict_from_records(
            root,
            conflict_paths=paths,
            left_records=left_records,
            right_records=right_records,
            merging_phase_slug=args.phase_slug,
        )
        ensure_no_ambiguous_intent(
            conflict_paths=paths,
            left_records=left_records,
            right_records=right_records,
            path_decisions=path_decisions,
        )
        emit(
            {
                "verdict": "pass",
                "intentClass": intent_class,
                "pathDecisions": path_decisions,
            }
        )

    if args.command == "proposal":
        records = resolve_intent_records(
            root,
            conflict_paths=paths,
            task_list=args.tasks,
            left_head=args.left_head,
            right_head=args.right_head,
            deliver_state=deliver_state,
        )
        if records.get("verdict") != "pass":
            emit(records, 2)
        left_records = list(records.get("leftRecords") or [])
        right_records = list(records.get("rightRecords") or [])
        ensure_no_ambiguous_intent(
            conflict_paths=paths,
            left_records=left_records,
            right_records=right_records,
        )
        intent_class, path_decisions = classify_conflict_from_records(
            root,
            conflict_paths=paths,
            left_records=left_records,
            right_records=right_records,
            merging_phase_slug=args.phase_slug,
        )
        ensure_no_ambiguous_intent(
            conflict_paths=paths,
            left_records=left_records,
            right_records=right_records,
            path_decisions=path_decisions,
        )
        proposal = build_proposal(
            root,
            conflict_paths=paths,
            left_records=left_records,
            right_records=right_records,
            path_decisions=path_decisions,
            intent_class=intent_class,
            phase_slug=args.phase_slug,
            phase_branch=args.phase_branch,
            target=args.target,
            task_list=args.tasks,
        )
        out = write_proposal(root, args.phase_slug, proposal) if not args.out else Path(args.out)
        if args.out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        emit({"verdict": "pass", "intentClass": intent_class, "proposalPath": str(out), "proposal": proposal})
    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
