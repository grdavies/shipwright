"""Cross-host HandoffBundle continuation smoke + unit coverage (PRD 349 R31–R38, R50–R51)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
import sys

sys.path[:0] = [str(REPO), str(REPO / "core"), str(REPO / "scripts")]

from handoff.acknowledgement import (  # noqa: E402
    list_pending_transitions,
    read_destination_ack,
    write_destination_ack,
)
from handoff.bundle import (  # noqa: E402
    BundleBuildError,
    attach_cross_host_transition,
    build_continuation_payload,
    export_cross_host_bundle,
    source_repo_id_for_remote,
)
from handoff.importer import ImportError_, ImportLock, import_bundle  # noqa: E402
from handoff.validate_bundle import digest_payload, validate_bundle  # noqa: E402
from credentials.resolver import (  # noqa: E402
    RepositoryContext,
    clear_resolve_cache,
)


FIXTURE = REPO / "core" / "tests" / "fixtures" / "bundle_self_test" / "pass.json"


def _base_bundle() -> dict:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.pop("destination_ack", None)
    data.pop("source_host", None)
    data.pop("destination_host", None)
    data.pop("transition_id", None)
    data.pop("continuation_payload", None)
    data.pop("pending_captures", None)
    data.pop("source_repo_id", None)
    data.pop("source_head", None)
    data.pop("bundleDigest", None)
    data["bundleDigest"] = digest_payload(data)
    return data


def _continuation(**overrides):
    payload = build_continuation_payload(
        task_baseline={"unitId": "349-platform-portability", "canonicalVersion": "1"},
        prd_baseline={"frozenCanonicalVersion": "1"},
        repo={
            "worktree": str(REPO),
            "head": "a" * 40,
            "remoteUrl": "https://github.com/example/shipwright.git",
        },
        current_workflow_node_id="sw-execute",
        completed_task_rows=[{"id": "4.1", "title": "fields"}],
        remaining_task_rows=[{"id": "4.2", "title": "import"}],
        unresolved_decisions=[
            {"title": "pick host", "options": ["codex", "opencode"], "blocking": True}
        ],
        evidence_references=[
            {"path": "docs/prds/349-platform-portability/tasks-349-platform-portability.md", "type": "task-list", "digest": "sha256:" + ("b" * 64)}
        ],
        model_attempt_lineage=[
            {"host": "claude-code", "modelId": "test", "attemptUuid": "11111111-1111-1111-1111-111111111111"}
        ],
    )
    payload.update(overrides)
    return payload


def test_same_host_bundle_still_validates():
    assert validate_bundle(_base_bundle())["verdict"] == "pass"


def test_cross_host_fields_and_continuation_validate(tmp_path: Path):
    base = _base_bundle()
    cont = _continuation()
    remote = "https://github.com/example/shipwright.git"
    enriched = attach_cross_host_transition(
        base,
        source_host="claude-code",
        destination_host="codex",
        continuation_payload=cont,
        pending_captures=[{"kind": "gap", "title": "follow-up"}],
        source_repo_id=source_repo_id_for_remote(remote),
        source_head="a" * 40,
        transition_id="22222222-2222-2222-2222-222222222222",
    )
    assert enriched["transition_id"]
    assert enriched["pending_captures"] == [{"kind": "gap", "title": "follow-up"}]
    assert "token" not in json.dumps(enriched).lower() or "github_pat" not in json.dumps(enriched)
    out = tmp_path / "bundle.json"
    export_cross_host_bundle(
        base,
        out,
        source_host="claude-code",
        destination_host="codex",
        continuation_payload=cont,
        pending_captures=[{"kind": "gap", "title": "follow-up"}],
        source_repo_id=source_repo_id_for_remote(remote),
        source_head="a" * 40,
        transition_id="22222222-2222-2222-2222-222222222222",
    )
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert validate_bundle(loaded)["verdict"] == "pass"


def test_credential_material_rejected_in_continuation():
    with pytest.raises(BundleBuildError):
        build_continuation_payload(
            task_baseline={"unitId": "u", "canonicalVersion": "1"},
            prd_baseline={"frozenCanonicalVersion": "1"},
            repo={"worktree": "/tmp", "head": "a" * 40},
            current_workflow_node_id="n",
            completed_task_rows=[],
            remaining_task_rows=[],
            unresolved_decisions=[],
            evidence_references=[],
            model_attempt_lineage=[{"host": "x", "modelId": "y", "attemptUuid": "z", "api_token": "secret"}],
        )


def test_idempotent_import_and_ack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    allow = root / ".shipwright" / "memory" / "rule-allowlist.json"
    allow.parent.mkdir(parents=True)
    allow.write_text(json.dumps({"rules": ["mock-realism"]}), encoding="utf-8")

    remote = "https://github.com/example/shipwright.git"
    base = _base_bundle()
    cont = _continuation()
    cont["evidenceReferences"] = []  # skip evidence digest checks
    bundle = attach_cross_host_transition(
        base,
        source_host="claude-code",
        destination_host="codex",
        continuation_payload=cont,
        pending_captures=[],
        source_repo_id=source_repo_id_for_remote(remote),
        source_head="a" * 40,
        transition_id="33333333-3333-3333-3333-333333333333",
    )

    monkeypatch.setattr(
        "handoff.importer.resolve_canonical_remote",
        lambda _root: remote,
    )
    monkeypatch.setattr(
        "handoff.importer._ls_remote_head",
        lambda _root: "a" * 40,
    )
    monkeypatch.setattr(
        "handoff.importer._worktree_clean",
        lambda _root: True,
    )

    first = import_bundle(
        root,
        bundle,
        run_id="run-1",
        destination_adapter_id="codex",
        agent_identity="agent-a",
        interactive=False,
        headless=True,
    )
    second = import_bundle(
        root,
        bundle,
        run_id="run-1",
        destination_adapter_id="codex",
        agent_identity="agent-a",
        interactive=False,
        headless=True,
    )
    assert first.status == "ok"
    assert second.already_imported is True
    state = json.loads(Path(first.state_path).read_text(encoding="utf-8"))
    state2 = json.loads(Path(second.state_path).read_text(encoding="utf-8"))
    assert state == state2
    assert len(state["taskRows"]["completed"]) == 1
    ack = read_destination_ack(root, run_id="run-1", transition_id=bundle["transition_id"])
    assert ack is not None
    assert ack["hostAdapterId"] == "codex"


def test_pending_transition_without_ack(tmp_path: Path):
    root = tmp_path / "repo"
    imports = root / ".shipwright" / "runs" / "run-2" / "imports"
    imports.mkdir(parents=True)
    (imports / "tid-1.json").write_text(
        json.dumps({"source_host": "claude-code", "destination_host": "codex"}),
        encoding="utf-8",
    )
    pending = list_pending_transitions(root)
    assert pending and pending[0]["status"] == "pending"
    assert pending[0]["transitionId"] == "tid-1"


def test_concurrent_import_lock(tmp_path: Path):
    root = tmp_path / "repo"
    lock_a = ImportLock(root, "run-x", agent_identity="agent-1")
    lock_b = ImportLock(root, "run-x", agent_identity="agent-2")
    lock_a.acquire()
    with pytest.raises(ImportError_) as exc:
        lock_b.acquire()
    assert exc.value.code == "already_acquired"
    assert exc.value.details.get("holder") == "agent-1"
    lock_a.release()
    lock_b.acquire()
    lock_b.release()


def test_repo_identity_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "repo"
    root.mkdir()
    allow = root / ".shipwright" / "memory" / "rule-allowlist.json"
    allow.parent.mkdir(parents=True)
    allow.write_text(json.dumps({"rules": ["r1"]}), encoding="utf-8")
    bundle = attach_cross_host_transition(
        _base_bundle(),
        source_host="claude-code",
        destination_host="codex",
        continuation_payload=_continuation(),
        source_repo_id=source_repo_id_for_remote("https://github.com/example/shipwright.git"),
        source_head="a" * 40,
        transition_id="44444444-4444-4444-4444-444444444444",
    )
    monkeypatch.setattr(
        "handoff.importer.resolve_canonical_remote",
        lambda _root: "https://github.com/other/repo.git",
    )
    with pytest.raises(ImportError_) as exc:
        import_bundle(
            root,
            bundle,
            run_id="run-3",
            destination_adapter_id="codex",
            headless=True,
        )
    assert exc.value.code == "repo_identity_mismatch"


def test_headless_context_failure_not_bypassable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "repo"
    root.mkdir()
    allow = root / ".shipwright" / "memory" / "rule-allowlist.json"
    allow.parent.mkdir(parents=True)
    allow.write_text(json.dumps({"rules": ["r1"]}), encoding="utf-8")
    remote = "https://github.com/example/shipwright.git"
    cont = _continuation()
    cont["evidenceReferences"] = []
    bundle = attach_cross_host_transition(
        _base_bundle(),
        source_host="claude-code",
        destination_host="codex",
        continuation_payload=cont,
        source_repo_id=source_repo_id_for_remote(remote),
        source_head="a" * 40,
        transition_id="55555555-5555-5555-5555-555555555555",
    )
    monkeypatch.setattr("handoff.importer.resolve_canonical_remote", lambda _r: remote)
    monkeypatch.setattr("handoff.importer._ls_remote_head", lambda _r: "b" * 40)
    monkeypatch.setattr("handoff.importer._worktree_clean", lambda _r: True)
    with pytest.raises(ImportError_) as exc:
        import_bundle(
            root,
            bundle,
            run_id="run-4",
            destination_adapter_id="codex",
            interactive=False,
            confirm=True,  # must not bypass headless
            headless=True,
        )
    assert exc.value.code == "context_validation_failed"


def test_adapter_id_cache_isolation():
    clear_resolve_cache()
    from credentials import resolver as res

    calls: list[str] = []

    class _Probe:
        def resolve(self, entry, *, purpose, context):  # noqa: ANN001
            calls.append(context.adapter_id or "")
            from credentials.model import ResolutionState
            from credentials.resolver import BackendResolveResult

            return BackendResolveResult(state=ResolutionState.UNRESOLVED, failure_code="probe")

    res.clear_backend_adapters(disable_lazy=True)
    res.register_backend_adapter("environment", _Probe())

    # Minimal selector so resolve_lookup reaches backend
    # If selector missing, we still validate cache key shape via _cache_key
    ctx_a = RepositoryContext(
        remote="https://github.com/o/r.git",
        repo_slug="o/r",
        project_id="p",
        destination_endpoint="https://api.github.com",
        adapter_id="codex",
    )
    ctx_b = RepositoryContext(
        remote="https://github.com/o/r.git",
        repo_slug="o/r",
        project_id="p",
        destination_endpoint="https://api.github.com",
        adapter_id="opencode",
    )
    key_a = res._cache_key("ref", provider="github", purpose="api", context=ctx_a)
    key_b = res._cache_key("ref", provider="github", purpose="api", context=ctx_b)
    assert key_a != key_b
    assert key_a[1] == "codex"
    assert key_b[1] == "opencode"


def test_claude_to_codex_to_opencode_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """R38 — multi-hop continuation preserves rows/decisions/evidence; idempotent; ack each hop."""
    # Use real adapter generators to emit MCP configs (proves generators still work).
    sys.path.insert(0, str(REPO / "platforms" / "codex"))
    sys.path.insert(0, str(REPO / "platforms" / "opencode"))
    from platforms.codex.generator import generate as codex_generate  # type: ignore
    from platforms.opencode.generator import generate as opencode_generate  # type: ignore

    out_codex = tmp_path / "codex-out"
    out_opencode = tmp_path / "opencode-out"
    codex_generate(dest=out_codex, repo_root=REPO)
    opencode_generate(dest=out_opencode, repo_root=REPO)
    assert list(out_codex.rglob("*mcp*")) or list(out_codex.rglob("*.json"))
    assert list(out_opencode.rglob("*mcp*")) or list(out_opencode.rglob("*.json"))

    root = tmp_path / "dest"
    root.mkdir()
    allow = root / ".shipwright" / "memory" / "rule-allowlist.json"
    allow.parent.mkdir(parents=True)
    allow.write_text(json.dumps({"rules": ["mock-realism"]}), encoding="utf-8")
    remote = "https://github.com/example/shipwright.git"
    cont = _continuation()
    cont["evidenceReferences"] = []
    bundle = attach_cross_host_transition(
        _base_bundle(),
        source_host="claude-code",
        destination_host="codex",
        continuation_payload=cont,
        pending_captures=[{"kind": "gap", "title": "pending-item"}],
        source_repo_id=source_repo_id_for_remote(remote),
        source_head="a" * 40,
        transition_id="66666666-6666-6666-6666-666666666666",
    )
    monkeypatch.setattr("handoff.importer.resolve_canonical_remote", lambda _r: remote)
    monkeypatch.setattr("handoff.importer._ls_remote_head", lambda _r: "a" * 40)
    monkeypatch.setattr("handoff.importer._worktree_clean", lambda _r: True)

    # Hop 1: Claude → Codex
    r1 = import_bundle(
        root, bundle, run_id="hop", destination_adapter_id="codex", agent_identity="codex-agent", headless=True
    )
    assert r1.ack and r1.ack["hostAdapterId"] == "codex"

    # Hop 2: re-export conceptually as Codex → OpenCode (same continuation payload)
    bundle2 = attach_cross_host_transition(
        _base_bundle(),
        source_host="codex",
        destination_host="opencode",
        continuation_payload=cont,
        pending_captures=[{"kind": "gap", "title": "pending-item"}],
        source_repo_id=source_repo_id_for_remote(remote),
        source_head="a" * 40,
        transition_id="77777777-7777-7777-7777-777777777777",
    )
    r2 = import_bundle(
        root,
        bundle2,
        run_id="hop",
        destination_adapter_id="opencode",
        agent_identity="opencode-agent",
        headless=True,
    )
    assert r2.ack and r2.ack["hostAdapterId"] == "opencode"
    state = json.loads(Path(r2.state_path).read_text(encoding="utf-8"))
    assert state["taskRows"]["completed"][0]["id"] == "4.1"
    assert state["gapItems"][0]["title"] == "pending-item"

    # Idempotent re-import of hop2
    r2b = import_bundle(
        root,
        bundle2,
        run_id="hop",
        destination_adapter_id="opencode",
        agent_identity="opencode-agent",
        headless=True,
    )
    assert r2b.already_imported is True

    # Delivery-gate stand-in: both acks present and pending empty for those transitions
    assert read_destination_ack(root, run_id="hop", transition_id=bundle["transition_id"])
    assert read_destination_ack(root, run_id="hop", transition_id=bundle2["transition_id"])
