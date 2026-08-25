#!/usr/bin/env python3
"""Portable cross-harness HandoffBundle@v1 export/import (PRD 280 gap-324 R8–R13)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from copy import deepcopy
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gate_evidence import digest_bytes, utc_now  # noqa: E402
from exploration_policy import DEFAULT_INTERACTION_MODE  # noqa: E402

SCHEMA_REL = Path("core/sw-reference/handoff-bundle.schema.json")
SCHEMA_VERSION = "HandoffBundle@v1"
DEFAULT_FRESHNESS_TTL_SECONDS = 86400
RESOLVED_STATUSES = frozenset({"resolved", "closed", "done", "cancelled"})
UNRESOLVED_STATUSES = frozenset({"open", "blocked", "unknown"})


def repo_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return start


def schema_path(root: Path | None = None) -> Path:
    return repo_root(root) / SCHEMA_REL


def load_schema(root: Path | None = None) -> dict[str, Any]:
    return json.loads(schema_path(root).read_text(encoding="utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_payload(payload: Mapping[str, Any]) -> str:
    material = {k: v for k, v in payload.items() if k != "bundleDigest"}
    return f"sha256:{hashlib.sha256(canonical_json(material).encode('utf-8')).hexdigest()}"


def validate_bundle(document: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Fail-closed schema validation for HandoffBundle@v1."""
    missing = [
        key
        for key in (
            "schemaVersion",
            "goal",
            "currentState",
            "resolvedDecisions",
            "unresolvedDecisions",
            "activeNode",
            "blockers",
            "evidence",
            "changedFiles",
            "relevantRules",
            "nextAction",
            "workflowDigest",
            "exportedAt",
            "expiresAt",
            "bundleDigest",
        )
        if key not in document
    ]
    if missing:
        return {"verdict": "fail", "error": "handoff:missing-keys", "missing": missing}
    if str(document.get("schemaVersion")) != SCHEMA_VERSION:
        return {"verdict": "fail", "error": "handoff:schema-version", "expected": SCHEMA_VERSION}
    expected = digest_payload(document)
    if str(document.get("bundleDigest")) != expected:
        return {"verdict": "fail", "error": "handoff:digest-mismatch", "expected": expected}
    try:
        import jsonschema

        jsonschema.validate(dict(document), load_schema(root))
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "fail", "error": "handoff:schema-invalid", "detail": str(exc)}
    return {"verdict": "pass"}


