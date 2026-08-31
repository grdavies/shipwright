"""PRD 337 R17–R20 — retro gap routing, redaction, and destination guards."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import planning_gap_capture as pgc
import retro_candidates as rc
import retro_gap_capture as rgc


def _write_cfg(repo: Path, *, enabled: bool = True, cap: int = 3) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "planning": {"store": {"backend": "in-repo-public"}},
                "retrospective": {"gapCapture": {"enabled": enabled, "maxCapturesPerRun": cap}},
            }
        ),
        encoding="utf-8",
    )


def _seed_planning(repo: Path) -> None:
    (repo / "docs" / "planning" / "gap").mkdir(parents=True, exist_ok=True)


def _seed_meta_schema(repo: Path) -> None:
    src = ROOT / "core" / "sw-reference" / "meta-inbox-draft.schema.json"
    dest = repo / "core" / "sw-reference"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest / "meta-inbox-draft.schema.json")


def _seed_plugin_self_repo(repo: Path) -> None:
    (repo / "version.txt").write_text("9.9.9\n", encoding="utf-8")
    (repo / "scripts" / "check-gate.py").parent.mkdir(parents=True, exist_ok=True)
    (repo / "scripts" / "check-gate.py").write_text("# fixture\n", encoding="utf-8")
    (repo / "core" / "sw-reference").mkdir(parents=True, exist_ok=True)


def _retro_payload(**items: dict) -> dict:
    default_items = [
        {
            "itemId": "product-pain",
            "kind": "painful",
            "summary": "Checkout API returned 500 for user@corp.example.com",
            "relatedFiles": ["src/api/checkout.ts"],
            "category": "product-code",
        }
    ]
    if items:
        default_items = list(items.values())
    return {"runId": "retro-337", "items": default_items}


def test_consumer_auto_materializes_product_gap_without_confirm(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R17 — enabled capture auto-materializes digest-bound product gaps."""
    _write_cfg(tmp_git_repo)
    _seed_planning(tmp_git_repo)
    monkeypatch.setattr(rc, "resolve_repo_posture", lambda _root: rc.POSTURE_CONSUMER)
    calls: list[str] = []

    def fake_put(root: Path, unit_id: str, body_path_rel: str, content: str) -> None:
        calls.append(unit_id)
        path = root / body_path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(pgc, "store_put_gap", fake_put)
    retro = _retro_payload()
    item = retro["items"][0]
    digest = pgc.retro_item_digest(item)
    out = rgc.capture_retro_gaps(tmp_git_repo, retro)
    assert out["verdict"] == "pass"
    assert len(out["materialized"]) == 1
    entry = out["materialized"][0]
    assert entry["destination"] == rgc.DESTINATION_CONSUMER_INBOX
    assert entry["digest"] == digest
    assert entry["action"] == "auto-materialized"
    assert len(calls) == 1


