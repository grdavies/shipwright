"""PRD 077 — compiled truth + append-only timeline for in-repo memory (portfolio item D)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_switch as ms  # noqa: E402
from memory_provider_catalog import load_catalog  # noqa: E402


def _load_irms():
    path = SCRIPTS / "in-repo-memory-search.py"
    spec = importlib.util.spec_from_file_location("in_repo_memory_search", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


irms = _load_irms()

# Portfolio item D scope: enhancement of in-repo only (depends on PRD 071).
PRD_077_SCOPE = {
    "provider_id": "in-repo",
    "depends_on": "071",
    "does_not_implement": (
        "mempalace",
        "basic-memory",
        "obsidian",
        "recallium",
        "agents.md",
        "brain",
        "brain-md",
    ),
}


def _ns(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _store_mem(tmp_path: Path) -> Path:
    store = tmp_path / "sw-memory"
    (store / "memories").mkdir(parents=True)
    (store / "rules").mkdir(parents=True)
    return store


def test_portfolio_item_d_scope_invariants(repo_root: Path) -> None:
    """R2, R3 — PRD 077 is in-repo enhancement only; no second provider."""
    catalog = load_catalog(repo_root)
    providers = catalog.get("providers") or {}
    assert PRD_077_SCOPE["provider_id"] in providers
    for forbidden in ("brain", "brain-md", "brain.md"):
        assert forbidden not in providers
    notes = str(providers["in-repo"].get("hookTransport", {}).get("notes") or "")
    assert "truth" in notes.lower() or "timeline" in notes.lower()
    # No brain/ SoT tree introduced by this work.
    assert not (repo_root / "brain").is_dir()
    assert not (repo_root / "BRAIN.md").is_file()


def test_no_mindmux_brain_interop_surface(repo_root: Path) -> None:
    """R25 — no bidirectional MindMux brain/ interop surface in v1."""
    search = (repo_root / "scripts" / "in-repo-memory-search.py").read_text(encoding="utf-8")
    adapter = (repo_root / "core" / "providers" / "in-repo.md").read_text(encoding="utf-8")
    # Script must not implement interop; adapter must document the non-goal.
    assert "mindmux" not in search.lower()
    assert "No MindMux" in adapter or "no MindMux" in adapter or "no bidirectional MindMux" in adapter
    assert "brain/" in adapter
    assert "interop" in adapter.lower()


def test_parse_legacy_body_as_truth() -> None:
    """R4, R5 — legacy body-only files parse as compiled truth."""
    sections = irms.parse_body_sections("Always run the gate.\n")
    assert sections["legacy"] is True
    assert sections["compiled_truth"] == "Always run the gate."
    assert sections["timeline"] == []


def test_parse_and_render_truth_timeline_round_trip() -> None:
    body = irms.render_body_sections(
        "Current understanding",
        [{"kind": "created", "at": "2026-07-22T12:00:00Z", "summary": "Initial memory created"}],
        "# Citations\n\n- docs/example.md",
    )
    sections = irms.parse_body_sections(body)
    assert sections["legacy"] is False
    assert sections["compiled_truth"] == "Current understanding"
    assert len(sections["timeline"]) == 1
    assert sections["timeline"][0]["kind"] == "created"
    assert "Citations" in sections["rest"]


def test_rules_do_not_require_timeline(tmp_path: Path) -> None:
    """R6, R7 — rules stay under rules/ without timeline sections."""
    store = _store_mem(tmp_path)
    path = irms.write_memory_record(store, {
        "id": "mock-realism",
        "category": "rule",
        "fields": {"category": "rule", "id": "mock-realism"},
        "body": "Mocks must be realistic.\n",
    })
    assert path == store / "rules" / "mock-realism.md"
    text = path.read_text(encoding="utf-8")
    assert "## Compiled truth" not in text
    assert "## Timeline" not in text
    assert not (store / "brain").exists()


def test_store_initializes_truth_and_created_timeline(tmp_path: Path) -> None:
    """R9 — store seeds compiled truth + kind: created."""
    store = _store_mem(tmp_path)
    rc = irms.cmd_store(_ns(
        store=str(store),
        id="learn-1",
        category="learning",
        content="Use check-gate.py for CI readiness.",
        summary="",
        tags="gate",
        scope="project",
    ))
    assert rc == 0
    record = irms.read_memory_record(store / "memories" / "learn-1.md")
    assert irms.compiled_truth_of(record) == "Use check-gate.py for CI readiness."
    timeline = irms.timeline_of(record)
    assert len(timeline) == 1
    assert timeline[0]["kind"] == "created"


def test_update_truth_atomic_and_append_only(tmp_path: Path) -> None:
    """R8, R12 — update-truth rewrites truth and appends exactly one entry."""
    store = _store_mem(tmp_path)
    irms.cmd_store(_ns(
        store=str(store),
        id="dec-1",
        category="decision",
        content="Prefer A.",
        summary="",
        tags="",
        scope="project",
    ))
    before = irms.timeline_of(irms.read_memory_record(store / "memories" / "dec-1.md"))
    rc = irms.cmd_update_truth(_ns(
        store=str(store),
        id="dec-1",
        truth="Prefer B after review.",
        summary="Review selected B",
    ))
    assert rc == 0
    after = irms.read_memory_record(store / "memories" / "dec-1.md")
    timeline = irms.timeline_of(after)
    assert irms.compiled_truth_of(after) == "Prefer B after review."
    assert len(timeline) == len(before) + 1
    assert timeline[-1]["kind"] == "truth-updated"
    assert timeline[-1]["summary"] == "Review selected B"
    # Prior entries preserved (append-only).
    assert timeline[0]["kind"] == before[0]["kind"]
    assert timeline[0]["summary"] == before[0]["summary"]


def test_atomic_write_uses_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R8 — writes go through temp file + os.replace."""
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def tracking_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        calls.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(irms.os, "replace", tracking_replace)
    target = tmp_path / "memories" / "x.md"
    irms.atomic_write_text(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"
    assert calls
    assert calls[0][1] == str(target)
    assert calls[0][0].endswith(".tmp")


def test_modify_appends_timeline_evidence(tmp_path: Path) -> None:
    """R10, R11 — truth-bearing modify and inactive leave timeline evidence."""
    store = _store_mem(tmp_path)
    irms.cmd_store(_ns(
        store=str(store),
        id="mod-1",
        category="learning",
        content="First understanding.",
        summary="",
        tags="",
        scope="project",
    ))
    irms.cmd_modify(_ns(
        store=str(store),
        id="mod-1",
        content="Second understanding.",
        summary="Revised after feedback",
        inactive=None,
    ))
    record = irms.read_memory_record(store / "memories" / "mod-1.md")
    kinds = [e["kind"] for e in irms.timeline_of(record)]
    assert kinds == ["created", "modified"]
    assert irms.compiled_truth_of(record) == "Second understanding."

    irms.cmd_modify(_ns(
        store=str(store),
        id="mod-1",
        content=None,
        summary="Parked",
        inactive="true",
    ))
    record = irms.read_memory_record(store / "memories" / "mod-1.md")
    kinds = [e["kind"] for e in irms.timeline_of(record)]
    assert kinds == ["created", "modified", "inactivated"]
    assert record["fields"].get("inactive") is True

    irms.cmd_modify(_ns(
        store=str(store),
        id="mod-1",
        content=None,
        summary="Back",
        inactive="false",
    ))
    record = irms.read_memory_record(store / "memories" / "mod-1.md")
    kinds = [e["kind"] for e in irms.timeline_of(record)]
    assert kinds[-1] == "reactivated"
    assert record["fields"].get("inactive") is False


def test_update_truth_redacts_secrets(tmp_path: Path) -> None:
    """R14 — update-truth payloads pass through redaction."""
    store = _store_mem(tmp_path)
    irms.cmd_store(_ns(
        store=str(store),
        id="sec-1",
        category="debug",
        content="Clean note.",
        summary="",
        tags="",
        scope="project",
    ))
    secret = "token=abcdefghijklmnopqrstuvwxyz12"
    rc = irms.cmd_update_truth(_ns(
        store=str(store),
        id="sec-1",
        truth=f"Leak: {secret}",
        summary="Should redact",
    ))
    assert rc == 0
    text = (store / "memories" / "sec-1.md").read_text(encoding="utf-8")
    assert secret not in text
    assert "REDACTED" in text


def test_search_prefers_compiled_truth_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """R15 — search summaries prefer compiled truth."""
    store = _store_mem(tmp_path)
    irms.cmd_store(_ns(
        store=str(store),
        id="sum-1",
        category="learning",
        content="UniqueTruthMarker for summaries.",
        summary="",
        tags="",
        scope="project",
    ))
    capsys.readouterr()
    irms.cmd_update_truth(_ns(
        store=str(store),
        id="sum-1",
        truth="UpdatedTruthMarker is current.",
        summary="refresh",
    ))
    capsys.readouterr()
    rc = irms.cmd_search(_ns(
        store=str(store),
        query="UpdatedTruthMarker",
        category="",
        tag="",
        file_glob="",
        include_excluded=False,
    ))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    hit = next(r for r in payload["results"] if r["id"] == "sum-1")
    assert "UpdatedTruthMarker" in hit["summary"]


def test_legacy_body_searchable_without_migration(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """R5, R20 — legacy files remain readable/searchable without bulk rewrite."""
    store = _store_mem(tmp_path)
    legacy = store / "memories" / "legacy-1.md"
    legacy.write_text(
        "---\ncategory: learning\nid: legacy-1\ncreatedAt: 2026-01-01T00:00:00Z\n---\n"
        "LegacyBodyMarker stays searchable.\n",
        encoding="utf-8",
    )
    rc = irms.cmd_search(_ns(
        store=str(store),
        query="LegacyBodyMarker",
        category="",
        tag="",
        file_glob="",
        include_excluded=False,
    ))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(r["id"] == "legacy-1" for r in payload["results"])
    # File not rewritten merely by search.
    assert "## Timeline" not in legacy.read_text(encoding="utf-8")


def test_expand_returns_truth_timeline_and_rest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """R16 — expand includes truth, timeline, and citations."""
    store = _store_mem(tmp_path)
    body = irms.render_body_sections(
        "Truth line",
        [{"kind": "created", "at": "2026-07-22T12:00:00Z", "summary": "Initial memory created"}],
        "# Citations\n\n- docs/a.md",
    )
    irms.write_memory_record(store, {
        "id": "exp-1",
        "category": "research",
        "fields": {"category": "research", "id": "exp-1", "createdAt": "2026-07-22T12:00:00Z"},
        "body": body,
    })
    rc = irms.cmd_expand(_ns(store=str(store), ids="exp-1"))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    item = payload["expanded"][0]
    assert item["found"] is True
    assert item["compiledTruth"] == "Truth line"
    assert item["timeline"][0]["kind"] == "created"
    assert "Citations" in item["rest"]


def test_maintain_derived_truth_aware(tmp_path: Path) -> None:
    """R17 — index/log prefer compiled-truth titles; log does not replace timelines."""
    store = _store_mem(tmp_path)
    irms.cmd_store(_ns(
        store=str(store),
        id="der-1",
        category="decision",
        content="DerivedTitleMarker.",
        summary="",
        tags="",
        scope="project",
    ))
    result = irms.maintain_derived(store)
    index = Path(result["index"]).read_text(encoding="utf-8")
    log = Path(result["log"]).read_text(encoding="utf-8")
    assert "DerivedTitleMarker" in index
    assert "DerivedTitleMarker" in log
    mem = (store / "memories" / "der-1.md").read_text(encoding="utf-8")
    assert "## Timeline" in mem
    assert mem.count("`created`") == 1


def test_jsonl_round_trip_preserves_truth_timeline(tmp_path: Path) -> None:
    """R18 — JSONL export/import preserves truth+timeline."""
    store = _store_mem(tmp_path)
    irms.cmd_store(_ns(
        store=str(store),
        id="rt-1",
        category="learning",
        content="Original.",
        summary="",
        tags="",
        scope="project",
    ))
    irms.cmd_update_truth(_ns(
        store=str(store),
        id="rt-1",
        truth="RoundTripTruth.",
        summary="updated",
    ))
    export_path = tmp_path / "export.jsonl"
    assert irms.cmd_export(_ns(store=str(store), format="jsonl", out=str(export_path))) == 0
    line = json.loads(export_path.read_text(encoding="utf-8").splitlines()[0])
    assert line["compiledTruth"] == "RoundTripTruth."
    assert any(e["kind"] == "truth-updated" for e in line["timeline"])

    target = tmp_path / "imported"
    assert irms.cmd_import(_ns(store=str(target), format="jsonl", source=str(export_path))) == 0
    written = irms.read_memory_record(target / "memories" / "rt-1.md")
    assert irms.compiled_truth_of(written) == "RoundTripTruth."
    kinds = [e["kind"] for e in irms.timeline_of(written)]
    assert "created" in kinds
    assert "truth-updated" in kinds


def test_legacy_jsonl_import_seeds_imported_timeline(tmp_path: Path) -> None:
    """R20 — legacy JSONL (no compiledTruth) seeds truth + kind: imported."""
    source = tmp_path / "legacy.jsonl"
    source.write_text(
        json.dumps({
            "id": "legacy-import",
            "category": "learning",
            "content": "Legacy interchange body.",
        })
        + "\n",
        encoding="utf-8",
    )
    store = tmp_path / "store"
    assert irms.cmd_import(_ns(store=str(store), format="jsonl", source=str(source))) == 0
    record = irms.read_memory_record(store / "memories" / "legacy-import.md")
    assert irms.compiled_truth_of(record) == "Legacy interchange body."
    assert irms.timeline_of(record)[0]["kind"] == "imported"


def test_legacy_okf_import_seeds_imported_timeline(tmp_path: Path) -> None:
    """R20 — legacy OKF bodies upgrade with kind: imported."""
    bundle = tmp_path / "okf"
    mem_dir = bundle / "learning"
    mem_dir.mkdir(parents=True)
    (mem_dir / "okf-legacy.md").write_text(
        "---\ntype: learning\nid: okf-legacy\ntimestamp: 2026-07-22T00:00:00Z\n---\n"
        "OKF legacy body.\n",
        encoding="utf-8",
    )
    store = tmp_path / "store"
    assert irms.cmd_import(_ns(store=str(store), format="okf", source=str(bundle))) == 0
    record = irms.read_memory_record(store / "memories" / "okf-legacy.md")
    assert "OKF legacy body." in irms.compiled_truth_of(record)
    assert irms.timeline_of(record)[0]["kind"] == "imported"


def test_memory_switch_in_repo_truth_timeline_first_class(repo_root: Path) -> None:
    """R19 — in-repo↔in-repo lossless; other providers cannot represent truth+timeline."""
    catalog = load_catalog(repo_root)
    caps = ms.display_capabilities(catalog, "in-repo", "in-repo")
    assert caps["formats"]["jsonl"]["migration"] == "supported"
    assert caps["firstClassFields"]["fields"] == list(ms.IN_REPO_FIRST_CLASS_FIELDS)
    assert caps["firstClassFields"]["provider"] == "in-repo"

    for other in ("mempalace", "basic-memory", "obsidian", "recallium"):
        outbound = ms.display_capabilities(catalog, "in-repo", other)
        assert outbound["formats"]["jsonl"]["migration"] == "lossy"
        inbound = ms.display_capabilities(catalog, other, "in-repo")
        assert inbound["formats"]["jsonl"]["migration"] == "lossy"


def test_memory_switch_in_repo_round_trip_preserves_timeline(repo_root: Path, tmp_path: Path) -> None:
    """R19 — migrate export/import for in-repo preserves timeline entries."""
    workspace = tmp_path / "ws"
    store = workspace / ".cursor" / "sw-memory"
    (store / "memories").mkdir(parents=True)
    (workspace / ".sw").mkdir()
    catalog = (repo_root / ".sw" / "memory-provider-catalog.json").read_text(encoding="utf-8")
    (workspace / ".sw" / "memory-provider-catalog.json").write_text(catalog, encoding="utf-8")
    (workspace / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"memory": {"provider": "in-repo"}}, indent=2) + "\n",
        encoding="utf-8",
    )
    irms.cmd_store(_ns(
        store=str(store),
        id="switch-1",
        category="learning",
        content="Switch truth.",
        summary="",
        tags="",
        scope="project",
    ))
    irms.cmd_update_truth(_ns(
        store=str(store),
        id="switch-1",
        truth="Switch truth updated.",
        summary="via switch test",
    ))
    export_path = workspace / "export.jsonl"
    result = ms.migrate_export_step(
        workspace,
        source_id="in-repo",
        target_id="in-repo",
        fmt="jsonl",
        export_path=export_path,
        store_path=store,
    )
    assert result["verdict"] == "pass"
    assert result["lossy"] is False
    ms.migrate_switch_step(workspace, "in-repo", dry_run=False)
    target = workspace / "target-store"
    confirmed = ms.migrate_import_step(
        workspace,
        fmt="jsonl",
        source_path=export_path,
        store_path=target,
        dry_run=False,
        confirm=True,
    )
    assert confirmed["fidelity"]["verdict"] == "pass"
    written = irms.read_memory_record(target / "memories" / "switch-1.md")
    assert irms.compiled_truth_of(written) == "Switch truth updated."
    assert any(e["kind"] == "truth-updated" for e in irms.timeline_of(written))


def test_adapter_documents_update_truth(repo_root: Path) -> None:
    """R13, R22 — adapter documents update-truth and non-goals."""
    text = (repo_root / "core" / "providers" / "in-repo.md").read_text(encoding="utf-8")
    assert "update-truth" in text
    assert "## Compiled truth" in text
    assert "Non-goals" in text
    assert "brain/" in text.lower() or "`brain/`" in text


def test_catalog_has_no_brain_provider(repo_root: Path) -> None:
    """R1, R21 — catalog notes truth/timeline; no brain provider id."""
    catalog = load_catalog(repo_root)
    providers = catalog["providers"]
    assert "in-repo" in providers
    assert "brain" not in providers
    assert "brain-md" not in providers
    notes = providers["in-repo"]["hookTransport"]["notes"]
    assert "timeline" in notes.lower() or "truth" in notes.lower()
    emit = json.loads(
        (repo_root / "core" / "sw-reference" / "memory-provider-catalog.json").read_text(
            encoding="utf-8"
        )
    )
    assert emit["providers"]["in-repo"]["hookTransport"]["notes"] == notes
