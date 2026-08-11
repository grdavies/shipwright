"""PRD 066 phase 2 — projection identity ledger, typed drift, dirty resume (R2, R5, R27, R28).

PRD 090 R5 — durable projection outbox: delivery events, derived dirty, drain/retry.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECTION_LEDGER_SCHEMA_VERSION = 2
PROJECTION_LEDGER_DIR = Path(".cursor") / "sw-projection-ledger"
PROJECTION_LEDGER_PROVIDERS = frozenset({"linear", "github-projects"})
PROJECTION_ARTIFACT_TYPES = frozenset(
    {"prd", "brainstorm", "gap", "phase", "task", "progress", "program", "cycle-wave"}
)
OUTBOX_DELIVERY_STATUSES = frozenset({"pending", "delivered", "failed"})
OUTBOX_DESTINATIONS = frozenset(
    {"refusal-ledger", "linear", "github-projects", "projection-checkpoint"}
)

OutboxDeliveryHandler = Callable[[Path, dict[str, Any], str], dict[str, Any]]
_OUTBOX_DELIVERY_HANDLER: OutboxDeliveryHandler | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def owned_fields_digest(owned_fields: dict[str, Any] | None) -> str:
    """Stable digest of Shipwright-owned projection fields (R27)."""
    payload = owned_fields or {}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def projection_ledger_path(root: Path, scope: str = "default") -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (scope or "default").strip()) or "default"
    return root / PROJECTION_LEDGER_DIR / f"{safe}.json"


def empty_projection_ledger(*, scope: str = "default") -> dict[str, Any]:
    return {
        "schemaVersion": PROJECTION_LEDGER_SCHEMA_VERSION,
        "scope": scope,
        "dirty": False,
        "dirtyReason": None,
        "checkpointGeneration": 0,
        "entries": {},
        "outbox": [],
        "audit": [],
        "updatedAt": _utc_now_iso(),
    }


def set_outbox_delivery_handler(handler: OutboxDeliveryHandler | None) -> None:
    """Test hook — override default outbox delivery handler."""
    global _OUTBOX_DELIVERY_HANDLER
    _OUTBOX_DELIVERY_HANDLER = handler


def _validate_outbox_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("outbox-event-malformed")
    required = (
        "eventId",
        "aggregateId",
        "sourceRevision",
        "destination",
        "idempotencyKey",
        "attemptCount",
        "deliveryStatus",
    )
    missing = [field for field in required if field not in event]
    if missing:
        raise ValueError(f"outbox-event-malformed:missing:{','.join(missing)}")
    status = str(event.get("deliveryStatus") or "")
    if status not in OUTBOX_DELIVERY_STATUSES:
        raise ValueError("outbox-event-malformed:delivery-status")
    destination = str(event.get("destination") or "")
    if not destination:
        raise ValueError("outbox-event-malformed:destination")
    return event


def _normalize_outbox(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    raw = ledger.get("outbox")
    if raw is None:
        ledger["outbox"] = []
        return ledger["outbox"]
    if not isinstance(raw, list):
        raise ValueError("outbox-event-malformed:list")
    events: list[dict[str, Any]] = []
    for item in raw:
        events.append(_validate_outbox_event(item))
    ledger["outbox"] = events
    return events


def _sync_dirty_from_outbox(ledger: dict[str, Any]) -> None:
    """R5 — dirty is derived from undelivered outbox events."""
    pending = [event for event in _normalize_outbox(ledger) if event.get("deliveryStatus") != "delivered"]
    if pending:
        ledger["dirty"] = True
        reasons = sorted(
            {
                str(event.get("lastError") or event.get("aggregateId") or event.get("destination") or "pending")
                for event in pending
            }
        )
        ledger["dirtyReason"] = reasons[0] if len(reasons) == 1 else "outbox-pending"
    else:
        ledger["dirty"] = False
        ledger["dirtyReason"] = None


def _has_undelivered_outbox(ledger: dict[str, Any]) -> bool:
    return any(
        event.get("deliveryStatus") != "delivered" for event in _normalize_outbox(ledger)
    )


def append_projection_outbox_event(
    ledger: dict[str, Any],
    *,
    aggregate_id: str,
    destination: str,
    idempotency_key: str,
    delivery_status: str = "pending",
    last_error: str | None = None,
    source_revision: int | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Append an outbox delivery record and sync derived dirty state."""
    if delivery_status not in OUTBOX_DELIVERY_STATUSES:
        raise ValueError("outbox-event-malformed:delivery-status")
    events = _normalize_outbox(ledger)
    for existing in events:
        if existing.get("idempotencyKey") == idempotency_key:
            return existing
    revision = (
        int(source_revision)
        if source_revision is not None
        else int(ledger.get("checkpointGeneration") or 0)
    )
    event = {
        "eventId": event_id or str(uuid.uuid4()),
        "aggregateId": aggregate_id,
        "sourceRevision": revision,
        "destination": destination,
        "idempotencyKey": idempotency_key,
        "attemptCount": 1,
        "lastError": last_error,
        "deliveryStatus": delivery_status,
        "createdAt": _utc_now_iso(),
        "updatedAt": _utc_now_iso(),
    }
    _validate_outbox_event(event)
    events.append(event)
    ledger["outbox"] = events
    _sync_dirty_from_outbox(ledger)
    return event


