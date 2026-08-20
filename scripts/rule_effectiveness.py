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
SCHEMA_VERSION = 1
AUTHORIZED_WRITER = "rule_effectiveness"

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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    args.root = str(Path(args.root).resolve())
    return int(args.handler(args))


if __name__ == "__main__":
    run_module_main(main)
