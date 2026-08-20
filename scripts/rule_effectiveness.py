#!/usr/bin/env python3
"""Rule effectiveness telemetry — append-only events and provider routing (PRD 280 phase 1)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
SCHEMA_PATH = ROOT / "core" / "sw-reference" / "rule-effectiveness-record.schema.json"
RECOMMENDATION_SCHEMA_PATH = ROOT / "core" / "sw-reference" / "rule-recommendation.schema.json"
SAFETY_RULE_IDS_PATH = ROOT / "core" / "sw-reference" / "safety-rule-ids.json"
SCHEMA_VERSION = 1
RECOMMENDATION_SCHEMA_VERSION = 1
AUTHORIZED_WRITER = "rule_effectiveness"

RECOMMENDATION_CLASSES = frozenset(
    {"retain", "merge", "narrow", "re-evaluate", "retire"}
)
MIN_EVENTS_FOR_RETAIN = 3
RETIRE_ERROR_RATE_THRESHOLD = 0.5
RETIRE_MIN_EVENTS = 2

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from memory_redact import RedactionError, redact_with_postcondition
from memory_sot import resolve_memory_provider

RuleEffectivenessRecord = dict[str, Any]


class RuleEffectivenessError(RuntimeError):
    """Base error for rule effectiveness operations."""


class ValidationError(RuleEffectivenessError):
    """Record failed schema or redaction validation."""


class ProviderOfflineError(RuleEffectivenessError):
    """Provider routing refused — fail closed for mutating paths."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_recommendation_schema() -> dict[str, Any]:
    return json.loads(RECOMMENDATION_SCHEMA_PATH.read_text(encoding="utf-8"))