def list_undelivered_outbox_events(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        event
        for event in _normalize_outbox(ledger)
        if event.get("deliveryStatus") != "delivered"
    ]


def update_outbox_delivery_status(
    ledger: dict[str, Any],
    *,
    event_id: str | None = None,
    idempotency_key: str | None = None,
    delivery_status: str,
    last_error: str | None = None,
    increment_attempt: bool = False,
) -> dict[str, Any]:
    if delivery_status not in OUTBOX_DELIVERY_STATUSES:
        return {"verdict": "fail", "error": "outbox-event-malformed:delivery-status"}
    events = _normalize_outbox(ledger)
    target: dict[str, Any] | None = None
    for event in events:
        if event_id and event.get("eventId") == event_id:
            target = event
            break
        if idempotency_key and event.get("idempotencyKey") == idempotency_key:
            target = event
            break
    if target is None:
        return {"verdict": "fail", "error": "outbox-event-missing"}
    if increment_attempt:
        target["attemptCount"] = int(target.get("attemptCount") or 0) + 1
    target["deliveryStatus"] = delivery_status
    target["lastError"] = last_error
    target["updatedAt"] = _utc_now_iso()
    _sync_dirty_from_outbox(ledger)
    return {"verdict": "pass", "action": "update-outbox-delivery-status", "event": target}


def _default_outbox_delivery_handler(
    root: Path,
    event: dict[str, Any],
    scope: str,
) -> dict[str, Any]:
    destination = str(event.get("destination") or "")
    if destination == "refusal-ledger":
        import planning_ledger_store as pls
        from host_lib import load_workflow_config

        cfg = load_workflow_config(root)
        ledger_dir = pls.resolve_ledger_path(root, cfg)
        entry = pls.load_entry(pls.entries_dir(ledger_dir), str(event.get("idempotencyKey") or ""))
        if entry is None:
            return {"verdict": "fail", "error": "refusal-entry-missing"}
        return {"verdict": "pass", "deliveryStatus": "delivered"}
    if destination in PROJECTION_LEDGER_PROVIDERS:
        ledger = load_projection_ledger(root, scope=scope)
        aggregate = str(event.get("aggregateId") or "")
        if aggregate in (ledger.get("entries") or {}):
            return {"verdict": "pass", "deliveryStatus": "delivered"}
        return {"verdict": "fail", "error": "projection-entry-missing", "deliveryStatus": "pending"}
    if destination == "projection-checkpoint":
        return {"verdict": "pass", "deliveryStatus": "delivered"}
    return {"verdict": "fail", "error": "unsupported-outbox-destination", "deliveryStatus": "pending"}