def test_tampered_digest_rejected(tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R17 — digest mismatch fails closed before materialization."""
    _write_cfg(tmp_git_repo)
    _seed_planning(tmp_git_repo)
    monkeypatch.setattr(rc, "resolve_repo_posture", lambda _root: rc.POSTURE_CONSUMER)
    retro = _retro_payload()
    item_id = retro["items"][0]["itemId"]
    with pytest.raises(SystemExit):
        rgc.capture_retro_gaps(
            tmp_git_repo,
            retro,
            digest_by_item_id={item_id: "deadbeef" * 4},
        )


def test_redaction_strips_email_from_materialized_context(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_cfg(tmp_git_repo)
    _seed_planning(tmp_git_repo)
    monkeypatch.setattr(rc, "resolve_repo_posture", lambda _root: rc.POSTURE_CONSUMER)
    captured: list[str] = []

    def fake_put(root: Path, unit_id: str, body_path_rel: str, content: str) -> None:
        captured.append(content)
        path = root / body_path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(pgc, "store_put_gap", fake_put)
    out = rgc.capture_retro_gaps(tmp_git_repo, _retro_payload())
    assert out["verdict"] == "pass"
    assert captured
    assert "user@corp.example.com" not in captured[0]
    assert "REDACTED" in captured[0]


def test_consumer_posture_prioritizes_product_learning_candidates() -> None:
    """R18 — consumer posture excludes plugin friction from learning candidates."""
    items = [
        {"itemId": "p1", "kind": "painful", "summary": "ship loop flake", "relatedFiles": ["scripts/wave.py"]},
        {"itemId": "p2", "kind": "painful", "summary": "api bug", "relatedFiles": ["src/app.ts"]},
        {"itemId": "w1", "kind": "well", "summary": "tests fast"},
    ]
    out = rc.select_learning_candidates(items, posture=rc.POSTURE_CONSUMER)
    assert len(out["excluded"]) == 1
    assert out["excluded"][0]["itemId"] == "p1"
    assert out["candidates"][0]["itemId"] == "p2"


def test_plugin_self_posture_retains_plugin_pain_focus() -> None:
    """R18 — plugin-self posture keeps plugin/process pain in candidate set."""
    items = [
        {"itemId": "p1", "kind": "painful", "summary": "ship loop flake", "relatedFiles": ["scripts/wave.py"]},
        {"itemId": "p2", "kind": "painful", "summary": "api bug", "relatedFiles": ["src/app.ts"]},
    ]
    out = rc.select_learning_candidates(items, posture=rc.POSTURE_PLUGIN_SELF)
    assert out["excluded"] == []
    assert out["candidates"][0]["itemId"] == "p1"
    assert out["candidates"][0]["learningScope"] == rc.FRICTION_PLUGIN_SELF


def test_consumer_rejects_plugin_friction_gap_capture(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R19 — consumer planning store refuses plugin-self friction gaps."""
    _write_cfg(tmp_git_repo)
    _seed_planning(tmp_git_repo)
    monkeypatch.setattr(rc, "resolve_repo_posture", lambda _root: rc.POSTURE_CONSUMER)
    retro = {
        "runId": "retro-consumer",
        "items": [
            {
                "itemId": "plugin-pain",
                "kind": "painful",
                "summary": "Deliver loop watchdog",
                "relatedFiles": ["scripts/wave_deliver_loop.py"],
                "gapClass": "plugin-self",
            }
        ],
    }
    out = rgc.capture_retro_gaps(tmp_git_repo, retro)
    assert out["verdict"] == "pass"
    assert out["materialized"] == []
    assert out["rejected"][0]["reason"] == "consumer-plugin-friction-rejected"


def test_plugin_self_routes_to_meta_shipwright(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R20 — plugin-self friction forks to meta-shipwright capture."""
    _write_cfg(tmp_git_repo)
    _seed_planning(tmp_git_repo)
    _seed_meta_schema(tmp_git_repo)
    _seed_plugin_self_repo(tmp_git_repo)
    monkeypatch.setattr(rc, "resolve_repo_posture", lambda _root: rc.POSTURE_PLUGIN_SELF)
    calls: list[str] = []

    def fake_put(root: Path, unit_id: str, body_path_rel: str, content: str) -> None:
        calls.append(content)
        path = root / body_path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(pgc, "store_put_gap", fake_put)
    retro = {
        "runId": "retro-meta",
        "items": [
            {
                "itemId": "plugin-pain",
                "kind": "painful",
                "summary": "Orchestrator dispatch flake",
                "relatedFiles": ["scripts/wave_deliver_loop.py"],
                "gapClass": "plugin-self",
            }
        ],
    }
    out = rgc.capture_retro_gaps(tmp_git_repo, retro)
    assert out["verdict"] == "pass"
    assert len(out["materialized"]) == 1
    entry = out["materialized"][0]
    assert entry["destination"] == rgc.DESTINATION_META_SHIPWRIGHT
    assert entry["gapClass"] == "plugin-self"
    inbox = tmp_git_repo / ".cursor" / "sw-meta-inbox" / "retro:retro-meta:plugin-pain.json"
    assert inbox.is_file()
    draft = json.loads(inbox.read_text(encoding="utf-8"))
    assert draft["destination"] == "meta-shipwright"
    assert draft["status"] == "materialized"
    assert "meta-shipwright" in (calls[0] if calls else "")


def test_product_gap_does_not_land_in_meta_inbox(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R20 — product gaps must not cross into meta-shipwright inbox."""
    _write_cfg(tmp_git_repo)
    _seed_planning(tmp_git_repo)
    monkeypatch.setattr(rc, "resolve_repo_posture", lambda _root: rc.POSTURE_CONSUMER)

    def fake_put(root: Path, unit_id: str, body_path_rel: str, content: str) -> None:
        path = root / body_path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(pgc, "store_put_gap", fake_put)
    out = rgc.capture_retro_gaps(tmp_git_repo, _retro_payload())
    assert out["materialized"][0]["destination"] == rgc.DESTINATION_CONSUMER_INBOX
    assert not list((tmp_git_repo / ".cursor" / "sw-meta-inbox").glob("*.json"))


def test_gap_capture_disabled_skips(tmp_git_repo: Path) -> None:
    _write_cfg(tmp_git_repo, enabled=False)
    out = rgc.capture_retro_gaps(tmp_git_repo, _retro_payload())
    assert out["verdict"] == "skipped"