def _parse_iso8601(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def is_stale(document: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    expires = _parse_iso8601(str(document.get("expiresAt") or ""))
    if expires is None:
        return True
    current = now or datetime.now(timezone.utc)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return current >= expires


def redact_bundle_text(root: Path, text: str) -> str:
    from memory_redact import redact
    from planning_visibility import resolve_emission_destination

    destination = resolve_emission_destination("handoff-032")
    return redact(text, destination=destination)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def resolve_head_sha(root: Path) -> str:
    proc = _git(root, "rev-parse", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def changed_files(root: Path, base_ref: str | None = None) -> list[str]:
    base = base_ref or os.environ.get("SW_INTEGRATION_BRANCH") or "main"
    merge_base = _git(root, "merge-base", "HEAD", base)
    if merge_base.returncode != 0:
        diff = _git(root, "diff", "--name-only", "HEAD")
    else:
        diff = _git(root, "diff", "--name-only", merge_base.stdout.strip(), "HEAD")
    if diff.returncode != 0:
        return []
    return [line.strip() for line in diff.stdout.splitlines() if line.strip()]


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _shipwright_state(root: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "shipwright-state.py"), "read"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _deliver_status(root: Path, phase_slug: str | None) -> dict[str, Any]:
    if not phase_slug:
        return {}
    run_dir = os.environ.get("SW_RUN_DIR")
    candidates = []
    if run_dir:
        candidates.append(Path(run_dir) / "status.json")
    candidates.append(root / ".cursor" / "sw-deliver-runs" / phase_slug / "status.json")
    for candidate in candidates:
        payload = _read_json(candidate)
        if payload:
            return payload
    return {}


def _gate_evidence(root: Path, phase_slug: str | None) -> list[dict[str, Any]]:
    if not phase_slug:
        return []
    evidence_dir = root / ".cursor" / "sw-deliver-runs" / phase_slug / "gate-evidence"
    if not evidence_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(evidence_dir.glob("*.status.json")):
        payload = _read_json(path)
        if not payload:
            continue
        rows.append(
            {
                "kind": "gate-evidence",
                "path": str(path.relative_to(root)),
                "verdict": str(payload.get("verdict") or ""),
                "gateId": str(payload.get("gateId") or path.stem.replace(".status", "")),
            }
        )
    return rows


def _relevant_rules(root: Path) -> list[str]:
    allowlist = root / ".cursor" / "sw-memory-rule-allowlist.json"
    payload = _read_json(allowlist)
    if not payload:
        return []
    rules = payload.get("rules")
    if isinstance(rules, list):
        return [str(item) for item in rules if str(item).strip()]
    return []


def _decision_entries(document: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    from decision_graph.frontier import compute_frontier

    spec = document.get("spec")
    if not isinstance(spec, dict):
        return [], [], None
    nodes = spec.get("nodes")
    if not isinstance(nodes, list):
        return [], [], None

    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        status = str(node.get("status") or "open")
        entry = {
            "nodeId": node_id,
            "title": str(node.get("title") or ""),
            "status": status,
            "kind": str(node.get("kind") or ""),
        }
        if node.get("resolution"):
            entry["resolution"] = str(node.get("resolution"))
        if status in RESOLVED_STATUSES:
            resolved.append(entry)
        elif status in UNRESOLVED_STATUSES or status not in RESOLVED_STATUSES:
            unresolved.append(entry)
            if active is None and status == "open":
                active = {"nodeId": node_id, "title": entry["title"], "kind": entry["kind"]}

    frontier = compute_frontier(document)
    for blocked in frontier.get("blocked") or []:
        if not isinstance(blocked, dict):
            continue
        node_id = str(blocked.get("id") or "")
        if not node_id:
            continue
        if any(item["nodeId"] == node_id for item in unresolved):
            continue
        unresolved.append(
            {
                "nodeId": node_id,
                "title": str(blocked.get("title") or ""),
                "status": "blocked",
                "kind": str(blocked.get("kind") or ""),
            }
        )
    return resolved, unresolved, active


def export_decisions(
    root: Path,
    unit_id: str,
    *,
    handoff_degraded: bool = False,
) -> dict[str, Any]:
    from decision_graph.frontier import frontier_for_unit
    from decision_graph.schema import load_graph

    frontier = frontier_for_unit(root, unit_id)
    if frontier.get("verdict") != "pass":
        if handoff_degraded:
            return {
                "verdict": "degraded",
                "resolvedDecisions": [],
                "unresolvedDecisions": [],
                "activeNode": None,
                "blockers": [{"kind": "decision-graph", "detail": frontier.get("error") or "graph-unavailable"}],
            }
        return {
            "verdict": "fail",
            "error": "handoff:graph-unavailable",
            "detail": frontier,
            "resumeCommand": "Re-run with --handoff-degraded after operator ack",
        }

    graph_path = Path(str(frontier.get("graphPath") or ""))
    document = load_graph(graph_path)
    resolved, unresolved, active = _decision_entries(document)
    blockers = [
        {"kind": "decision-blocked", "detail": str(item.get("reason") or "blocked"), "nodeId": str(item.get("id") or "")}
        for item in (frontier.get("blocked") or [])
        if isinstance(item, dict)
    ]
    return {
        "verdict": "pass",
        "resolvedDecisions": resolved,
        "unresolvedDecisions": unresolved,
        "activeNode": active,
        "blockers": blockers,
        "graphPath": str(graph_path.relative_to(root)) if graph_path.is_file() else str(graph_path),
    }


def build_workflow_digest(payload: Mapping[str, Any]) -> str:
    material = {
        "goal": payload.get("goal"),
        "currentState": payload.get("currentState"),
        "resolvedDecisions": payload.get("resolvedDecisions"),
        "unresolvedDecisions": payload.get("unresolvedDecisions"),
        "nextAction": payload.get("nextAction"),
        "changedFiles": payload.get("changedFiles"),
    }
    return f"sha256:{hashlib.sha256(canonical_json(material).encode('utf-8')).hexdigest()}"


def export_bundle(
    root: Path,
    *,
    unit_id: str | None = None,
    phase_slug: str | None = None,
    run_id: str | None = None,
    goal: str | None = None,
    ttl_seconds: int = DEFAULT_FRESHNESS_TTL_SECONDS,
    handoff_degraded: bool = False,
    base_ref: str | None = None,
) -> dict[str, Any]:
    """Machine-generate a HandoffBundle from durable deliver/graph/decision state."""
    root = repo_root(root)
    unit_id = unit_id or os.environ.get("SW_UNIT_ID") or ""
    phase_slug = phase_slug or os.environ.get("SW_PHASE_SLUG") or ""
    run_id = run_id or os.environ.get("SW_RUN_ID") or os.environ.get("SW_DELIVER_RUN_ID") or ""
    ship_state = _shipwright_state(root)
    deliver_status = _deliver_status(root, phase_slug or None)
    head_sha = resolve_head_sha(root)

    if not unit_id:
        task_list = os.environ.get("SW_TASK_LIST") or ship_state.get("taskList")
        if isinstance(task_list, str) and task_list:
            unit_id = Path(task_list).stem

    decision_export = export_decisions(root, unit_id, handoff_degraded=handoff_degraded) if unit_id else {
        "verdict": "degraded" if handoff_degraded else "fail",
        "error": "handoff:missing-unit-id",
        "resolvedDecisions": [],
        "unresolvedDecisions": [],
        "activeNode": None,
        "blockers": [],
    }
    if decision_export.get("verdict") == "fail":
        return decision_export

    phase_status = str(deliver_status.get("verdict") or ship_state.get("phaseStatus") or "unknown")
    summary_bits = [
        f"phase={phase_slug or 'unknown'}",
        f"status={phase_status}",
        f"branch={ship_state.get('currentBranch') or _git(root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()}",
    ]
    current_state = {
        "summary": "; ".join(summary_bits),
        "phaseStatus": phase_status,
        "branch": str(ship_state.get("currentBranch") or ""),
        "deliverVerdict": str(deliver_status.get("verdict") or ""),
    }
    next_action = {
        "action": "review-handoff",
        "detail": "Import bundle on target harness; deliver resume requires materialize + dependency-gate (R13).",
    }
    if deliver_status.get("resumeCommand"):
        next_action["command"] = str(deliver_status.get("resumeCommand"))

    exported_at = utc_now()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=max(60, ttl_seconds))).strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "exportedAt": exported_at,
        "expiresAt": expires_at,
        "goal": goal or f"Continue planning unit {unit_id or phase_slug or 'unknown'}",
        "currentState": current_state,
        "resolvedDecisions": list(decision_export.get("resolvedDecisions") or []),
        "unresolvedDecisions": list(decision_export.get("unresolvedDecisions") or []),
        "activeNode": decision_export.get("activeNode"),
        "blockers": list(decision_export.get("blockers") or []),
        "evidence": _gate_evidence(root, phase_slug or None),
        "changedFiles": changed_files(root, base_ref=base_ref),
        "relevantRules": _relevant_rules(root),
        "nextAction": next_action,
    }
    if run_id:
        bundle["runId"] = run_id
    if unit_id:
        bundle["unitId"] = unit_id
    if phase_slug:
        bundle["phaseSlug"] = phase_slug
    if head_sha:
        bundle["headSha"] = head_sha
    if decision_export.get("verdict") == "degraded":
        bundle["handoffDegraded"] = True
    bundle["workflowDigest"] = build_workflow_digest(bundle)
    bundle["bundleDigest"] = digest_payload(bundle)

    validation = validate_bundle(bundle, root=root)
    if validation.get("verdict") != "pass":
        return validation

    redacted = redact_bundle_text(root, canonical_json(bundle))
    try:
        bundle = json.loads(redacted)
    except json.JSONDecodeError:
        return {"verdict": "fail", "error": "handoff:redaction-invalid-json"}
    bundle["bundleDigest"] = digest_payload(bundle)
    bundle["workflowDigest"] = build_workflow_digest(bundle)
    validation = validate_bundle(bundle, root=root)
    if validation.get("verdict") != "pass":
        return validation
    return {"verdict": "pass", "bundle": bundle, "readOnly": True}


def _extract_exploration_context(bundle: Mapping[str, Any]) -> dict[str, Any] | None:
    extensions = bundle.get("extensions")
    if isinstance(extensions, dict):
        exploration = extensions.get("exploration")
        if isinstance(exploration, dict) and exploration.get("explorationMapId"):
            return dict(exploration)
        cursor = extensions.get("cursor")
        if isinstance(cursor, dict):
            exploration = cursor.get("exploration")
            if isinstance(exploration, dict) and exploration.get("explorationMapId"):
                return dict(exploration)
    current_state = bundle.get("currentState")
    if isinstance(current_state, dict):
        exploration = current_state.get("exploration")
        if isinstance(exploration, dict) and exploration.get("explorationMapId"):
            return dict(exploration)
    return None


def _notebook_provenance(map_document: Mapping[str, Any]) -> dict[str, Any]:
    provenance = map_document.get("provenance")
    if not isinstance(provenance, dict):
        return {}
    notebook = provenance.get("notebook")
    if isinstance(notebook, dict):
        return dict(notebook)
    notebook_id = str(provenance.get("notebookId") or "").strip()
    if notebook_id:
        payload: dict[str, Any] = {"notebookId": notebook_id}
        source = provenance.get("source")
        if isinstance(source, str) and source.strip():
            payload["source"] = source.strip()
        return payload
    source = provenance.get("source")
    if isinstance(source, str) and source.strip():
        return {"source": source.strip()}
    return {}


def build_exploration_resume_context(
    map_document: Mapping[str, Any],
    *,
    brief: Mapping[str, Any] | None = None,
    interaction_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build exploration resume payload for HandoffBundle (PRD 331 R15, R39, R45)."""
    map_id = str(map_document.get("id") or "").strip()
    revision = int(map_document.get("revision", 1))
    if not map_id:
        raise ValueError("missing-map-id")
    mode = DEFAULT_INTERACTION_MODE
    state: dict[str, Any] = {"mode": mode}
    if interaction_state:
        if isinstance(interaction_state.get("mode"), str) and interaction_state["mode"].strip():
            state["mode"] = interaction_state["mode"].strip()
        for key in ("activeNodeId", "lastPrompt", "phase", "mapId", "expectedRevision"):
            value = interaction_state.get(key)
            if isinstance(value, str) and value.strip():
                state[key] = value.strip()
            elif isinstance(value, int):
                state[key] = value
    recovery = (
        f"Resume with `/sw-explore resume --map-id {map_id}` when map revision {revision} matches. "
        "If the live map advanced, re-export the handoff bundle — stale revisions fail closed."
    )
    context: dict[str, Any] = {
        "explorationMapId": map_id,
        "revision": revision,
        "mapRevision": revision,
        "notebookProvenance": _notebook_provenance(map_document),
        "interactionState": state,
        "recoveryInstructions": recovery,
    }
    if brief is not None:
        context["briefId"] = str(brief.get("id") or "")
        brief_revision = brief.get("sourceRevision")
        if isinstance(brief_revision, int):
            context["briefSourceRevision"] = brief_revision
        readiness = brief.get("readiness")
        context["brief"] = {
            "id": str(brief.get("id") or ""),
            "sourceRevision": brief_revision,
            "readyForDocHandoff": bool(
                isinstance(readiness, dict) and readiness.get("readyForDocHandoff")
            ),
            "invalidation": deepcopy(brief.get("invalidation") or {"state": "valid"}),
        }
        if isinstance(readiness, dict):
            context["forwardHandoffReady"] = bool(readiness.get("readyForDocHandoff"))
    return context


def _attach_exploration_context(bundle: dict[str, Any], exploration: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(bundle)
    current_state = dict(updated.get("currentState") or {})
    current_state["exploration"] = dict(exploration)
    updated["currentState"] = current_state
    extensions = dict(updated.get("extensions") or {})
    extensions["exploration"] = dict(exploration)
    cursor = dict(extensions.get("cursor") or {})
    cursor["exploration"] = dict(exploration)
    extensions["cursor"] = cursor
    updated["extensions"] = extensions
    updated["nextAction"] = {
        "action": "resume-exploration",
        "detail": str(exploration.get("recoveryInstructions") or ""),
        "command": f"/sw-explore resume --map-id {exploration.get('explorationMapId')}",
    }
    updated["workflowDigest"] = build_workflow_digest(updated)
    updated["bundleDigest"] = digest_payload(updated)
    return updated


def export_exploration_bundle(
    root: Path,
    map_document: Mapping[str, Any],
    *,
    brief: Mapping[str, Any] | None = None,
    interaction_state: Mapping[str, Any] | None = None,
    goal: str | None = None,
    ttl_seconds: int = DEFAULT_FRESHNESS_TTL_SECONDS,
    handoff_degraded: bool = False,
    base_ref: str | None = None,
) -> dict[str, Any]:
    """Export HandoffBundle with cross-session exploration resume context (R15, R39, R45)."""
    from exploration_brief import emit_brief

    map_id = str(map_document.get("id") or "").strip()
    if not map_id:
        return {"verdict": "fail", "error": "handoff:missing-map-id"}
    live_brief = brief or emit_brief(map_document)
    exploration = build_exploration_resume_context(
        map_document,
        brief=live_brief,
        interaction_state=interaction_state,
    )
    result = export_bundle(
        root,
        unit_id=map_id,
        goal=goal or f"Resume exploration {map_id}",
        ttl_seconds=ttl_seconds,
        handoff_degraded=handoff_degraded if handoff_degraded else True,
        base_ref=base_ref,
    )
    if result.get("verdict") != "pass" or not isinstance(result.get("bundle"), dict):
        return result
    bundle = _attach_exploration_context(result["bundle"], exploration)
    validation = validate_bundle(bundle, root=root)
    if validation.get("verdict") != "pass":
        return validation
    redacted = redact_bundle_text(root, canonical_json(bundle))
    try:
        bundle = json.loads(redacted)
    except json.JSONDecodeError:
        return {"verdict": "fail", "error": "handoff:redaction-invalid-json"}
    bundle = _attach_exploration_context(bundle, exploration)
    validation = validate_bundle(bundle, root=root)
    if validation.get("verdict") != "pass":
        return validation
    return {"verdict": "pass", "bundle": bundle, "brief": live_brief, "readOnly": True}


def import_exploration_resume(
    root: Path,
    bundle: Mapping[str, Any] | str | Path,
    *,
    allow_stale: bool = False,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Validate imported bundle and return exploration resume context (never resumes deliver)."""
    result = import_bundle(root, bundle, allow_stale=allow_stale)
    if result.get("verdict") != "pass":
        return result
    clean = result["bundle"]
    exploration = _extract_exploration_context(clean)
    if exploration is None:
        return {"verdict": "fail", "error": "handoff:missing-exploration-context"}
    live_revision = exploration.get("revision") or exploration.get("mapRevision")
    if expected_revision is not None and live_revision != expected_revision:
        return {
            "verdict": "halt",
            "error": "handoff:stale-revision",
            "expectedRevision": expected_revision,
            "bundleRevision": live_revision,
            "resumeCommand": f"/sw-explore resume --map-id {exploration.get('explorationMapId')}",
        }
    brief = exploration.get("brief")
    brief_revision = exploration.get("briefSourceRevision")
    if isinstance(brief, dict):
        invalidation = brief.get("invalidation")
        if isinstance(invalidation, dict) and invalidation.get("state") != "valid":
            return {
                "verdict": "halt",
                "error": "handoff:brief-invalidated",
                "invalidation": invalidation,
                "resumeCommand": str(exploration.get("recoveryInstructions") or ""),
            }
    elif isinstance(brief_revision, int) and exploration.get("briefId"):
        invalidation_state = exploration.get("invalidation")
        if isinstance(invalidation_state, dict) and invalidation_state.get("state") != "valid":
            return {
                "verdict": "halt",
                "error": "handoff:brief-invalidated",
                "invalidation": invalidation_state,
                "resumeCommand": str(exploration.get("recoveryInstructions") or ""),
            }
    return {
        "verdict": "pass",
        "bundle": clean,
        "exploration": exploration,
        "resumeCommand": str(exploration.get("recoveryInstructions") or ""),
        "foreignHarnessResumeForbidden": True,
    }


def import_bundle(
    root: Path,
    bundle: Mapping[str, Any] | str | Path,
    *,
    allow_stale: bool = False,
) -> dict[str, Any]:
    """Validate, freshness-check, and redact an imported bundle. Never resumes deliver."""
    root = repo_root(root)
    document: dict[str, Any]
    if isinstance(bundle, (str, Path)):
        path = Path(bundle)
        if not path.is_file():
            return {"verdict": "fail", "error": "handoff:missing-file", "path": str(path)}
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"verdict": "fail", "error": "handoff:invalid-json", "detail": str(exc)}
    elif isinstance(bundle, Mapping):
        document = dict(bundle)
    else:
        return {"verdict": "fail", "error": "handoff:invalid-input"}

    validation = validate_bundle(document, root=root)
    if validation.get("verdict") != "pass":
        return validation

    if is_stale(document) and not allow_stale:
        return {
            "verdict": "halt",
            "error": "handoff:stale",
            "expiresAt": document.get("expiresAt"),
            "resumeCommand": "Refresh export via /sw-status --export-handoff",
            "foreignHarnessResumeForbidden": True,
        }

    redacted = redact_bundle_text(root, canonical_json(document))
    try:
        clean = json.loads(redacted)
    except json.JSONDecodeError:
        return {"verdict": "fail", "error": "handoff:import-redaction-invalid-json"}

    clean_validation = validate_bundle(clean, root=root)
    if clean_validation.get("verdict") != "pass":
        return clean_validation

    return {
        "verdict": "pass",
        "bundle": clean,
        "foreignHarnessResumeForbidden": True,
        "detail": "Bundle import is informational only; /sw-deliver resume requires materialize + dependency-gate.",
    }


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else repo_root()
    payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    result = validate_bundle(payload, root=root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("verdict") == "pass" else 20


def cmd_export(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else repo_root()
    result = export_bundle(
        root,
        unit_id=args.unit_id or None,
        phase_slug=args.phase_slug or None,
        run_id=args.run_id or None,
        goal=args.goal or None,
        ttl_seconds=int(args.ttl_seconds),
        handoff_degraded=bool(args.handoff_degraded),
        base_ref=args.base_ref or None,
    )
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if result.get("verdict") == "pass" and isinstance(result.get("bundle"), dict):
            out_path.write_text(
                json.dumps(result["bundle"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = {**result, "path": str(out_path)}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    verdict = str(result.get("verdict") or "")
    if verdict == "pass":
        return 0
    if verdict == "fail":
        return 20
    return 21


def cmd_import(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else repo_root()
    result = import_bundle(root, Path(args.path), allow_stale=bool(args.allow_stale))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    verdict = str(result.get("verdict") or "")
    if verdict == "pass":
        return 0
    if verdict == "halt":
        return 21
    return 20


def _read_json_file(path: str) -> dict[str, Any] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def cmd_export_exploration(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else repo_root()
    map_document = _read_json_file(args.map_json)
    if map_document is None:
        print(json.dumps({"verdict": "fail", "error": "handoff:invalid-map-json"}, indent=2))
        return 20
    brief = _read_json_file(args.brief_json)
    interaction = _read_json_file(args.interaction_json)
    result = export_exploration_bundle(
        root,
        map_document,
        brief=brief,
        interaction_state=interaction,
        goal=args.goal or None,
        ttl_seconds=int(args.ttl_seconds),
        handoff_degraded=bool(args.handoff_degraded),
        base_ref=args.base_ref or None,
    )
    if args.out and result.get("verdict") == "pass" and isinstance(result.get("bundle"), dict):
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result["bundle"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result = {**result, "path": str(out_path)}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    verdict = str(result.get("verdict") or "")
    if verdict == "pass":
        return 0
    if verdict == "halt":
        return 21
    return 20


def cmd_import_exploration(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else repo_root()
    expected_revision = None
    if str(args.expected_revision or "").strip():
        expected_revision = int(args.expected_revision)
    result = import_exploration_resume(
        root,
        Path(args.path),
        allow_stale=bool(args.allow_stale),
        expected_revision=expected_revision,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    verdict = str(result.get("verdict") or "")
    if verdict == "pass":
        return 0
    if verdict == "halt":
        return 21
    return 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HandoffBundle@v1 export/import (PRD 280 gap-324)")
    parser.add_argument("--root", default="", help="Repository root (default: git root from cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate bundle JSON against schema + digest")
    validate.add_argument("path")
    validate.set_defaults(func=cmd_validate)

    export = sub.add_parser("export", help="Export bundle from durable deliver/graph/decision state")
    export.add_argument("--unit-id", default="")
    export.add_argument("--phase-slug", default="")
    export.add_argument("--run-id", default="")
    export.add_argument("--goal", default="")
    export.add_argument("--ttl-seconds", default=str(DEFAULT_FRESHNESS_TTL_SECONDS))
    export.add_argument("--handoff-degraded", action="store_true")
    export.add_argument("--base-ref", default="")
    export.add_argument("--out", default="")
    export.set_defaults(func=cmd_export)

    import_cmd = sub.add_parser("import", help="Import bundle with freshness TTL + redaction")
    import_cmd.add_argument("path")
    import_cmd.add_argument("--allow-stale", action="store_true")
    import_cmd.set_defaults(func=cmd_import)

    export_exploration = sub.add_parser(
        "export-exploration",
        help="Export bundle with exploration resume context",
    )
    export_exploration.add_argument("--map-json", required=True, help="Path to ExplorationMap JSON")
    export_exploration.add_argument("--brief-json", default="", help="Optional precomputed brief JSON")
    export_exploration.add_argument("--interaction-json", default="", help="Optional interaction state JSON")
    export_exploration.add_argument("--goal", default="")
    export_exploration.add_argument("--ttl-seconds", default=str(DEFAULT_FRESHNESS_TTL_SECONDS))
    export_exploration.add_argument("--handoff-degraded", action="store_true")
    export_exploration.add_argument("--base-ref", default="")
    export_exploration.add_argument("--out", default="")
    export_exploration.set_defaults(func=cmd_export_exploration)

    import_exploration = sub.add_parser(
        "import-exploration",
        help="Import bundle and return exploration resume context",
    )
    import_exploration.add_argument("path")
    import_exploration.add_argument("--allow-stale", action="store_true")
    import_exploration.add_argument("--expected-revision", default="")
    import_exploration.set_defaults(func=cmd_import_exploration)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