def drain_projection_outbox(
    root: Path,
    *,
    scope: str = "default",
    delivery_handler: OutboxDeliveryHandler | None = None,
) -> dict[str, Any]:
    """Drain undelivered outbox events; retry increments attemptCount on failure."""
    ledger = load_projection_ledger(root, scope=scope)
    handler = delivery_handler or _OUTBOX_DELIVERY_HANDLER or _default_outbox_delivery_handler
    drained: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for event in list_undelivered_outbox_events(ledger):
        result = handler(root, event, scope)
        if result.get("verdict") == "pass" and result.get("deliveryStatus") == "delivered":
            update_outbox_delivery_status(
                ledger,
                event_id=str(event.get("eventId")),
                delivery_status="delivered",
                last_error=None,
            )
            drained.append(event)
        else:
            update_outbox_delivery_status(
                ledger,
                event_id=str(event.get("eventId")),
                delivery_status=str(result.get("deliveryStatus") or "pending"),
                last_error=str(result.get("error") or result.get("lastError") or "delivery-failed"),
                increment_attempt=True,
            )
            pending.append(event)
    path = save_projection_ledger(root, ledger, scope=scope)
    return {
        "verdict": "pass",
        "action": "drain-projection-outbox",
        "drainedCount": len(drained),
        "pendingCount": len(pending),
        "dirty": bool(ledger.get("dirty")),
        "path": str(path),
    }


def load_projection_ledger(root: Path, *, scope: str = "default") -> dict[str, Any]:
    path = projection_ledger_path(root, scope)
    if not path.is_file():
        return empty_projection_ledger(scope=scope)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_projection_ledger(scope=scope)
    if not isinstance(doc, dict):
        return empty_projection_ledger(scope=scope)
    doc.setdefault("schemaVersion", PROJECTION_LEDGER_SCHEMA_VERSION)
    doc.setdefault("scope", scope)
    doc.setdefault("dirty", False)
    doc.setdefault("dirtyReason", None)
    doc.setdefault("checkpointGeneration", 0)
    doc.setdefault("entries", {})
    doc.setdefault("outbox", [])
    doc.setdefault("audit", [])
    _normalize_outbox(doc)
    _sync_dirty_from_outbox(doc)
    return doc