def load_safety_rule_ids() -> set[str]:
    """Return safety-tagged rule ids from canonical manifest (R4)."""
    if not SAFETY_RULE_IDS_PATH.is_file():
        return set()
    try:
        data = json.loads(SAFETY_RULE_IDS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = data.get("ruleIds") if isinstance(data, dict) else []
    if not isinstance(ids, list):
        return set()
    return {str(item).strip() for item in ids if str(item).strip()}


def is_safety_tagged(rule_id: str) -> bool:
    return rule_id.strip() in load_safety_rule_ids()


def _waivers_path(store_root: Path) -> Path:
    return store_root / "waivers.json"


def load_waivers(store_root: Path) -> list[dict[str, Any]]:
    path = _waivers_path(store_root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("waivers") if isinstance(data, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def has_retire_waiver(store_root: Path, rule_id: str) -> bool:
    """True when an approved waiver exists for autonomous retire on this rule."""
    for row in load_waivers(store_root):
        if str(row.get("ruleId") or "") != rule_id:
            continue
        if str(row.get("recommendation") or "") != "retire":
            continue
        if row.get("approvedAt"):
            return True
    return False


def record_waiver(
    store_root: Path,
    *,
    rule_id: str,
    recommendation: str,
    approved_by: str,
    reason: str,
) -> dict[str, Any]:
    """Record a human-gated waiver for safety exception (audit-gated, not autonomous)."""
    if recommendation not in RECOMMENDATION_CLASSES:
        return {"verdict": "reject", "reason": "invalid-recommendation"}
    store_root.mkdir(parents=True, exist_ok=True)
    waiver_id = hashlib.sha256(
        _canonical_bytes(
            {
                "ruleId": rule_id,
                "recommendation": recommendation,
                "approvedBy": approved_by,
                "approvedAt": utc_now_iso(),
            }
        )
    ).hexdigest()
    row = {
        "waiverId": waiver_id,
        "ruleId": rule_id,
        "recommendation": recommendation,
        "approvedBy": approved_by,
        "approvedAt": utc_now_iso(),
        "reason": reason,
    }
    existing = load_waivers(store_root)
    existing.append(row)
    _waivers_path(store_root).write_text(
        json.dumps({"waivers": existing}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"verdict": "pass", "action": "record-waiver", "waiver": row}


def aggregate_rule_metrics(events: Iterable[Mapping[str, Any]], rule_id: str) -> dict[str, Any]:
    """Aggregate effectiveness events for one rule into supporting metrics."""
    loaded = 0
    errors = 0
    unreachable = 0
    revoked = 0
    filtered = 0
    total = 0
    for event in events:
        if str(event.get("ruleId") or "") != rule_id:
            continue
        total += 1
        outcome = str(event.get("outcome") or "")
        if outcome == "loaded":
            loaded += 1
        elif outcome == "error":
            errors += 1
        elif outcome == "unreachable":
            unreachable += 1
        elif outcome == "revoked":
            revoked += 1
        elif outcome == "filtered":
            filtered += 1
    load_success_rate = (loaded / total) if total else 0.0
    error_rate = (errors / total) if total else 0.0
    return {
        "eventCount": total,
        "loadedCount": loaded,
        "errorCount": errors,
        "unreachableCount": unreachable,
        "revokedCount": revoked,
        "filteredCount": filtered,
        "loadSuccessRate": round(load_success_rate, 4),
        "errorRate": round(error_rate, 4),
    }


def _classify_from_metrics(metrics: Mapping[str, Any]) -> tuple[str, str, float]:
    """Derive advisory recommendation class from aggregated metrics (R3)."""
    total = int(metrics.get("eventCount") or 0)
    loaded = int(metrics.get("loadedCount") or 0)
    errors = int(metrics.get("errorCount") or 0)
    unreachable = int(metrics.get("unreachableCount") or 0)
    revoked = int(metrics.get("revokedCount") or 0)
    filtered = int(metrics.get("filteredCount") or 0)
    error_rate = float(metrics.get("errorRate") or 0.0)
    load_success_rate = float(metrics.get("loadSuccessRate") or 0.0)

    if total == 0:
        return (
            "re-evaluate",
            "no effectiveness events observed — gather signal before lifecycle change",
            0.35,
        )

    if revoked > 0 and loaded == 0:
        return (
            "retire",
            "rule revoked with no successful loads in telemetry window",
            0.75,
        )

    if total >= RETIRE_MIN_EVENTS and error_rate >= RETIRE_ERROR_RATE_THRESHOLD:
        return (
            "retire",
            f"error rate {error_rate:.0%} across {total} events exceeds retire threshold",
            0.7,
        )

    if unreachable > 0 and loaded == 0 and total >= RETIRE_MIN_EVENTS:
        return (
            "retire",
            "persistent unreachable outcomes with zero successful loads",
            0.65,
        )

    if filtered > 0 and error_rate > 0.2:
        return (
            "narrow",
            "filtered outcomes with elevated errors — narrow scope or tighten allowlist",
            0.6,
        )

    if total < MIN_EVENTS_FOR_RETAIN:
        return (
            "re-evaluate",
            f"only {total} event(s) — insufficient signal for confident lifecycle action",
            0.45,
        )

    if load_success_rate >= 0.8 and errors == 0:
        return (
            "retain",
            f"stable loads ({loaded}/{total}) with low error rate",
            0.85,
        )

    if filtered > 0 and load_success_rate < 0.5:
        return (
            "narrow",
            "mixed filtered/loaded outcomes suggest narrowing standing guidance",
            0.55,
        )

    if errors > 0 and load_success_rate >= 0.5:
        return (
            "re-evaluate",
            "mixed success and errors — human review before promotion or retirement",
            0.5,
        )

    return (
        "merge",
        "low-distinct signal — consider collapsing duplicate or overlapping rule memories",
        0.4,
    )


def enforce_safety_exception(
    rule_id: str,
    recommendation: str,
    store_root: Path,
) -> tuple[str, bool, str | None]:
    """Refuse autonomous retire for safety-tagged rules without waiver (R4)."""
    if recommendation != "retire" or not is_safety_tagged(rule_id):
        return recommendation, False, None
    if has_retire_waiver(store_root, rule_id):
        return recommendation, False, None
    return (
        "re-evaluate",
        True,
        "safety-tagged rule: autonomous retire refused — waiver required via /sw-memory-audit",
    )


def build_recommendation(
    rule_id: str,
    metrics: Mapping[str, Any],
    *,
    store_root: Path,
) -> dict[str, Any]:
    """Build one advisory recommendation artifact for a rule."""
    raw_class, reason, confidence = _classify_from_metrics(metrics)
    final_class, safety_blocked, safety_reason = enforce_safety_exception(
        rule_id, raw_class, store_root
    )
    if safety_blocked and safety_reason:
        reason = safety_reason
        confidence = min(confidence, 0.5)
    recommendation: dict[str, Any] = {
        "schemaVersion": RECOMMENDATION_SCHEMA_VERSION,
        "ruleId": rule_id,
        "recommendation": final_class,
        "reason": reason,
        "confidence": round(confidence, 3),
        "supportingMetrics": dict(metrics),
        "safetyTagged": is_safety_tagged(rule_id),
        "safetyBlocked": safety_blocked,
        "generatedAt": utc_now_iso(),
        "auditHandoffRequired": final_class in ("retire", "merge", "narrow"),
    }
    return recommendation


def validate_recommendation(recommendation: Mapping[str, Any]) -> dict[str, Any]:
    try:
        import jsonschema

        schema = load_recommendation_schema()
        jsonschema.validate(dict(recommendation), schema)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "fail", "reason": "schema-invalid", "errors": [str(exc)]}
    return {"verdict": "pass", "recommendation": dict(recommendation)}


def classify_recommendations(
    repo_root: str | Path,
    *,
    provider: str | None = None,
    rule_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Classify lifecycle recommendations for all observed or requested rules."""
    root = Path(repo_root)
    events = list_events(root, provider=provider, limit=10000)
    store_root = resolve_store_root(root, provider=provider)
    observed: set[str] = {str(e.get("ruleId") or "") for e in events if e.get("ruleId")}
    if rule_ids:
        observed.update(str(r).strip() for r in rule_ids if str(r).strip())
    if not observed:
        observed = set(load_safety_rule_ids())
    out: list[dict[str, Any]] = []
    for rid in sorted(observed):
        metrics = aggregate_rule_metrics(events, rid)
        out.append(build_recommendation(rid, metrics, store_root=store_root))
    return out


def recommendations_report(
    repo_root: str | Path,
    *,
    provider: str | None = None,
    rule_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Advisory recommendations report artifact (R3/R5)."""
    recommendations = classify_recommendations(
        repo_root, provider=provider, rule_ids=rule_ids
    )
    safety_refusals = [
        r["ruleId"]
        for r in recommendations
        if r.get("safetyBlocked")
    ]
    return {
        "verdict": "pass",
        "action": "recommendations-report",
        "schemaVersion": RECOMMENDATION_SCHEMA_VERSION,
        "generatedAt": utc_now_iso(),
        "recommendationCount": len(recommendations),
        "safetyRefusals": safety_refusals,
        "auditHandoff": "/sw-memory-audit",
        "reportCommand": "python3 scripts/rule_effectiveness.py recommendations report",
        "recommendations": recommendations,
    }


def write_recommendations_report(
    repo_root: str | Path,
    out_path: Path,
    *,
    provider: str | None = None,
) -> dict[str, Any]:
    report = recommendations_report(repo_root, provider=provider)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {"verdict": "pass", "action": "write-recommendations-report", "path": str(out_path)}


def _basic_validate(record: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in (
        "schemaVersion",
        "eventId",
        "ruleId",
        "surface",
        "provider",
        "outcome",
        "recordedAt",
    ):
        if key not in record:
            errors.append(f"missing:{key}")
    rule_id = record.get("ruleId")
    if isinstance(rule_id, str) and not rule_id.strip():
        errors.append("empty:ruleId")
    return errors


def validate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a RuleEffectivenessRecord against JSON Schema (fail-closed)."""
    errors = _basic_validate(record)
    if errors:
        return {"verdict": "fail", "reason": "schema-invalid", "errors": errors}
    try:
        import jsonschema

        schema = load_schema()
        jsonschema.validate(dict(record), schema)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 — surface validation failures
        return {"verdict": "fail", "reason": "schema-invalid", "errors": [str(exc)]}
    return {"verdict": "pass", "record": dict(record)}


def redact_record(record: Mapping[str, Any]) -> RuleEffectivenessRecord:
    """Redact record payload before persistence (R12 — no secrets/transcripts)."""
    serialized = json.dumps(dict(record), ensure_ascii=False)
    try:
        redacted_text, residuals = redact_with_postcondition(serialized, destination="local")
    except RedactionError as exc:
        raise ValidationError(f"redaction-failed:{exc}") from exc
    if residuals:
        raise ValidationError(f"residual-detectors:{sorted(residuals)}")
    parsed = json.loads(redacted_text)
    if not isinstance(parsed, dict):
        raise ValidationError("redaction-invalid-json")
    return parsed


def compute_event_id(
    *,
    rule_id: str,
    surface: str,
    provider: str | None,
    outcome: str,
    batch_digest: str | None = None,
) -> str:
    """Derive a stable idempotency key for append-only ingest."""
    material = {
        "ruleId": rule_id,
        "surface": surface,
        "provider": provider,
        "outcome": outcome,
        "batchDigest": batch_digest or "",
    }
    return hashlib.sha256(_canonical_bytes(material)).hexdigest()


def build_record(
    *,
    rule_id: str,
    surface: str,
    provider: str | None,
    outcome: str,
    metrics: Mapping[str, int] | None = None,
    cohort_digest: str | None = None,
    batch_digest: str | None = None,
    recorded_at: str | None = None,
) -> RuleEffectivenessRecord:
    event_id = compute_event_id(
        rule_id=rule_id,
        surface=surface,
        provider=provider,
        outcome=outcome,
        batch_digest=batch_digest,
    )
    record: RuleEffectivenessRecord = {
        "schemaVersion": SCHEMA_VERSION,
        "eventId": event_id,
        "ruleId": rule_id,
        "surface": surface,
        "provider": provider,
        "outcome": outcome,
        "recordedAt": recorded_at or utc_now_iso(),
    }
    if metrics:
        record["metrics"] = {key: int(value) for key, value in metrics.items()}
    if cohort_digest:
        record["cohortDigest"] = cohort_digest
    validation = validate_record(record)
    if validation["verdict"] != "pass":
        raise ValidationError(str(validation.get("errors")))
    return record


def default_store_root(repo_root: str | Path) -> Path:
    """Gitignored append-only effectiveness store."""
    return Path(repo_root) / ".cursor" / "sw-rule-effectiveness"


def _events_path(store_root: Path) -> Path:
    return store_root / "events.jsonl"


def _index_path(store_root: Path) -> Path:
    return store_root / "event-index.json"


def _load_index(store_root: Path) -> set[str]:
    path = _index_path(store_root)
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = data.get("eventIds") if isinstance(data, dict) else []
    return {str(item) for item in ids if isinstance(item, str)}


def _save_index(store_root: Path, event_ids: set[str]) -> None:
    store_root.mkdir(parents=True, exist_ok=True)
    _index_path(store_root).write_text(
        json.dumps({"eventIds": sorted(event_ids)}, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_store_root(repo_root: Path, *, provider: str | None) -> Path:
    """Route persistence to local adjunct for all providers (read-only telemetry)."""
    _ = provider
    return default_store_root(repo_root)


def put_event(
    repo_root: str | Path,
    record: Mapping[str, Any],
    *,
    provider: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Append one validated effectiveness event (idempotent on eventId)."""
    validation = validate_record(record)
    if validation["verdict"] != "pass":
        return {"verdict": "reject", "reason": "schema-invalid", "errors": validation.get("errors")}
    redacted = redact_record(validation["record"])
    root = Path(repo_root)
    resolved_provider = provider if provider is not None else resolve_memory_provider(root)
    store_root = resolve_store_root(root, provider=resolved_provider)
    event_id = str(redacted["eventId"])
    if dry_run:
        return {
            "verdict": "pass",
            "action": "put-event",
            "eventId": event_id,
            "dryRun": True,
            "provider": resolved_provider,
            "storeRoot": str(store_root),
        }
    store_root.mkdir(parents=True, exist_ok=True)
    known = _load_index(store_root)
    if event_id in known:
        return {
            "verdict": "pass",
            "action": "put-event",
            "eventId": event_id,
            "idempotent": True,
            "provider": resolved_provider,
        }
    line = _canonical_bytes(redacted)
    with _events_path(store_root).open("ab") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    known.add(event_id)
    _save_index(store_root, known)
    return {
        "verdict": "pass",
        "action": "put-event",
        "eventId": event_id,
        "idempotent": False,
        "provider": resolved_provider,
    }


def list_events(
    repo_root: str | Path,
    *,
    provider: str | None = None,
    rule_id: str | None = None,
    surface: str | None = None,
    limit: int = 100,
) -> list[RuleEffectivenessRecord]:
    """List persisted events with optional filters."""
    root = Path(repo_root)
    resolved_provider = provider if provider is not None else resolve_memory_provider(root)
    store_root = resolve_store_root(root, provider=resolved_provider)
    events_path = _events_path(store_root)
    if not events_path.is_file():
        return []
    out: list[RuleEffectivenessRecord] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if rule_id and row.get("ruleId") != rule_id:
            continue
        if surface and row.get("surface") != surface:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _rule_id(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("id") or entry.get("ruleId") or entry.get("name") or "").strip()
    return str(entry).strip()


def emit_rules_load_events(
    repo_root: str | Path,
    *,
    surface: str,
    provider: str | None,
    rules: Iterable[Any],
    outcome: str = "loaded",
    metrics: Mapping[str, int] | None = None,
    batch_digest: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Emit one event per rule for a rules-load surface (idempotent per rule batch)."""
    emitted = 0
    skipped = 0
    errors: list[str] = []
    for entry in rules:
        rid = _rule_id(entry)
        if not rid:
            continue
        per_rule_metrics = dict(metrics or {})
        if isinstance(entry, dict):
            summary = entry.get("summary") or entry.get("content") or ""
            if isinstance(summary, str):
                per_rule_metrics.setdefault("summaryLength", len(summary))
        try:
            record = build_record(
                rule_id=rid,
                surface=surface,
                provider=provider,
                outcome=outcome,
                metrics=per_rule_metrics or None,
                batch_digest=batch_digest,
            )
            result = put_event(repo_root, record, provider=provider, dry_run=dry_run)
            if result.get("idempotent"):
                skipped += 1
            else:
                emitted += 1
        except (ValidationError, ProviderOfflineError) as exc:
            errors.append(str(exc))
    if errors:
        return {
            "verdict": "halt",
            "reason": "redaction-or-validation",
            "errors": errors,
            "emitted": emitted,
            "skipped": skipped,
        }
    return {
        "verdict": "pass",
        "emitted": emitted,
        "skipped": skipped,
        "surface": surface,
        "provider": provider,
    }


def emit_provider_fetch_events(
    repo_root: str | Path,
    *,
    provider: str,
    rules: Iterable[Any],
    ok: bool,
) -> dict[str, Any]:
    """Emit effectiveness events from a provider rules-fetch adapter."""
    rules_list = list(rules)
    outcome = "loaded" if ok else "unreachable"
    batch_digest = hashlib.sha256(
        _canonical_bytes({"provider": provider, "ok": ok})
    ).hexdigest()
    return emit_rules_load_events(
        repo_root,
        surface="provider-rules-fetch",
        provider=provider,
        rules=rules_list,
        outcome=outcome,
        metrics={"rulesReturned": len(rules_list)} if ok else None,
        batch_digest=batch_digest,
    )


def emit_memory_preflight_rules_load(
    repo_root: str | Path,
    *,
    provider: str | None,
    rules: Iterable[Any],
    allowlist_count: int | None = None,
) -> dict[str, Any]:
    """Emit from memory-preflight rules-load after allowlist filtering."""
    surface = os.environ.get("SW_RULE_EFFECTIVENESS_SURFACE", "rules-load")
    rules_list = list(rules)
    metrics: dict[str, int] = {"rulesAllowlisted": len(rules_list)}
    if allowlist_count is not None:
        metrics["rulesAllowlisted"] = allowlist_count
    batch_digest = hashlib.sha256(
        _canonical_bytes({"surface": surface, "provider": provider, "count": len(rules_list)})
    ).hexdigest()
    return emit_rules_load_events(
        repo_root,
        surface=surface,
        provider=provider,
        rules=rules_list,
        outcome="loaded",
        metrics=metrics,
        batch_digest=batch_digest,
    )


def _cmd_validate(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.record).read_text(encoding="utf-8"))
    result = validate_record(payload)
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "pass" else 1


def _cmd_put(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.record).read_text(encoding="utf-8"))
    result = put_event(args.root, payload, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "pass" else 1


def _cmd_list(args: argparse.Namespace) -> int:
    rows = list_events(
        args.root,
        provider=args.provider,
        rule_id=args.rule_id,
        surface=args.surface,
        limit=args.limit,
    )
    print(json.dumps({"verdict": "pass", "events": rows}, indent=2))
    return 0


def _cmd_recommendations_report(args: argparse.Namespace) -> int:
    report = recommendations_report(args.root, provider=args.provider)
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        report = {**report, "writtenTo": str(out_path.resolve())}
    print(json.dumps(report, indent=2))
    return 0


def _cmd_record_waiver(args: argparse.Namespace) -> int:
    root = Path(args.root)
    store_root = resolve_store_root(root, provider=args.provider)
    result = record_waiver(
        store_root,
        rule_id=args.rule_id,
        recommendation=args.recommendation,
        approved_by=args.approved_by,
        reason=args.reason,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "pass" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rule effectiveness telemetry CLI")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate a record JSON file")
    validate.add_argument("record", help="Path to record JSON")
    validate.set_defaults(handler=_cmd_validate)

    put = sub.add_parser("put-event", help="Persist one event")
    put.add_argument("record", help="Path to record JSON")
    put.add_argument("--dry-run", action="store_true")
    put.set_defaults(handler=_cmd_put)

    list_cmd = sub.add_parser("list-events", help="List persisted events")
    list_cmd.add_argument("--provider")
    list_cmd.add_argument("--rule-id")
    list_cmd.add_argument("--surface")
    list_cmd.add_argument("--limit", type=int, default=100)
    list_cmd.set_defaults(handler=_cmd_list)

    recommendations = sub.add_parser("recommendations", help="Rule lifecycle recommendations (R3)")
    rec_sub = recommendations.add_subparsers(dest="rec_command", required=True)
    report = rec_sub.add_parser("report", help="Emit advisory recommendations JSON report")
    report.add_argument("--provider")
    report.add_argument("--out", help="Optional path to write report JSON")
    report.set_defaults(handler=_cmd_recommendations_report)

    waiver = sub.add_parser("record-waiver", help="Record human-gated safety waiver (audit only)")
    waiver.add_argument("rule_id")
    waiver.add_argument("--recommendation", default="retire")
    waiver.add_argument("--approved-by", required=True)
    waiver.add_argument("--reason", required=True)
    waiver.add_argument("--provider")
    waiver.set_defaults(handler=_cmd_record_waiver)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    args.root = str(Path(args.root).resolve())
    return int(args.handler(args))


if __name__ == "__main__":
    run_module_main(main)
