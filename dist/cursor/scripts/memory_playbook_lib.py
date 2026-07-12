"""Confidence-scored playbook memory (PRD 064 R26-R28, R33)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from check_gate_lib import cfg_value, load_workflow_config

PLAYBOOK_CATEGORY = "playbook"
CODE_CONTEXT_CATEGORY = "code-context"
CONFIDENCE_CATEGORIES = frozenset({PLAYBOOK_CATEGORY, CODE_CONTEXT_CATEGORY, "learning"})
PLAYBOOK_STATUSES = frozenset({"draft", "active"})
SKEPTIC_VERDICTS = frozenset({"pass", "fail", "pending"})

DEFAULT_PLAYBOOK_CONFIG: dict[str, Any] = {
    "enabled": True,
    "injectMinConfidence": 0.75,
    "activeMinConfidence": 0.6,
    "promoteMinSuccessRate": 0.8,
    "promoteMinUsage": 5,
    "demoteMaxSuccessRate": 0.4,
    "demoteMinUsage": 5,
    "confidenceStep": 0.05,
}

STEP_HEADER_RE = re.compile(r"^##\s+Step\s+\d+:", re.MULTILINE)
COMMAND_RE = re.compile(r"^\s*-\s*command:\s*(.+)$", re.MULTILINE)
EXPECTED_RE = re.compile(r"^\s*-\s*expected:\s*(.+)$", re.MULTILINE)
FALLBACK_RE = re.compile(r"^\s*-\s*fallback:\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class PlaybookConfig:
    enabled: bool
    inject_min_confidence: float
    active_min_confidence: float
    promote_min_success_rate: float
    promote_min_usage: int
    demote_max_success_rate: float
    demote_min_usage: int
    confidence_step: float


def load_playbook_config(root: Path) -> PlaybookConfig:
    cfg = load_workflow_config(root)
    block = cfg_value(cfg, "memory", "playbooks", default={}) or {}
    if not isinstance(block, dict):
        block = {}
    merged = {**DEFAULT_PLAYBOOK_CONFIG, **block}
    return PlaybookConfig(
        enabled=bool(merged.get("enabled", True)),
        inject_min_confidence=float(merged.get("injectMinConfidence", 0.75)),
        active_min_confidence=float(merged.get("activeMinConfidence", 0.6)),
        promote_min_success_rate=float(merged.get("promoteMinSuccessRate", 0.8)),
        promote_min_usage=int(merged.get("promoteMinUsage", 5)),
        demote_max_success_rate=float(merged.get("demoteMaxSuccessRate", 0.4)),
        demote_min_usage=int(merged.get("demoteMinUsage", 5)),
        confidence_step=float(merged.get("confidenceStep", 0.05)),
    )


def resolve_store_dir(root: Path) -> Path:
    cfg = load_workflow_config(root)
    memory = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    in_repo = memory.get("inRepo") if isinstance(memory.get("inRepo"), dict) else {}
    store_rel = str(in_repo.get("storeDir") or ".cursor/sw-memory")
    return (root / store_rel).resolve()


def _import_memory_search():
    import importlib.util

    path = Path(__file__).resolve().parent / "in-repo-memory-search.py"
    spec = importlib.util.spec_from_file_location("in_repo_memory_search", path)
    if spec is None or spec.loader is None:
        raise ImportError("in-repo-memory-search.py not found")
    mem = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mem)
    return mem


def load_playbook_records(store: Path) -> list[dict[str, Any]]:
    mem = _import_memory_search()
    records = mem.load_store_records(store)
    return [r for r in records if str(r.get("category") or "") == PLAYBOOK_CATEGORY]


def parse_keywords(fields: dict[str, Any]) -> list[str]:
    raw = fields.get("triggerKeywords") or fields.get("trigger_keywords") or []
    if isinstance(raw, str):
        return [part.strip().lower() for part in raw.split(",") if part.strip()]
    if isinstance(raw, list):
        return [str(item).strip().lower() for item in raw if str(item).strip()]
    return []


def parse_prerequisites(fields: dict[str, Any], body: str) -> list[str]:
    raw = fields.get("prerequisites")
    items: list[str] = []
    if isinstance(raw, list):
        items.extend(str(item).strip() for item in raw if str(item).strip())
    elif isinstance(raw, str) and raw.strip():
        items.append(raw.strip())
    if "# Prerequisites" in body:
        section = body.split("# Prerequisites", 1)[1]
        section = section.split("#", 1)[0]
        for line in section.splitlines():
            line = line.strip()
            if line.startswith("- "):
                items.append(line[2:].strip())
    return items


def parse_steps(body: str) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    if "# Steps" not in body and not STEP_HEADER_RE.search(body):
        return steps
    chunks = STEP_HEADER_RE.split(body)
    headers = STEP_HEADER_RE.findall(body)
    for header, chunk in zip(headers, chunks[1:]):
        title = header.replace("##", "").strip()
        command = (COMMAND_RE.search(chunk) or [None, ""])[1].strip().strip("`")
        expected = (EXPECTED_RE.search(chunk) or [None, ""])[1].strip().strip("`")
        fallback = (FALLBACK_RE.search(chunk) or [None, ""])[1].strip().strip("`")
        steps.append({
            "title": title,
            "command": command,
            "expected": expected,
            "fallback": fallback,
        })
    return steps


def parse_verification(fields: dict[str, Any], body: str) -> list[str]:
    raw = fields.get("verification")
    items: list[str] = []
    if isinstance(raw, list):
        items.extend(str(item).strip() for item in raw if str(item).strip())
    elif isinstance(raw, str) and raw.strip():
        items.append(raw.strip())
    if "# Verification" in body:
        section = body.split("# Verification", 1)[1]
        section = section.split("#", 1)[0]
        for line in section.splitlines():
            line = line.strip()
            if line.startswith("- "):
                items.append(line[2:].strip())
    return items


def playbook_struct(record: dict[str, Any]) -> dict[str, Any]:
    fields = dict(record.get("fields") or {})
    body = str(record.get("body") or "")
    return {
        "id": record.get("id"),
        "category": PLAYBOOK_CATEGORY,
        "playbookStatus": str(fields.get("playbookStatus") or "draft"),
        "triggerKeywords": parse_keywords(fields),
        "prerequisites": parse_prerequisites(fields, body),
        "steps": parse_steps(body),
        "verification": parse_verification(fields, body),
        "confidence": float(fields.get("confidence") or 0.0),
        "usage_count": int(fields.get("usage_count") or 0),
        "success_count": int(fields.get("success_count") or 0),
        "auditTelemetryRef": str(fields.get("auditTelemetryRef") or ""),
        "skepticVerdict": str(fields.get("skepticVerdict") or "pending"),
    }


def success_rate(usage_count: int, success_count: int) -> float:
    if usage_count <= 0:
        return 0.0
    return success_count / usage_count


def audit_telemetry_valid(root: Path, ref: str) -> bool:
    if not ref:
        return False
    path = Path(ref)
    if not path.is_absolute():
        path = root / ref
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    verdict = str(payload.get("verdict") or "").lower()
    if verdict in {"pass", "verified", "green"}:
        return True
    claims = payload.get("claims")
    if isinstance(claims, list) and claims:
        return all(str(item.get("verdict") or "").lower() == "pass" for item in claims if isinstance(item, dict))
    return False


def promotion_eligible(root: Path, fields: dict[str, Any], config: PlaybookConfig) -> tuple[bool, str]:
    status = str(fields.get("playbookStatus") or "draft")
    if status == "active":
        return True, "already-active"
    skeptic = str(fields.get("skepticVerdict") or "pending").lower()
    if skeptic != "pass":
        return False, "skeptic-not-pass"
    audit_ref = str(fields.get("auditTelemetryRef") or "")
    if not audit_telemetry_valid(root, audit_ref):
        return False, "audit-telemetry-missing-or-fail"
    confidence = float(fields.get("confidence") or 0.0)
    if confidence < config.active_min_confidence:
        return False, "confidence-below-active-threshold"
    return True, "eligible"


def injection_eligible(
    root: Path,
    record: dict[str, Any],
    config: PlaybookConfig,
) -> tuple[bool, str]:
    if not config.enabled:
        return False, "playbooks-disabled"
    fields = dict(record.get("fields") or {})
    status = str(fields.get("playbookStatus") or "draft")
    if status != "active":
        return False, "not-active"
    eligible, reason = promotion_eligible(root, fields, config)
    if not eligible and reason != "already-active":
        return False, reason
    confidence = float(fields.get("confidence") or 0.0)
    if confidence < config.inject_min_confidence:
        return False, "confidence-below-inject-threshold"
    return True, "eligible"


def keyword_match_score(keywords: list[str], signals: list[str]) -> int:
    if not keywords or not signals:
        return 0
    signal_set = {s.lower() for s in signals if s}
    return sum(1 for kw in keywords if kw in signal_set or any(kw in sig for sig in signal_set))


def collect_signal_tokens(signal_context: dict[str, Any] | None) -> list[str]:
    tokens: list[str] = []
    if not signal_context:
        return tokens
    for key in ("command", "skill", "surface", "phase", "query", "scope"):
        value = signal_context.get(key)
        if isinstance(value, str) and value.strip():
            tokens.append(value.strip().lower())
    for key in ("file_paths", "files", "keywords"):
        value = signal_context.get(key)
        if isinstance(value, list):
            tokens.extend(str(item).strip().lower() for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            tokens.append(value.strip().lower())
    return tokens


def match_playbooks(
    store: Path,
    *,
    signal_context: dict[str, Any] | None = None,
    root: Path | None = None,
    config: PlaybookConfig | None = None,
) -> list[dict[str, Any]]:
    repo = root or store.parent
    cfg = config or load_playbook_config(repo)
    signals = collect_signal_tokens(signal_context)
    matched: list[dict[str, Any]] = []
    for record in load_playbook_records(store):
        fields = dict(record.get("fields") or {})
        keywords = parse_keywords(fields)
        score = keyword_match_score(keywords, signals)
        if score <= 0 and signals:
            continue
        if not signals:
            score = 1
        struct = playbook_struct(record)
        eligible, gate_reason = injection_eligible(repo, record, cfg)
        matched.append({
            **struct,
            "matchScore": score,
            "injectEligible": eligible,
            "gateReason": gate_reason,
        })
    matched.sort(
        key=lambda item: (
            -int(item.get("injectEligible", False)),
            -item["matchScore"],
            -item["confidence"],
            str(item["id"]),
        )
    )
    return matched


def render_playbook_primary_context(record: dict[str, Any]) -> str:
    struct = playbook_struct(record)
    lines = [
        f"# Playbook: {struct['id']}",
        "",
        f"status: {struct['playbookStatus']} | confidence: {struct['confidence']:.2f}",
        "",
    ]
    if struct["prerequisites"]:
        lines.append("## Prerequisites")
        lines.extend(f"- {item}" for item in struct["prerequisites"])
        lines.append("")
    if struct["steps"]:
        lines.append("## Steps")
        for step in struct["steps"]:
            lines.append(f"### {step['title']}")
            if step["command"]:
                lines.append(f"- command: `{step['command']}`")
            if step["expected"]:
                lines.append(f"- expected: `{step['expected']}`")
            if step["fallback"]:
                lines.append(f"- fallback: `{step['fallback']}`")
            lines.append("")
    if struct["verification"]:
        lines.append("## Verification")
        lines.extend(f"- {item}" for item in struct["verification"])
    return "\n".join(lines).strip() + "\n"


def primary_inject_blocks(
    store: Path,
    *,
    signal_context: dict[str, Any] | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    repo = root or store.parent
    config = load_playbook_config(repo)
    blocks: list[dict[str, Any]] = []
    for item in match_playbooks(store, signal_context=signal_context, root=repo, config=config):
        if not item.get("injectEligible"):
            continue
        record = next((r for r in load_playbook_records(store) if r["id"] == item["id"]), None)
        if not record:
            continue
        blocks.append({
            "label": f"primary-playbook:{item['id']}",
            "contentType": "prose",
            "text": render_playbook_primary_context(record),
            "allowPathReference": False,
        })
        break
    return blocks


def reconcile_confidence_fields(
    fields: dict[str, Any],
    config: PlaybookConfig,
) -> tuple[dict[str, Any], list[str]]:
    category = str(fields.get("category") or "")
    if category not in CONFIDENCE_CATEGORIES:
        return fields, []
    usage = int(fields.get("usage_count") or 0)
    success = int(fields.get("success_count") or 0)
    confidence = float(fields.get("confidence") or 0.0)
    actions: list[str] = []
    rate = success_rate(usage, success)
    updated = dict(fields)
    if usage >= config.promote_min_usage and rate >= config.promote_min_success_rate:
        new_conf = min(1.0, confidence + config.confidence_step)
        if new_conf > confidence:
            updated["confidence"] = round(new_conf, 3)
            actions.append("promote-confidence")
    elif usage >= config.demote_min_usage and rate <= config.demote_max_success_rate:
        new_conf = max(0.0, confidence - config.confidence_step)
        if new_conf < confidence:
            updated["confidence"] = round(new_conf, 3)
            actions.append("demote-confidence")
    return updated, actions


def record_usage(
    store: Path,
    playbook_id: str,
    *,
    success: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    mem = _import_memory_search()
    repo = root or store.parent
    config = load_playbook_config(repo)
    records = mem.load_store_records(store)
    record = next((r for r in records if r["id"] == playbook_id), None)
    if not record:
        return {"verdict": "fail", "reason": "playbook-not-found", "id": playbook_id}
    fields = dict(record["fields"])
    fields["usage_count"] = int(fields.get("usage_count") or 0) + 1
    if success:
        fields["success_count"] = int(fields.get("success_count") or 0) + 1
    fields, actions = reconcile_confidence_fields(fields, config)
    updated = {**record, "fields": fields}
    mem.write_memory_record(store, updated)
    mem.maintain_derived(store)
    return {
        "verdict": "ok",
        "id": playbook_id,
        "usage_count": fields["usage_count"],
        "success_count": int(fields.get("success_count") or 0),
        "confidence": float(fields.get("confidence") or 0.0),
        "actions": actions,
    }


def evaluate_promotion(
    store: Path,
    playbook_id: str,
    *,
    root: Path | None = None,
    promote: bool = False,
) -> dict[str, Any]:
    mem = _import_memory_search()
    repo = root or store.parent
    config = load_playbook_config(repo)
    records = mem.load_store_records(store)
    record = next((r for r in records if r["id"] == playbook_id), None)
    if not record:
        return {"verdict": "fail", "reason": "playbook-not-found", "id": playbook_id}
    fields = dict(record["fields"])
    eligible, reason = promotion_eligible(repo, fields, config)
    result = {
        "verdict": "ok" if eligible else "fail",
        "id": playbook_id,
        "eligible": eligible,
        "reason": reason,
        "playbookStatus": str(fields.get("playbookStatus") or "draft"),
    }
    if promote and eligible:
        fields["playbookStatus"] = "active"
        mem.write_memory_record(store, {**record, "fields": fields})
        mem.maintain_derived(store)
        result["promoted"] = True
        result["playbookStatus"] = "active"
    return result


def reconcile_store_confidence(store: Path, *, root: Path | None = None) -> dict[str, Any]:
    mem = _import_memory_search()
    repo = root or store.parent
    config = load_playbook_config(repo)
    actions: list[dict[str, Any]] = []
    for record in mem.load_store_records(store):
        category = str(record.get("category") or "")
        if category not in CONFIDENCE_CATEGORIES:
            continue
        fields = dict(record["fields"])
        updated_fields, field_actions = reconcile_confidence_fields(fields, config)
        if updated_fields != fields:
            mem.write_memory_record(store, {**record, "fields": updated_fields})
            actions.append({"id": record["id"], "actions": field_actions})
    if actions:
        mem.maintain_derived(store)
    return {"verdict": "ok", "updated": len(actions), "actions": actions}
