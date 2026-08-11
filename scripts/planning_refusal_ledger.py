#!/usr/bin/env python3
"""PRD 082 phase 6 — append-only refusal ledger entry model (R26)."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import load_workflow_config
from memory_redaction_provenance import (
    DEFAULT_DESTINATION_POLICY_ID,
    DEFAULT_DESTINATION_POLICY_VERSION,
)
import planning_ledger_store as pls
import planning_visibility

REFUSAL_LEDGER_SCHEMA_VERSION = 1


class RefusalLedgerError(RuntimeError):
    """Refusal ledger record contract violation."""


def compute_content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def compute_idempotency_key(unit_id: str, operation: str, content_hash: str) -> str:
    canonical = "\0".join((unit_id.strip(), operation.strip(), content_hash.strip()))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def redact_refusal_body(content: str) -> str:
    """Apply the same redaction chokepoint as planning backend writes."""
    destination = planning_visibility.resolve_emission_destination("store-get")
    proc = subprocess.run(
        [str(SCRIPT_DIR / "memory-redact.py"), "--destination", destination],
        input=content,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RefusalLedgerError(proc.stderr.strip() or "memory-redact failed")
    return proc.stdout


def build_refusal_entry(
    *,
    unit_id: str,
    operation: str,
    intended_body: str,
    authority_state: str,
    authority_reason: str | None,
    destination_policy_id: str = DEFAULT_DESTINATION_POLICY_ID,
    destination_policy_version: str = DEFAULT_DESTINATION_POLICY_VERSION,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    if not unit_id.strip():
        raise RefusalLedgerError("unit-id:missing")
    if not operation.strip():
        raise RefusalLedgerError("operation:missing")
    content_hash = compute_content_hash(intended_body)
    idempotency_key = compute_idempotency_key(unit_id, operation, content_hash)
    redacted_body = redact_refusal_body(intended_body)
    entry = {
        "schemaVersion": REFUSAL_LEDGER_SCHEMA_VERSION,
        "entryId": idempotency_key,
        "idempotencyKey": idempotency_key,
        "unitId": unit_id.strip(),
        "operation": operation.strip(),
        "contentHash": content_hash,
        "redactedBody": redacted_body,
        "redactedBodyDigest": compute_content_hash(redacted_body),
        "recordedAt": recorded_at or pls._utc_now(),
        "authorityState": authority_state.strip(),
        "authorityReason": authority_reason,
        "destinationPolicyId": destination_policy_id.strip(),
        "destinationPolicyVersion": str(destination_policy_version).strip(),
    }
    body = {k: v for k, v in entry.items() if k != "digest"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    entry["digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return entry


def record_refusal(
    root: Path,
    *,
    unit_id: str,
    operation: str,
    intended_body: str,
    authority_state: str,
    authority_reason: str | None,
    destination_policy_id: str = DEFAULT_DESTINATION_POLICY_ID,
    destination_policy_version: str = DEFAULT_DESTINATION_POLICY_VERSION,
    projection_destination: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    ledger_dir = pls.resolve_ledger_path(root, cfg)
    preflight = pls.verify_ledger_path_contract(root, ledger_dir)
    if preflight.get("verdict") != "ok":
        return {
            "verdict": "fail",
            "action": "record-refusal",
            "error": "ledger-path-contract",
            "contract": preflight,
        }
    entry_root = pls.ensure_ledger_layout(ledger_dir)
    contract = pls.verify_ledger_path_contract(root, ledger_dir)
    if contract.get("verdict") != "ok":
        return {
            "verdict": "fail",
            "action": "record-refusal",
            "error": "ledger-at-rest-contract",
            "contract": contract,
        }
    proposed = build_refusal_entry(
        unit_id=unit_id,
        operation=operation,
        intended_body=intended_body,
        authority_state=authority_state,
        authority_reason=authority_reason,
        destination_policy_id=destination_policy_id,
        destination_policy_version=destination_policy_version,
    )
    existing = pls.load_entry(entry_root, proposed["entryId"])
    if existing is not None:
        return {
            "verdict": "ok",
            "action": "record-refusal",
            "idempotent": True,
            "entry": existing,
        }
    path = pls.save_entry(entry_root, proposed)
    ttl_seconds, max_size_bytes = pls.resolve_ledger_bounds(cfg)
    eviction = pls.enforce_ledger_bounds(
        ledger_dir,
        ttl_seconds=ttl_seconds,
        max_size_bytes=max_size_bytes,
    )
    still_present = pls.load_entry(entry_root, proposed["entryId"]) is not None
    outbox_event: dict[str, Any] | None = None
    if still_present:
        import planning_projection_ledger as ppl

        ledger = ppl.load_projection_ledger(root)
        outbox_event = ppl.append_projection_outbox_event(
            ledger,
            aggregate_id=proposed["unitId"],
            destination="refusal-ledger",
            idempotency_key=proposed["idempotencyKey"],
            delivery_status="delivered",
        )
        proposed["outboxEventId"] = outbox_event.get("eventId")
        pls.save_entry(entry_root, proposed)
        if projection_destination:
            ppl.append_projection_outbox_event(
                ledger,
                aggregate_id=proposed["unitId"],
                destination=projection_destination,
                idempotency_key=f"{proposed['idempotencyKey']}:projection",
                delivery_status="pending",
                last_error=authority_reason,
            )
        ppl.save_projection_ledger(root, ledger)
    return {
        "verdict": "ok",
        "action": "record-refusal",
        "idempotent": False,
        "entry": proposed if still_present else None,
        "path": str(path),
        "eviction": eviction,
        "evictedSelf": not still_present,
        "outboxEventId": proposed.get("outboxEventId") if still_present else None,
    }


def list_refusals(root: Path, cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    ledger_dir = pls.resolve_ledger_path(root, cfg)
    return pls.load_all_entries(pls.entries_dir(ledger_dir))


def verify_refusal_ledger_at_rest(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    ledger_dir = pls.resolve_ledger_path(root, cfg)
    contract = pls.verify_ledger_path_contract(root, ledger_dir)
    journal = pls.load_eviction_journal(ledger_dir)
    entries = pls.load_all_entries(pls.entries_dir(ledger_dir))
    verdict = "ok" if contract.get("verdict") == "ok" else "fail"
    return {
        "verdict": verdict,
        "action": "verify-refusal-ledger-at-rest",
        "contract": contract,
        "entryCount": len(entries),
        "evictionEventCount": len(journal.get("events") or []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planning refusal ledger (PRD 082 R26)")
    parser.add_argument("--root", type=Path, default=SCRIPT_DIR.parent)
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="Append a refusal entry (idempotent)")
    record.add_argument("--unit-id", required=True)
    record.add_argument("--operation", required=True)
    body = record.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="Intended body text")
    body.add_argument("--body-file", type=Path, help="Read intended body from file")
    record.add_argument("--authority-state", required=True)
    record.add_argument("--authority-reason", default=None)
    record.add_argument("--destination-policy-id", default=DEFAULT_DESTINATION_POLICY_ID)
    record.add_argument("--destination-policy-version", default=DEFAULT_DESTINATION_POLICY_VERSION)

    sub.add_parser("list", help="List refusal entries")
    sub.add_parser("verify", help="Verify at-rest ledger contract")

    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "record":
        if args.body_file is not None:
            intended_body = args.body_file.read_text(encoding="utf-8")
        else:
            intended_body = args.body or ""
        payload = record_refusal(
            root,
            unit_id=args.unit_id,
            operation=args.operation,
            intended_body=intended_body,
            authority_state=args.authority_state,
            authority_reason=args.authority_reason,
            destination_policy_id=args.destination_policy_id,
            destination_policy_version=args.destination_policy_version,
        )
    elif args.command == "list":
        payload = {"verdict": "ok", "entries": list_refusals(root)}
    else:
        payload = verify_refusal_ledger_at_rest(root)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("verdict") == "ok" else 20


if __name__ == "__main__":
    raise SystemExit(main())
