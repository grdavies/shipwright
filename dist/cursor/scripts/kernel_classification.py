#!/usr/bin/env python3
"""Load kernel classification + derive canonical SHIP_CHAIN (PRD 022 TR1)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

CLASSIFICATION_REL = Path("core/sw-reference/kernel-classification.json")
CHAIN_KEY = "sw-ship"
MERGE_PUSH_STEPS = frozenset({"sw-pr", "sw-commit"})
CHOKEPOINT_TRACE_ANCHORS = frozenset({"sw-pr", "sw-stabilize", "sw-ready", "verification-gate"})

STEP_ALIASES: dict[str, str] = {
    "sw-tmp init": "sw-tmp-init",
    "sw-tmp clean": "sw-tmp-clean",
}

CHAIN_MARKER_START = "<!-- canonical-chain:begin -->"
CHAIN_MARKER_END = "<!-- canonical-chain:end -->"


def classification_path(root: Path) -> Path:
    return root / CLASSIFICATION_REL


@lru_cache(maxsize=8)
def _load_raw(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"kernel classification must be an object: {path}")
    return data


def load_classification(root: Path) -> dict[str, Any]:
    path = classification_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"missing kernel classification: {path}")
    return _load_raw(str(path.resolve()))


def normalize_step(step: str) -> str:
    s = step.strip()
    if s in STEP_ALIASES:
        return STEP_ALIASES[s]
    return s.replace(" ", "-")


def canonical_ship_chain(root: Path | None = None, classification: dict[str, Any] | None = None) -> list[str]:
    data = classification if classification is not None else load_classification(root or Path.cwd())
    chains = data.get("canonicalPhaseChains") or {}
    chain = chains.get(CHAIN_KEY)
    if not isinstance(chain, list) or not chain:
        raise ValueError(f"canonicalPhaseChains.{CHAIN_KEY} missing or empty")
    return [normalize_step(str(s)) for s in chain]


def kernel_step_ids(classification: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in classification.get("kernelChokepoints") or []:
        if not isinstance(item, dict):
            continue
        step_id = item.get("stepId")
        if isinstance(step_id, str) and step_id.strip():
            ids.add(normalize_step(step_id))
    return ids


def plan_policy_step_ids(classification: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in classification.get("planPolicySteps") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.add(normalize_step(item["id"]))
    return ids


def classified_step_ids(classification: dict[str, Any]) -> set[str]:
    return kernel_step_ids(classification) | plan_policy_step_ids(classification)


def validate_chain_order(chain: list[str], classification: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    positions = {step: idx for idx, step in enumerate(chain)}
    for raw in classification.get("orderingInvariants") or []:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("kind") or "step") == "chokepoint":
            continue
        before = raw.get("before")
        after = raw.get("after")
        if not isinstance(before, str) or not isinstance(after, str):
            continue
        b = normalize_step(before)
        a = normalize_step(after)
        if b not in positions or a not in positions:
            continue
        if positions[b] >= positions[a]:
            reasons.append(f"ordering invariant violated: {b} must precede {a}")
    return (len(reasons) == 0, reasons)


def driver_transition_log(chain: list[str]) -> list[str]:
    log: list[str] = ["scoped-run-identity", "durable-state-transitions"]
    for step in chain:
        log.append(step)
        if step == "verification-gate":
            log.append("verification-gate-eval")
        if step in CHOKEPOINT_TRACE_ANCHORS:
            if step == "sw-pr":
                log.append("git-push-secret-scan")
            if step in {"sw-stabilize", "sw-ready"}:
                log.append("check-gate")
    return log


def chokepoints_reachable_before_merge_push(
    classification: dict[str, Any], chain: list[str] | None = None
) -> tuple[bool, list[str]]:
    chain = chain or canonical_ship_chain(classification=classification)
    trace = driver_transition_log(chain) + ["merge-push"]
    required_tokens = (
        "scoped-run-identity",
        "durable-state-transitions",
        "verification-gate",
        "check-gate",
        "git-push-secret-scan",
    )
    merge_idx = trace.index("merge-push")
    prefix = trace[:merge_idx]
    missing = [tok for tok in required_tokens if tok not in prefix]
    return (len(missing) == 0, missing)


def orchestrator_referenced_steps(root: Path, classification: dict[str, Any]) -> set[str]:
    """Steps explicitly declared in orchestratorStepRegistry only (no prose token scan)."""
    _ = root
    refs: set[str] = set()
    registry = classification.get("orchestratorStepRegistry") or {}
    phase_chains = classification.get("canonicalPhaseChains") or {}
    orch_chains = classification.get("canonicalOrchestratorChains") or {}
    for entry in registry.values():
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("chainKey"), str):
            key = entry["chainKey"]
            chain_source = orch_chains if key in orch_chains else phase_chains
            for step in chain_source.get(key) or []:
                refs.add(normalize_step(str(step)))
        for step in entry.get("chain") or []:
            refs.add(normalize_step(str(step)))
        if entry.get("delegatesTo"):
            key = str(entry["delegatesTo"])
            chain_source = orch_chains if key in orch_chains else phase_chains
            for step in chain_source.get(key) or []:
                refs.add(normalize_step(str(step)))
    return refs


def lint_completeness(root: Path, classification: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    data = classification if classification is not None else load_classification(root)
    classified = classified_step_ids(data)
    skip = {"sw-deliver", "sw-doc", "sw-debug", "sw-feedback", "sw-ship", "sw-triage", "sw-worktree", "sw-start"}
    missing = sorted(
        step for step in orchestrator_referenced_steps(root, data) if step not in classified and step not in skip
    )
    return (len(missing) == 0, missing)


def render_chain_prose(chain: list[str]) -> str:
    rendered: list[str] = []
    for step in chain:
        if step == "sw-tmp-init":
            rendered.append("sw-tmp init")
        elif step == "sw-tmp-clean":
            rendered.append("sw-tmp clean")
        else:
            rendered.append(step)
    body = " → ".join(rendered)
    return f"{CHAIN_MARKER_START}\n{body}\n{CHAIN_MARKER_END}"


def sync_sw_ship_chain_markers(root: Path) -> bool:
    cmd_path = root / "core/commands/sw-ship.md"
    if not cmd_path.is_file():
        return False
    chain = canonical_ship_chain(root)
    block = render_chain_prose(chain)
    text = cmd_path.read_text(encoding="utf-8")
    if CHAIN_MARKER_START in text and CHAIN_MARKER_END in text:
        pattern = re.compile(
            re.escape(CHAIN_MARKER_START) + r".*?" + re.escape(CHAIN_MARKER_END),
            re.DOTALL,
        )
        updated = pattern.sub(block, text, count=1)
    else:
        legacy = (
            "sw-tmp init → sw-execute → sw-verify → verification-gate → sw-review → "
            "sw-simplify → gap-check → sw-commit → sw-pr → sw-watch-ci → sw-stabilize → "
            "sw-ready [PAUSE] → sw-tmp clean"
        )
        if legacy not in text:
            return False
        inner = block.replace(CHAIN_MARKER_START, "").replace(CHAIN_MARKER_END, "").strip()
        updated = text.replace(legacy, f"{inner} [PAUSE]", 1)
    if updated != text:
        cmd_path.write_text(updated, encoding="utf-8")
        return True
    return False


def check_ship_chain_parity(root: Path, ship_chain: list[str]) -> tuple[bool, str]:
    try:
        chain = canonical_ship_chain(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, str(exc)
    if chain != ship_chain:
        return False, "ship_phase_steps.SHIP_CHAIN drift from kernel-classification.json"
    return True, "fresh"