def save_projection_ledger(root: Path, ledger: dict[str, Any], *, scope: str = "default") -> Path:
    path = projection_ledger_path(root, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(ledger)
    payload["scope"] = scope
    _normalize_outbox(payload)
    _sync_dirty_from_outbox(payload)
    payload["updatedAt"] = _utc_now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _ledger_entry_key(unit_id: str, artifact_type: str, provider: str) -> str:
    return f"{provider}::{artifact_type}::{unit_id}"


def assert_portable_graph_authority(
    graph: dict[str, Any],
    *,
    projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """R2 — portable semantic graph remains SoT; projections never become freeze authority."""
    if not isinstance(graph, dict) or not graph:
        return {
            "verdict": "fail",
            "error": "portable-graph-missing",
            "action": "assert-portable-graph-authority",
        }
    freeze_authority = str(graph.get("freezeAuthority") or graph.get("authority") or "portable-graph")
    if freeze_authority not in {"portable-graph", "semantic-graph", "graph"}:
        return {
            "verdict": "fail",
            "error": "freeze-authority-not-portable-graph",
            "freezeAuthority": freeze_authority,
            "action": "assert-portable-graph-authority",
        }
    if isinstance(projection, dict):
        if projection.get("freezeAuthority") not in (None, "portable-graph", "derived"):
            return {
                "verdict": "fail",
                "error": "projection-claimed-freeze-authority",
                "projectionFreezeAuthority": projection.get("freezeAuthority"),
                "action": "assert-portable-graph-authority",
            }
        if projection.get("isSourceOfTruth") is True:
            return {
                "verdict": "fail",
                "error": "projection-claimed-sot",
                "action": "assert-portable-graph-authority",
            }
    return {
        "verdict": "pass",
        "action": "assert-portable-graph-authority",
        "freezeAuthority": "portable-graph",
        "projectionRebuildable": True,
    }


def projection_ledger_upsert(
    root: Path,
    *,
    unit_id: str,
    artifact_type: str,
    provider: str,
    entity_id: str,
    owned_fields: dict[str, Any] | None = None,
    marker: str | None = None,
    scope: str = "default",
) -> dict[str, Any]:
    """R5 — upsert unit-id + artifact-type → provider entity id."""
    if provider not in PROJECTION_LEDGER_PROVIDERS:
        return {"verdict": "fail", "error": "unsupported-ledger-provider", "provider": provider}
    if artifact_type not in PROJECTION_ARTIFACT_TYPES:
        return {"verdict": "fail", "error": "unsupported-artifact-type", "artifactType": artifact_type}
    if not unit_id or not entity_id:
        return {"verdict": "fail", "error": "ledger-upsert-missing-ids"}
    ledger = load_projection_ledger(root, scope=scope)
    key = _ledger_entry_key(unit_id, artifact_type, provider)
    digest = owned_fields_digest(owned_fields)
    entry = {
        "unitId": unit_id,
        "artifactType": artifact_type,
        "provider": provider,
        "entityId": entity_id,
        "marker": marker,
        "ownedFieldsDigest": digest,
        "ownedFields": dict(owned_fields or {}),
        "generation": int(ledger.get("checkpointGeneration") or 0),
        "updatedAt": _utc_now_iso(),
    }
    ledger.setdefault("entries", {})[key] = entry
    idem = hashlib.sha256(
        f"{key}:{digest}:{entity_id}".encode("utf-8")
    ).hexdigest()
    append_projection_outbox_event(
        ledger,
        aggregate_id=key,
        destination=provider,
        idempotency_key=idem,
        delivery_status="delivered",
        source_revision=int(ledger.get("checkpointGeneration") or 0),
    )
    path = save_projection_ledger(root, ledger, scope=scope)
    return {
        "verdict": "pass",
        "action": "projection-ledger-upsert",
        "key": key,
        "entry": entry,
        "path": str(path),
    }


def projection_ledger_lookup(
    root: Path,
    *,
    unit_id: str,
    artifact_type: str,
    provider: str,
    scope: str = "default",
) -> dict[str, Any]:
    ledger = load_projection_ledger(root, scope=scope)
    key = _ledger_entry_key(unit_id, artifact_type, provider)
    entry = (ledger.get("entries") or {}).get(key)
    if not entry:
        return {"verdict": "miss", "action": "projection-ledger-lookup", "key": key}
    return {"verdict": "pass", "action": "projection-ledger-lookup", "key": key, "entry": entry}


def projection_ledger_discover_by_marker(
    root: Path,
    *,
    provider: str,
    marker: str,
    scope: str = "default",
) -> dict[str, Any]:
    """R5 — discovery-by-marker fallback when ledger entry is missing."""
    if not marker:
        return {"verdict": "fail", "error": "marker-required"}
    ledger = load_projection_ledger(root, scope=scope)
    matches = [
        entry
        for entry in (ledger.get("entries") or {}).values()
        if isinstance(entry, dict)
        and entry.get("provider") == provider
        and entry.get("marker") == marker
    ]
    if not matches:
        return {"verdict": "miss", "action": "projection-ledger-discover-by-marker", "marker": marker}
    if len(matches) > 1:
        return {
            "verdict": "fail",
            "error": "ledger-duplicate-marker",
            "action": "projection-ledger-discover-by-marker",
            "marker": marker,
            "matches": matches,
        }
    return {
        "verdict": "pass",
        "action": "projection-ledger-discover-by-marker",
        "marker": marker,
        "entry": matches[0],
    }


def projection_ledger_reconcile_duplicates(
    root: Path,
    *,
    unit_id: str,
    artifact_type: str,
    provider: str,
    candidate_entity_ids: list[str],
    scope: str = "default",
) -> dict[str, Any]:
    """R5 — fail-closed duplicate reconciliation (collapse only when a single ledger winner exists)."""
    lookup = projection_ledger_lookup(
        root, unit_id=unit_id, artifact_type=artifact_type, provider=provider, scope=scope
    )
    unique = sorted({str(x) for x in candidate_entity_ids if x})
    if len(unique) <= 1:
        return {
            "verdict": "pass",
            "action": "projection-ledger-reconcile-duplicates",
            "entityIds": unique,
            "winner": unique[0] if unique else None,
            "collapsed": False,
        }
    if lookup.get("verdict") == "pass":
        winner = str((lookup.get("entry") or {}).get("entityId") or "")
        if winner and winner in unique:
            return {
                "verdict": "pass",
                "action": "projection-ledger-reconcile-duplicates",
                "entityIds": unique,
                "winner": winner,
                "collapsed": True,
                "note": "collapsed-to-ledger-winner",
            }
    return {
        "verdict": "fail",
        "error": "ledger-duplicate-entities",
        "action": "projection-ledger-reconcile-duplicates",
        "entityIds": unique,
        "unitId": unit_id,
        "artifactType": artifact_type,
        "provider": provider,
    }


def projection_ledger_checkpoint(root: Path, *, scope: str = "default") -> dict[str, Any]:
    """R28 — persist last-good ledger checkpoint generation."""
    ledger = load_projection_ledger(root, scope=scope)
    gen = int(ledger.get("checkpointGeneration") or 0) + 1
    ledger["checkpointGeneration"] = gen
    ledger["lastGoodCheckpointAt"] = _utc_now_iso()
    path = save_projection_ledger(root, ledger, scope=scope)
    return {
        "verdict": "pass",
        "action": "projection-ledger-checkpoint",
        "checkpointGeneration": gen,
        "path": str(path),
        "entryCount": len(ledger.get("entries") or {}),
    }


def set_projection_dirty(
    root: Path,
    *,
    reason: str,
    scope: str = "default",
    checkpoint: bool = True,
) -> dict[str, Any]:
    """R28 — mid-flight halt sets dirty via pending outbox event and retains checkpoint."""
    if checkpoint:
        projection_ledger_checkpoint(root, scope=scope)
    ledger = load_projection_ledger(root, scope=scope)
    idem = hashlib.sha256(
        f"projection-checkpoint:{scope}:{reason}:{ledger.get('checkpointGeneration')}".encode("utf-8")
    ).hexdigest()
    append_projection_outbox_event(
        ledger,
        aggregate_id=f"projection-checkpoint::{scope}",
        destination="projection-checkpoint",
        idempotency_key=idem,
        delivery_status="pending",
        last_error=reason or "projection-mid-flight-halt",
        source_revision=int(ledger.get("checkpointGeneration") or 0),
    )
    ledger["dirtyAt"] = _utc_now_iso()
    path = save_projection_ledger(root, ledger, scope=scope)
    return {
        "verdict": "pass",
        "action": "set-projection-dirty",
        "dirty": True,
        "dirtyReason": ledger.get("dirtyReason"),
        "checkpointGeneration": ledger.get("checkpointGeneration"),
        "path": str(path),
    }


def clear_projection_dirty(root: Path, *, scope: str = "default") -> dict[str, Any]:
    ledger = load_projection_ledger(root, scope=scope)
    if _has_undelivered_outbox(ledger):
        return {
            "verdict": "fail",
            "error": "outbox-pending",
            "action": "clear-projection-dirty",
            "pendingCount": len(list_undelivered_outbox_events(ledger)),
        }
    ledger["dirty"] = False
    ledger["dirtyReason"] = None
    ledger["clearedDirtyAt"] = _utc_now_iso()
    path = save_projection_ledger(root, ledger, scope=scope)
    return {"verdict": "pass", "action": "clear-projection-dirty", "dirty": False, "path": str(path)}


def projection_is_dirty(root: Path, *, scope: str = "default") -> bool:
    ledger = load_projection_ledger(root, scope=scope)
    return _has_undelivered_outbox(ledger) or bool(ledger.get("dirty"))


def check_projection_drift(
    root: Path,
    *,
    unit_id: str,
    artifact_type: str,
    provider: str,
    provider_owned_fields: dict[str, Any],
    overwrite_drift: bool = False,
    audit_actor: str | None = None,
    scope: str = "default",
) -> dict[str, Any]:
    """R27 — fail closed on typed drift; optional overwrite + audit only."""
    lookup = projection_ledger_lookup(
        root, unit_id=unit_id, artifact_type=artifact_type, provider=provider, scope=scope
    )
    if lookup.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "error": "ledger-entry-missing",
            "action": "check-projection-drift",
            "unitId": unit_id,
            "artifactType": artifact_type,
            "provider": provider,
        }
    entry = lookup["entry"]
    expected = str(entry.get("ownedFieldsDigest") or "")
    actual = owned_fields_digest(provider_owned_fields)
    if expected == actual:
        return {
            "verdict": "pass",
            "action": "check-projection-drift",
            "drift": False,
            "ownedFieldsDigest": expected,
        }
    if not overwrite_drift:
        return {
            "verdict": "fail",
            "error": "projection_drift",
            "action": "check-projection-drift",
            "drift": True,
            "expectedDigest": expected,
            "actualDigest": actual,
            "unitId": unit_id,
            "artifactType": artifact_type,
            "provider": provider,
            "entityId": entry.get("entityId"),
            "note": "default path never clobbers; pass overwrite_drift=True with audit",
        }
    ledger = load_projection_ledger(root, scope=scope)
    audit_entry = {
        "at": _utc_now_iso(),
        "actor": audit_actor or os.environ.get("USER") or "operator",
        "action": "overwrite-drift",
        "unitId": unit_id,
        "artifactType": artifact_type,
        "provider": provider,
        "entityId": entry.get("entityId"),
        "expectedDigest": expected,
        "actualDigest": actual,
    }
    ledger.setdefault("audit", []).append(audit_entry)
    key = _ledger_entry_key(unit_id, artifact_type, provider)
    entry = dict(entry)
    entry["ownedFields"] = dict(provider_owned_fields or {})
    entry["ownedFieldsDigest"] = actual
    entry["updatedAt"] = _utc_now_iso()
    entry["overwrittenDrift"] = True
    ledger.setdefault("entries", {})[key] = entry
    path = save_projection_ledger(root, ledger, scope=scope)
    return {
        "verdict": "pass",
        "action": "check-projection-drift",
        "drift": True,
        "overwritten": True,
        "audit": audit_entry,
        "entry": entry,
        "path": str(path),
    }


def resume_projection_from_checkpoint(
    root: Path,
    *,
    scope: str = "default",
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """R28 — resume from last-good checkpoint; refuse duplicate ledger entities."""
    authority = assert_portable_graph_authority(graph or {"freezeAuthority": "portable-graph"})
    if authority.get("verdict") != "pass":
        return authority
    ledger = load_projection_ledger(root, scope=scope)
    if not ledger.get("dirty"):
        return {
            "verdict": "pass",
            "action": "resume-projection-from-checkpoint",
            "dirty": False,
            "note": "already-clean",
            "checkpointGeneration": ledger.get("checkpointGeneration"),
            "entryCount": len(ledger.get("entries") or {}),
        }
    seen: dict[str, str] = {}
    duplicates: list[dict[str, Any]] = []
    for key, entry in (ledger.get("entries") or {}).items():
        if not isinstance(entry, dict):
            continue
        entity_id = str(entry.get("entityId") or "")
        provider = str(entry.get("provider") or "")
        if not entity_id:
            continue
        dup_key = f"{provider}::{entity_id}"
        if dup_key in seen:
            duplicates.append(
                {"entityId": entity_id, "provider": provider, "keys": [seen[dup_key], key]}
            )
        else:
            seen[dup_key] = key
    if duplicates:
        return {
            "verdict": "fail",
            "error": "ledger-duplicate-entities-on-resume",
            "action": "resume-projection-from-checkpoint",
            "duplicates": duplicates,
            "checkpointGeneration": ledger.get("checkpointGeneration"),
        }
    drain = drain_projection_outbox(root, scope=scope)
    ledger = load_projection_ledger(root, scope=scope)
    for event in list_undelivered_outbox_events(ledger):
        update_outbox_delivery_status(
            ledger,
            event_id=str(event.get("eventId")),
            delivery_status="delivered",
            last_error=None,
        )
    cleared = clear_projection_dirty(root, scope=scope)
    if cleared.get("verdict") != "pass":
        save_projection_ledger(root, ledger, scope=scope)
        return cleared
    return {
        "verdict": "pass",
        "action": "resume-projection-from-checkpoint",
        "dirty": False,
        "checkpointGeneration": ledger.get("checkpointGeneration"),
        "entryCount": len(ledger.get("entries") or {}),
        "cleared": cleared,
        "drain": drain,
    }


def rebuild_projection_from_graph(
    root: Path,
    graph: dict[str, Any],
    *,
    provider: str,
    units: list[dict[str, Any]] | None = None,
    overwrite_drift: bool = False,
    scope: str = "default",
) -> dict[str, Any]:
    """R2/R5 — idempotent rebuild helper: graph remains SoT; ledger upserts by key."""
    authority = assert_portable_graph_authority(graph, projection={"freezeAuthority": "derived"})
    if authority.get("verdict") != "pass":
        return authority
    if provider not in PROJECTION_LEDGER_PROVIDERS:
        return {"verdict": "fail", "error": "unsupported-ledger-provider", "provider": provider}
    if projection_is_dirty(root, scope=scope) and not overwrite_drift:
        return {
            "verdict": "fail",
            "error": "projection-dirty",
            "action": "rebuild-projection-from-graph",
            "note": "call resume_projection_from_checkpoint first",
        }
    targets = units or list(graph.get("units") or [])
    upserts: list[dict[str, Any]] = []
    for unit in targets:
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("unitId") or unit.get("id") or "")
        artifact_type = str(unit.get("artifactType") or unit.get("type") or "")
        entity_id = str(unit.get("entityId") or unit.get("providerEntityId") or "")
        if not (unit_id and artifact_type and entity_id):
            return {
                "verdict": "fail",
                "error": "rebuild-unit-incomplete",
                "unit": unit,
                "action": "rebuild-projection-from-graph",
            }
        owned = (
            unit.get("ownedFields")
            if isinstance(unit.get("ownedFields"), dict)
            else {k: unit[k] for k in ("title", "status", "marker") if k in unit}
        )
        existing = projection_ledger_lookup(
            root, unit_id=unit_id, artifact_type=artifact_type, provider=provider, scope=scope
        )
        if existing.get("verdict") == "pass":
            drift = check_projection_drift(
                root,
                unit_id=unit_id,
                artifact_type=artifact_type,
                provider=provider,
                provider_owned_fields=owned,
                overwrite_drift=overwrite_drift,
                scope=scope,
            )
            if drift.get("verdict") != "pass":
                return drift
        result = projection_ledger_upsert(
            root,
            unit_id=unit_id,
            artifact_type=artifact_type,
            provider=provider,
            entity_id=entity_id,
            owned_fields=owned,
            marker=str(unit.get("marker") or "") or None,
            scope=scope,
        )
        if result.get("verdict") != "pass":
            return result
        upserts.append(result)
    if projection_is_dirty(root, scope=scope):
        clear_projection_dirty(root, scope=scope)
    checkpoint = projection_ledger_checkpoint(root, scope=scope)
    return {
        "verdict": "pass",
        "action": "rebuild-projection-from-graph",
        "provider": provider,
        "upsertCount": len(upserts),
        "checkpoint": checkpoint,
        "freezeAuthority": "portable-graph",
    }
