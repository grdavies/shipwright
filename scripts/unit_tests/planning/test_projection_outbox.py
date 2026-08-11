"""PRD 090 R5 — durable projection outbox fixtures (Z,O,M,B,S,E)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_authority as pa
import planning_projection_ledger as ppl
import planning_refusal_ledger as prl


def test_r5_outbox_fields_appended_on_projection_upsert(tmp_path: Path) -> None:
    result = ppl.projection_ledger_upsert(
        tmp_path,
        unit_id="090-prd",
        artifact_type="prd",
        provider="linear",
        entity_id="proj-1",
        owned_fields={"title": "PRD 090"},
    )
    assert result["verdict"] == "pass"
    ledger = ppl.load_projection_ledger(tmp_path)
    assert ledger["outbox"]
    event = ledger["outbox"][-1]
    assert event["aggregateId"] == "linear::prd::090-prd"
    assert event["destination"] == "linear"
    assert event["idempotencyKey"]
    assert event["attemptCount"] == 1
    assert event["deliveryStatus"] == "delivered"
    assert ppl.projection_is_dirty(tmp_path) is False


def test_r5_dirty_derived_from_undelivered_outbox(tmp_path: Path) -> None:
    ledger = ppl.load_projection_ledger(tmp_path)
    ppl.append_projection_outbox_event(
        ledger,
        aggregate_id="issue-store::gap-001",
        destination="issue-store",
        idempotency_key="pending-1",
        delivery_status="pending",
        last_error="simulated-outage",
    )
    ppl.save_projection_ledger(tmp_path, ledger)
    assert ppl.projection_is_dirty(tmp_path) is True
    ppl.update_outbox_delivery_status(
        ledger,
        idempotency_key="pending-1",
        delivery_status="delivered",
    )
    ppl.save_projection_ledger(tmp_path, ledger)
    assert ppl.projection_is_dirty(tmp_path) is False


def test_r5_refusal_maps_to_outbox_without_dual_dirty(tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gi = tmp_git_repo / ".gitignore"
    gi.write_text(".cursor/**\n", encoding="utf-8")
    cfg_path = tmp_git_repo / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        '{"planning":{"refusalLedger":{"path":".cursor/sw-refusal-ledger"}}}',
        encoding="utf-8",
    )

    def _noop_redact(content: str) -> str:
        return content

    monkeypatch.setattr(prl, "redact_refusal_body", _noop_redact)
    recorded = prl.record_refusal(
        tmp_git_repo,
        unit_id="gap-001",
        operation="gap-projection",
        intended_body="fixture body",
        authority_state="online",
        authority_reason="projection-unavailable",
        projection_destination="issue-store",
    )
    assert recorded["verdict"] == "ok"
    ledger = ppl.load_projection_ledger(tmp_git_repo)
    destinations = {event["destination"] for event in ledger["outbox"]}
    assert "refusal-ledger" in destinations
    assert "issue-store" in destinations
    pending = [event for event in ledger["outbox"] if event["deliveryStatus"] == "pending"]
    assert pending
    assert ppl.projection_is_dirty(tmp_git_repo) is True


def test_r5_drain_on_mutate_clears_outage_pending(tmp_path: Path) -> None:
    ledger = ppl.load_projection_ledger(tmp_path)
    ppl.append_projection_outbox_event(
        ledger,
        aggregate_id="issue-store::gap-002",
        destination="issue-store",
        idempotency_key="retry-1",
        delivery_status="pending",
        last_error="simulated-outage",
    )
    ppl.save_projection_ledger(tmp_path, ledger)
    attempts = {"count": 0}

    def _flaky_handler(_root: Path, event: dict, _scope: str) -> dict:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return {"verdict": "fail", "error": "simulated-outage", "deliveryStatus": "pending"}
        return {"verdict": "pass", "deliveryStatus": "delivered"}

    first = pa.drain_outbox_on_mutate(tmp_path, delivery_handler=_flaky_handler)
    assert first["pendingCount"] == 1
    assert ppl.projection_is_dirty(tmp_path) is True
    ledger = ppl.load_projection_ledger(tmp_path)
    pending = [event for event in ledger["outbox"] if event["deliveryStatus"] == "pending"][0]
    assert pending["attemptCount"] >= 2

    second = pa.drain_outbox_on_mutate(tmp_path, delivery_handler=_flaky_handler)
    assert second["drainedCount"] == 1
    assert ppl.projection_is_dirty(tmp_path) is False


def test_r5_malformed_outbox_fails_closed(tmp_path: Path) -> None:
    path = ppl.projection_ledger_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schemaVersion":2,"scope":"default","outbox":[{"eventId":"x"}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="outbox-event-malformed"):
        ppl.load_projection_ledger(tmp_path)