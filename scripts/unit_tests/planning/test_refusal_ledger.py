"""PRD 082 phase 6 — refusal ledger record and at-rest fixtures (R26) — Z,O,M,B,S,E."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_ledger_store as pls
import planning_refusal_ledger as prl


def _write_cfg(repo: Path, cfg: dict[str, Any]) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _seed_gitignore(repo: Path, *patterns: str) -> None:
    gi = repo / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    merged = sorted({line.strip() for line in (existing.splitlines() + list(patterns)) if line.strip()})
    gi.write_text("\n".join(merged) + "\n", encoding="utf-8")


def _ledger_cfg(
    *,
    path: str = ".cursor/sw-refusal-ledger",
    ttl_seconds: int = 2_592_000,
    max_size_bytes: int = 52_428_800,
) -> dict[str, Any]:
    return {
        "planning": {
            "refusalLedger": {
                "path": path,
                "ttlSeconds": ttl_seconds,
                "maxSizeBytes": max_size_bytes,
            }
        }
    }


class TestIdempotency:
    def test_idempotency_key_stable_across_repeated_refusals(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _ledger_cfg())
        body = "# intended mutation body"
        first = prl.record_refusal(
            tmp_git_repo,
            unit_id="unit-082",
            operation="put",
            intended_body=body,
            authority_state="read-only",
            authority_reason="offline-with-cache",
        )
        second = prl.record_refusal(
            tmp_git_repo,
            unit_id="unit-082",
            operation="put",
            intended_body=body,
            authority_state="read-only",
            authority_reason="offline-with-cache",
        )
        assert first["verdict"] == "ok"
        assert second["verdict"] == "ok"
        assert first["idempotent"] is False
        assert second["idempotent"] is True
        assert first["entry"]["idempotencyKey"] == second["entry"]["idempotencyKey"]
        assert len(prl.list_refusals(tmp_git_repo)) == 1

    def test_idempotency_key_changes_when_body_changes(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _ledger_cfg())
        first = prl.record_refusal(
            tmp_git_repo,
            unit_id="unit-082",
            operation="put",
            intended_body="body-a",
            authority_state="blocked",
            authority_reason="store-unavailable",
        )
        second = prl.record_refusal(
            tmp_git_repo,
            unit_id="unit-082",
            operation="put",
            intended_body="body-b",
            authority_state="blocked",
            authority_reason="store-unavailable",
        )
        assert first["entry"]["idempotencyKey"] != second["entry"]["idempotencyKey"]
        assert len(prl.list_refusals(tmp_git_repo)) == 2


class TestAtRestContract:
    def test_permissions_enforced_for_loose_directory_mode(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _ledger_cfg())
        ledger_dir = pls.resolve_ledger_path(tmp_git_repo, _ledger_cfg())
        pls.ensure_ledger_layout(ledger_dir)
        os.chmod(ledger_dir, 0o755)
        contract = pls.verify_ledger_path_contract(tmp_git_repo, ledger_dir)
        assert contract["verdict"] == "fail"
        assert "ledger directory must be mode" in " ".join(contract.get("warnings") or [])

    def test_symlinked_ledger_path_rejected(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        real = tmp_git_repo / ".cursor" / "real-ledger"
        real.mkdir(parents=True)
        link = tmp_git_repo / ".cursor" / "linked-ledger"
        link.symlink_to(real, target_is_directory=True)
        _write_cfg(tmp_git_repo, _ledger_cfg(path=".cursor/linked-ledger"))
        contract = pls.verify_ledger_path_contract(tmp_git_repo, link)
        assert contract["verdict"] == "fail"
        assert "symlink-rejected" in contract.get("warnings", [])

    def test_non_gitignored_ledger_path_reported_as_failure(self, tmp_git_repo: Path) -> None:
        _write_cfg(tmp_git_repo, _ledger_cfg(path="tracked-ledger"))
        ledger_dir = pls.resolve_ledger_path(tmp_git_repo, _ledger_cfg(path="tracked-ledger"))
        contract = pls.verify_ledger_path_contract(tmp_git_repo, ledger_dir)
        assert contract["verdict"] == "fail"
        assert "ledger-path-not-gitignored" in contract.get("warnings", [])
        payload = prl.verify_refusal_ledger_at_rest(tmp_git_repo)
        assert payload["verdict"] == "fail"


class TestEvictionJournal:
    def test_ttl_eviction_is_journaled(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _ledger_cfg(ttl_seconds=3600, max_size_bytes=52_428_800))
        ledger_dir = pls.resolve_ledger_path(tmp_git_repo, _ledger_cfg(ttl_seconds=3600))
        entry_root = pls.ensure_ledger_layout(ledger_dir)
        old_time = (datetime.now(UTC) - timedelta(days=40)).replace(microsecond=0)
        old_time_text = old_time.isoformat().replace("+00:00", "Z")
        stale = prl.build_refusal_entry(
            unit_id="stale-unit",
            operation="put",
            intended_body="stale body",
            authority_state="read-only",
            authority_reason="offline-with-cache",
            recorded_at=old_time_text,
        )
        pls.save_entry(entry_root, stale)
        fresh = prl.record_refusal(
            tmp_git_repo,
            unit_id="fresh-unit",
            operation="put",
            intended_body="fresh body",
            authority_state="read-only",
            authority_reason="offline-with-cache",
        )
        assert fresh["verdict"] == "ok"
        journal = pls.load_eviction_journal(ledger_dir)
        events = journal.get("events") or []
        assert events
        assert any(event.get("entryId") == stale["entryId"] for event in events)
        assert prl.list_refusals(tmp_git_repo)


class TestEntryShape:
    def test_entry_carries_required_fields_and_redacted_body(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _ledger_cfg())
        result = prl.record_refusal(
            tmp_git_repo,
            unit_id="unit-shape",
            operation="freeze",
            intended_body="public planning body",
            authority_state="blocked",
            authority_reason="store-unavailable",
            destination_policy_id="shipwright.memory.redaction",
            destination_policy_version="1",
        )
        entry = result["entry"]
        for field in (
            "unitId",
            "operation",
            "contentHash",
            "recordedAt",
            "idempotencyKey",
            "authorityState",
            "authorityReason",
            "destinationPolicyId",
            "destinationPolicyVersion",
            "redactedBody",
            "digest",
        ):
            assert field in entry
        assert entry["destinationPolicyId"] == "shipwright.memory.redaction"
        assert entry["destinationPolicyVersion"] == "1"
        assert "replay" not in dir(prl)
