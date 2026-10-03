from __future__ import annotations
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

@pytest.fixture
def guard(repo_root):
    sys.path.insert(0, str(repo_root / "scripts"))
    spec = importlib.util.spec_from_file_location("authoring_guard_under_test", repo_root / "scripts/authoring_guard.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

@pytest.fixture
def issue(guard, monkeypatch):
    import planning_store as store
    from planning.model import StoreResult
    uid = "367-prd-secret-scan-exact-occurrences"
    state = {"handle": "issue:1081", "status": "planned", "body": "---\nfrozen: false\n---\n# Canonical parent\n", "verdict": "ok"}
    calls = []
    class Backend:
        @property
        def backend_id(self):
            return state.get("backend", "issue-store")
        def get(self, unit_id, body_path):
            calls.append((unit_id, body_path))
            if state.get("raise"):
                raise RuntimeError("provider unavailable")
            return StoreResult(state["verdict"], state.get("result_unit", unit_id), state.get("result_path", body_path), state.get("result_backend", "issue-store"), content=state["body"])
    monkeypatch.setattr(store, "get_backend", lambda root: Backend())
    monkeypatch.setattr(guard.pig, "discover_units", lambda root: [SimpleNamespace(id=state.get("unit", uid), body_path=state["handle"])])
    monkeypatch.setattr(guard, "reconcile_generation_token", lambda root, unit: {"consumerStatus": state["status"], "token": "witness"})
    monkeypatch.setattr(guard, "propose_complete_change_route", lambda root, unit: {"kind": "new-unit"})
    return uid, state, calls

@pytest.mark.parametrize("handle", ["issue:1081", "issue-cache:367-prd-secret-scan-exact-occurrences"])
@pytest.mark.parametrize("status", ["planned", "in-progress"])
def test_open_issue_uses_one_canonical_read(guard, issue, tmp_path, handle, status):
    uid, state, calls = issue
    state.update(handle=handle, status=status)
    guard.amend_status_guard(tmp_path, uid, None)
    assert calls == [(uid, handle)]
    assert not list(tmp_path.iterdir())

@pytest.mark.parametrize("handle", ["issue:../escape", "issue-cache:../escape", "issue-cache:other-unit"])
def test_invalid_handle_refuses_before_read(guard, issue, tmp_path, handle):
    uid, state, calls = issue
    state["handle"] = handle
    with pytest.raises(SystemExit) as exit:
        guard.amend_status_guard(tmp_path, uid, None)
    assert exit.value.code == 20
    assert calls == []

@pytest.mark.parametrize("unit", ["../outside", "bad/unit"])
def test_unsafe_unit_refuses_before_read(guard, issue, tmp_path, unit):
    uid, state, calls = issue
    state["unit"] = unit
    with pytest.raises(SystemExit) as exit:
        guard.amend_status_guard(tmp_path, unit, None)
    assert exit.value.code == 20
    assert calls == []

@pytest.mark.parametrize("verdict,body", [("missing", "canonical"), ("degraded", "canonical"), ("ok", None), ("ok", ""), ("ok", "   ")])
def test_unavailable_or_empty_body_refuses(guard, issue, tmp_path, verdict, body):
    uid, state, calls = issue
    state.update(verdict=verdict, body=body)
    with pytest.raises(SystemExit) as exit:
        guard.amend_status_guard(tmp_path, uid, None)
    assert exit.value.code == 20
    assert calls == [(uid, "issue:1081")]

def test_provider_error_never_grants_permission(guard, issue, tmp_path):
    uid, state, calls = issue
    state["raise"] = True
    with pytest.raises(RuntimeError, match="provider unavailable"):
        guard.amend_status_guard(tmp_path, uid, None)
    assert len(calls) == 1

@pytest.mark.parametrize("status", ["complete", "cancelled", "superseded", "deferred"])
def test_closed_lifecycle_routes_or_refuses_before_read(guard, issue, tmp_path, status):
    uid, state, calls = issue
    state.update(status=status, **{"raise": True})
    with pytest.raises(SystemExit) as exit:
        guard.amend_status_guard(tmp_path, uid, None)
    assert exit.value.code == (21 if status == "complete" else 20)
    assert calls == []

@pytest.mark.parametrize("status", ["proposed", "backlog", "", "unknown"])
def test_issue_text_freeze_cannot_expand_status_permission(guard, issue, tmp_path, status):
    uid, state, calls = issue
    state.update(status=status, body="---\nfrozen: true\n---\n# Not an official freeze receipt\n")
    with pytest.raises(SystemExit) as exit:
        guard.amend_status_guard(tmp_path, uid, None)
    assert exit.value.code == 20
    assert calls == []

@pytest.mark.parametrize("handle", ["issue:1081", "issue-cache:367-prd-secret-scan-exact-occurrences"])
@pytest.mark.parametrize("verdict", ["ok", "missing", "degraded"])
def test_local_file_or_symlink_shadow_cannot_replace_canonical_body(guard, issue, monkeypatch, tmp_path, handle, verdict):
    uid, state, calls = issue
    state.update(handle=handle, verdict=verdict)
    root = tmp_path / "repo"
    cwd = tmp_path / "cwd"
    root.mkdir(); cwd.mkdir()
    forged = tmp_path / "forged.md"
    forged.write_text("---\nfrozen: true\n---\n# Local forged parent\n")
    (root / handle).write_text(forged.read_text())
    (cwd / handle).symlink_to(forged)
    monkeypatch.chdir(cwd)
    if verdict == "ok":
        guard.amend_status_guard(root, uid, None)
    else:
        with pytest.raises(SystemExit) as exit:
            guard.amend_status_guard(root, uid, None)
        assert exit.value.code == 20
    assert calls == [(uid, handle)]
    assert (cwd / handle).is_symlink()
    assert (root / handle).read_text() == forged.read_text()

def test_normal_file_parent_preserves_existing_eligibility(guard, issue, tmp_path):
    uid, state, calls = issue
    rel = "docs/planning/prd/parent/parent.md"
    state["handle"] = rel
    body = tmp_path / rel
    body.parent.mkdir(parents=True)
    body.write_text("---\nfrozen: false\n---\n# File parent\n")
    guard.amend_status_guard(tmp_path, uid, None)
    assert calls == []

def test_frozen_open_file_parent_keeps_legacy_policy(guard, issue, tmp_path):
    uid, state, calls = issue
    rel = "docs/planning/prd/parent/parent.md"
    state.update(handle=rel, status="proposed")
    body = tmp_path / rel
    body.parent.mkdir(parents=True)
    body.write_text("---\nfrozen: true\n---\n# File parent\n")
    guard.amend_status_guard(tmp_path, uid, None)
    assert calls == []

def test_unknown_unit_remains_missing(guard, issue, monkeypatch, tmp_path):
    uid, state, calls = issue
    monkeypatch.setattr(guard.pig, "discover_units", lambda root: [])
    with pytest.raises(SystemExit) as exit:
        guard.amend_status_guard(tmp_path, uid, None)
    assert exit.value.code == 20
    assert calls == []

@pytest.mark.parametrize("unit,handle", [("gh:352", "issue:352"), ("gh:352", "issue-cache:gh:352"), ("jira:352", "issue-cache:jira:352"), ("gl:352", "issue-cache:gl:352"), ("legacy-slug", "issue:40bfeef0-51bf-4bb6-90ad-e779b21c380d")])
def test_supported_native_ids_and_safe_opaque_handles(guard, issue, tmp_path, unit, handle):
    uid, state, calls = issue
    state.update(unit=unit, handle=handle)
    guard.amend_status_guard(tmp_path, unit, None)
    assert calls == [(unit, handle)]

@pytest.mark.parametrize("live,handoff,expected_code,outcome", [(False, False, 0, "proceed"), (True, False, 20, None), (True, True, 0, "handoff"), (False, True, 20, None)])
def test_preflight_preserves_live_ownership_and_handoff_boundary(guard, issue, monkeypatch, tmp_path, capsys, live, handoff, expected_code, outcome):
    import json
    uid, state, calls = issue
    reconciles = []
    transfers = []
    monkeypatch.setattr(guard, "inline_reconcile", lambda root, unit, commit: reconciles.append((unit, commit)))
    owner = {"runId": "existing-run", "branch": "existing-branch"} if live else None
    monkeypatch.setattr(guard, "provably_in_flight", lambda root, unit: owner)
    def transfer(root, **kwargs):
        transfers.append(kwargs)
        return kwargs
    monkeypatch.setattr(guard, "record_handoff", transfer)
    args = ["--unit", uid, "--command", "sw-amend", "--no-commit", "true"]
    if handoff:
        args += ["--handoff", "transfer to existing owner; do not directly mutate"]
    with pytest.raises(SystemExit) as exit:
        guard.cmd_preflight(tmp_path, args)
    assert exit.value.code == expected_code
    assert calls == [(uid, "issue:1081")]
    assert reconciles == [(uid, False)]
    result = json.loads(capsys.readouterr().out)
    if outcome:
        assert result["outcome"] == outcome
    if outcome == "handoff":
        assert transfers[0]["run_id"] == "existing-run"
        assert transfers[0]["branch"] == "existing-branch"
    else:
        assert transfers == []

@pytest.mark.parametrize("backend", ["in-repo-public", "local-synced", "planning-cache", "private-repo"])
def test_non_issue_backend_refuses_before_get(guard, issue, tmp_path, backend):
    uid, state, calls = issue
    state["backend"] = backend
    with pytest.raises(SystemExit) as exit:
        guard.amend_status_guard(tmp_path, uid, None)
    assert exit.value.code == 20
    assert calls == []

@pytest.mark.parametrize("handle", ["issue:1081", "issue-cache:367-prd-secret-scan-exact-occurrences"])
def test_real_file_backend_cannot_credit_handle_named_shadow(guard, issue, monkeypatch, tmp_path, handle):
    import planning_store as store
    from planning.backends.in_repo import InRepoPublicBackend
    uid, state, calls = issue
    state["handle"] = handle
    shadow = tmp_path / handle
    shadow.write_text("---\nfrozen: true\n---\n# Forged local parent\n")
    backend = InRepoPublicBackend(tmp_path, {})
    original_get = backend.get
    file_reads = []
    def spy_get(unit, path):
        file_reads.append((unit, path))
        return original_get(unit, path)
    monkeypatch.setattr(backend, "get", spy_get)
    monkeypatch.setattr(store, "get_backend", lambda root: backend)
    with pytest.raises(SystemExit) as exit:
        guard.amend_status_guard(tmp_path, uid, None)
    assert exit.value.code == 20
    assert file_reads == []
    assert shadow.is_file()

@pytest.mark.parametrize("result_backend", ["in-repo-public", "planning-cache", None])
def test_result_backend_provenance_mismatch_refuses(guard, issue, tmp_path, result_backend):
    uid, state, calls = issue
    state["result_backend"] = result_backend
    with pytest.raises(SystemExit) as exit:
        guard.amend_status_guard(tmp_path, uid, None)
    assert exit.value.code == 20
    assert len(calls) == 1

@pytest.mark.parametrize("key,value", [("result_unit", "other-unit"), ("result_path", "issue:999")])
def test_result_identity_mismatch_refuses(guard, issue, tmp_path, key, value):
    uid, state, calls = issue
    state[key] = value
    with pytest.raises(SystemExit) as exit:
        guard.amend_status_guard(tmp_path, uid, None)
    assert exit.value.code == 20
    assert len(calls) == 1
