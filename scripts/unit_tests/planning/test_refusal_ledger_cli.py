"""PRD 082 phase 7 — refusal ledger CLI fixtures (R26) — O,M,I,S,E."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import cleanup_lib
import planning_ledger_store as pls
import planning_refusal_ledger as prl
import planning_refusal_ledger_cli as prlc


def _write_cfg(repo: Path, cfg: dict) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _seed_gitignore(repo: Path, *patterns: str) -> None:
    gi = repo / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    merged = sorted({line.strip() for line in (existing.splitlines() + list(patterns)) if line.strip()})
    gi.write_text("\n".join(merged) + "\n", encoding="utf-8")


def _ledger_cfg() -> dict:
    return {
        "planning": {
            "refusalLedger": {
                "path": ".cursor/sw-refusal-ledger",
                "ttlSeconds": 2_592_000,
                "maxSizeBytes": 52_428_800,
            }
        }
    }


def _record(repo: Path, *, unit_id: str, body: str) -> dict:
    return prl.record_refusal(
        repo,
        unit_id=unit_id,
        operation="put",
        intended_body=body,
        authority_state="read-only",
        authority_reason="offline-with-cache",
    )


class TestListAndShow:
    def test_list_and_show_redact_at_recorded_destination_tier(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _ledger_cfg())
        secret_body = "api_key=ghp_deadbeefdeadbeefdeadbeefdeadbeefdead"
        recorded = _record(tmp_git_repo, unit_id="unit-list", body=secret_body)
        entry_id = recorded["entry"]["entryId"]
        listed = prlc.list_entries_display(tmp_git_repo)
        assert len(listed) == 1
        assert "displayBody" in listed[0]
        assert "ghp_deadbeef" not in listed[0]["displayBody"]
        assert listed[0]["displayDestinationTier"] == "external"
        shown = prlc.show_entry(tmp_git_repo, entry_id)
        assert shown["verdict"] == "ok"
        assert "ghp_deadbeef" not in shown["entry"]["displayBody"]


class TestExport:
    def test_export_is_runnable_and_rerun_detectable(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _ledger_cfg())
        _record(tmp_git_repo, unit_id="unit-export", body="export body")
        first = prlc.export_entries(tmp_git_repo)
        second = prlc.export_entries(tmp_git_repo)
        assert first["verdict"] == "ok"
        assert first["exportIdempotencyKey"] == second["exportIdempotencyKey"]
        assert first["replayRefusedWrites"] is False
        script = first["script"]
        assert " record " in script
        assert "planning_refusal_ledger" in script
        assert "idempotencyKey:" in script
        assert "replay" not in script.lower() or "does not replay" in script.lower()
        out_path = tmp_git_repo / "export.sh"
        out_path.write_text(script, encoding="utf-8")
        out_path.chmod(0o700)
        before = len(prl.list_refusals(tmp_git_repo))
        proc = subprocess.run(["bash", str(out_path)], cwd=tmp_git_repo, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        after = len(prl.list_refusals(tmp_git_repo))
        assert before == after == 1


class TestPurge:
    def test_purge_removes_entries_and_journals(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _ledger_cfg())
        recorded = _record(tmp_git_repo, unit_id="unit-purge", body="purge me")
        entry_id = recorded["entry"]["entryId"]
        ledger_dir = pls.resolve_ledger_path(tmp_git_repo, _ledger_cfg())
        result = prlc.purge_entries(tmp_git_repo, entry_ids=[entry_id])
        assert result["verdict"] == "ok"
        assert result["remaining"] == 0
        journal = pls.load_eviction_journal(ledger_dir)
        events = journal.get("events") or []
        assert any(event.get("entryId") == entry_id and event.get("reason") == "purge" for event in events)

    def test_cleanup_enumerates_and_purges_after_confirm(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _ledger_cfg())
        recorded = _record(tmp_git_repo, unit_id="unit-cleanup", body="cleanup body")
        entry_id = recorded["entry"]["entryId"]
        report = cleanup_lib.enumerate_cleanup(tmp_git_repo)
        candidates = [item for item in report.would_remove if item.kind == "refusal-ledger-entry"]
        assert any(item.name == entry_id for item in candidates)
        assert any("human decision" in note for note in report.notes)
        applied = cleanup_lib.apply_report(tmp_git_repo, report)
        assert any(item.name == entry_id for item in applied.removed)
        assert len(prl.list_refusals(tmp_git_repo)) == 0
