"""PRD 325 phase 2 — closeout prefers run-scoped state (R3)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import deliver_closeout as dc
from wave_json_io import write_json
from wave_run_paths import state_path

SHA = "a" * 40
RUN_ID = "deliver-0ab2c3b752e04ea2b580283bacfb9b91"
LEGACY_RUN_ID = "sw-deliver-325-closeout-run-scoped"
PRD_RUN_SCOPED = "prd-325-deliver-finalize-consumer-resilience"
PRD_LEGACY = "prd-070-automated-delivery-closeout"


def _write_legacy_slug_state(tmp_path: Path, slug: str, state: dict) -> None:
    cursor = tmp_path / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / f"sw-deliver-state.{slug}.json").write_text(json.dumps(state), encoding="utf-8")


def _write_run_scoped_state(tmp_path: Path, run_id: str, state: dict) -> Path:
    path = state_path(tmp_path, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, state)
    return path


def _pending_merge_state(
    *,
    slug: str = "closeout-run-scoped",
    prd_number: str = "325",
    prd_unit: str = PRD_RUN_SCOPED,
    run_id: str | None = RUN_ID,
) -> dict:
    prd_slug = prd_unit.split("-", 2)[-1] if prd_unit.startswith("prd-") else slug
    state = {
        "prd_number": prd_number,
        "prd_slug": prd_slug,
        "target": {"branch": f"feat/{slug}", "slug": slug},
        "completion": {"status": "completed-pending-merge"},
        "source_task_list": f"docs/prds/{prd_number}-{prd_slug}/tasks.md",
        "terminalPr": {"number": 42},
    }
    if run_id:
        state["runId"] = run_id
    return state


def test_deliver_run_id_from_state_prefers_explicit_run_id() -> None:
    state = _pending_merge_state(run_id=RUN_ID)
    assert dc.deliver_run_id_from_state(state) == RUN_ID


def test_run_scoped_state_wins_over_legacy_slug(tmp_path: Path) -> None:
    slug = "closeout-run-scoped"
    run_state = _pending_merge_state(slug=slug, prd_unit=PRD_RUN_SCOPED)
    legacy_state = _pending_merge_state(slug=slug, prd_number="070", prd_unit=PRD_LEGACY, run_id=None)
    _write_run_scoped_state(tmp_path, RUN_ID, run_state)
    _write_legacy_slug_state(tmp_path, slug, legacy_state)

    state, path, slug_out, meta = dc.resolve_state_by_run_id(tmp_path, RUN_ID)
    assert meta == {}
    assert state is not None
    assert state.get("stateSource") == "run-scoped"
    assert path == state_path(tmp_path, RUN_ID)
    assert slug_out == slug
    from inflight_signal import prd_unit_id_from_state

    assert prd_unit_id_from_state(state) == PRD_RUN_SCOPED


def test_legacy_fallback_when_no_run_scoped(tmp_path: Path) -> None:
    slug = "automated-delivery-closeout"
    legacy_state = {
        "prd_number": "070",
        "target": {"branch": f"feat/{slug}", "slug": slug},
        "completion": {"status": "completed-pending-merge"},
        "terminalPr": {"number": 9},
    }
    _write_legacy_slug_state(tmp_path, slug, legacy_state)
    run_id = dc.deliver_run_id_from_state(legacy_state)
    assert run_id == "sw-deliver-070-automated-delivery-closeout"

    state, _path, _slug, meta = dc.resolve_state_by_run_id(tmp_path, run_id)
    assert meta == {}
    assert state is not None
    assert state.get("stateSource") == "legacy"


def test_ambiguous_run_scoped_matches_fail_closed(tmp_path: Path) -> None:
    run_a = "deliver-duplicate-a"
    run_b = "deliver-duplicate-b"
    shared = _pending_merge_state(run_id=run_a)
    _write_run_scoped_state(tmp_path, run_a, shared)
    dup = dict(shared)
    dup["runId"] = run_a
    _write_run_scoped_state(tmp_path, run_b, dup)

    state, _path, _slug, meta = dc.resolve_state_by_run_id(tmp_path, run_a)
    assert state is None
    assert meta.get("error") == "run-id-ambiguous"
    assert len(meta.get("statePaths") or []) == 2


def test_corrupt_run_scoped_falls_back_to_legacy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    slug = "closeout-run-scoped"
    run_path = _write_run_scoped_state(tmp_path, RUN_ID, _pending_merge_state(slug=slug))
    run_path.write_text("{not-json", encoding="utf-8")
    legacy_state = _pending_merge_state(
        slug=slug,
        prd_number="070",
        prd_unit=PRD_LEGACY,
        run_id=RUN_ID,
    )
    _write_legacy_slug_state(tmp_path, slug, legacy_state)

    state, _path, _slug, meta = dc.resolve_state_by_run_id(tmp_path, RUN_ID)
    assert meta == {}
    assert state is not None
    assert state.get("stateSource") == "legacy"
    from inflight_signal import prd_unit_id_from_state

    assert prd_unit_id_from_state(state) == PRD_LEGACY
    captured = capsys.readouterr()
    assert "falling back to legacy" in captured.err


def test_short_circuit_requires_case_normalized_merge_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _pending_merge_state()
    prd_unit = PRD_RUN_SCOPED
    upper_sha = SHA.upper()
    dc.write_close_marker(tmp_path, prd_unit, upper_sha, audit={"verdict": "ready"})
    monkeypatch.setattr(
        "planning_store.audit_closure_completeness",
        lambda *_a, **_k: {"verdict": "ready"},
    )
    short = dc.short_circuit_closeout(tmp_path, {}, prd_unit, SHA, state=state)
    assert short is not None
    assert short["verdict"] == "ready"
    assert short["mergeSha"] == SHA.lower()


def test_self_wake_uses_run_scoped_prd_unit_over_legacy_shadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = "closeout-run-scoped"
    run_state = _pending_merge_state(slug=slug)
    legacy_state = _pending_merge_state(slug=slug, prd_number="070", prd_unit=PRD_LEGACY, run_id=None)
    _write_run_scoped_state(tmp_path, RUN_ID, run_state)
    _write_legacy_slug_state(tmp_path, slug, legacy_state)

    def probe(_root, _state):
        return {"merged": True, "mergeCommit": SHA, "prNumber": 42}

    close_calls: list[str] = []

    def fake_run_closeout(root, *, prd_unit_id, merge_sha, pr_number=None, dry_run=False, state=None):
        close_calls.append(prd_unit_id)
        return {
            "verdict": "ready",
            "action": "run-closeout",
            "closure": {"closureAudit": {"verdict": "ready"}},
        }

    monkeypatch.setattr(dc, "run_closeout", fake_run_closeout)

    result = dc.self_wake_poll_once(tmp_path, RUN_ID, merge_probe=probe)
    assert result["verdict"] == "ready"
    assert close_calls == [PRD_RUN_SCOPED]
    assert dc.deliver_run_id_from_state(run_state) == RUN_ID
