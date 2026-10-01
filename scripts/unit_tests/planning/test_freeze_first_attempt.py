"""PRD 093 R2 — freeze succeeds on first attempt against fixture issue-store units."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from dataclasses import fields
from pathlib import Path

import pytest

from issues_lib import IssueRecord, IssueRevisionConflict
from planning_canonical import (FROZEN_LABEL, FREEZE_INCOMPLETE_LABEL, CommentRecord,
                                build_edges_block, compute_etag)
from planning_github_client import _record_from_issue
from planning_store import IssueStoreBackend, _default_body_path


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ("." + "cursor") / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "freeze-first-093") -> dict:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
            }
        },
        "host": {"provider": "github"},
    }


def _fixture_doc_set(
    backend: IssueStoreBackend,
    *,
    project_key: str,
    prd_unit: str,
    brainstorm_unit: str,
    tasks_unit: str,
) -> tuple[str, str, str]:
    prd_path = _default_body_path(prd_unit, "prd")
    brainstorm_path = _default_body_path(brainstorm_unit, "brainstorm")
    tasks_path = _default_body_path(tasks_unit, "tasks")

    brainstorm_body = (
        f"---\nid: {brainstorm_unit}\ntype: brainstorm\nstatus: draft\nvisibility: public\n---\n"
        f"# Brainstorm for freeze smoke\n\nDistilled rationale without transcript markers.\n"
        + build_edges_block([{"rel": "produces", "target": prd_unit}])
    )
    assert backend.put(brainstorm_unit, brainstorm_path, brainstorm_body).verdict == "ok"

    prd_body = (
        f"---\nid: {prd_unit}\ntype: prd\nstatus: draft\nvisibility: public\n---\n"
        f"# PRD freeze smoke\n\nMinimal PRD body for first-attempt freeze convergence.\n"
    )
    assert backend.put(prd_unit, prd_path, prd_body).verdict == "ok"

    tasks_body = (
        f"---\nid: {tasks_unit}\ntype: tasks\nstatus: draft\nvisibility: public\nprd: {prd_unit}\n---\n"
        f"# Tasks\n\n- [ ] 1.1 Smoke task\n"
    )
    assert backend.put(tasks_unit, tasks_path, tasks_body).verdict == "ok"

    return prd_path, brainstorm_path, tasks_path


def test_freeze_succeeds_first_attempt_for_brainstorm_prd_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2 — IssueStoreBackend.freeze() converges on first call (no revision-conflict retry)."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "freeze-first-093"
    cfg = _issue_store_cfg(project_key)
    (root / ("." + "cursor") / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    prd_unit = "093-prd-freeze-etag-retry-and-absorb-edge-preservation"
    brainstorm_unit = "2026-08-04-freeze-first-attempt-smoke"
    tasks_unit = "tasks-093-prd-freeze-etag-retry-and-absorb-edge-preservation"

    backend = IssueStoreBackend(root, cfg)
    prd_path, brainstorm_path, tasks_path = _fixture_doc_set(
        backend,
        project_key=project_key,
        prd_unit=prd_unit,
        brainstorm_unit=brainstorm_unit,
        tasks_unit=tasks_unit,
    )

    lock_calls = 0
    label_calls = 0
    original_lock = backend._client.issue_lock
    original_label = backend._client.issue_label

    def counting_lock(issue_id: str, *, if_match: str | None = None):
        nonlocal lock_calls
        lock_calls += 1
        return original_lock(issue_id, if_match=if_match)

    def counting_label(issue_id: str, labels: list[str], *, if_match: str | None = None):
        nonlocal label_calls
        label_calls += 1
        return original_label(issue_id, labels, if_match=if_match)

    monkeypatch.setattr(backend._client, "issue_lock", counting_lock)
    monkeypatch.setattr(backend._client, "issue_label", counting_label)

    prd_result = backend.freeze(prd_unit, prd_path, distill=True)
    assert prd_result["verdict"] == "ok"
    assert prd_result.get("locked") is True
    assert prd_result.get("hash")

    tasks_result = backend.freeze(tasks_unit, tasks_path, distill=False)
    assert tasks_result["verdict"] == "ok"
    assert tasks_result.get("locked") is True

    brainstorm_result = backend.freeze(brainstorm_unit, brainstorm_path, distill=False)
    assert brainstorm_result["verdict"] == "ok"
    assert brainstorm_result.get("locked") is True

    assert lock_calls == 3
    assert label_calls >= 3

    store_path = root / ("." + "cursor") / "hooks" / "state" / "issue-store-fixture.json"
    fixture = json.loads(store_path.read_text(encoding="utf-8"))
    for unit in (prd_unit, tasks_unit, brainstorm_unit):
        record = next(
            rec for rec in fixture["issues"].values() if rec.get("unit_id") == unit
        )
        assert record.get("locked") is True
        assert FROZEN_LABEL in record.get("labels", [])
        if unit == prd_unit:
            freeze_hash = prd_result["hash"]
            comment_bodies = [c.get("body", "") for c in record.get("comments", [])]
            assert any(freeze_hash in body for body in comment_bodies)

# R1: provider-realistic reads are detached and comment publication advances updated_at.


@pytest.fixture
def recovery_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    _init_repo(tmp_path)
    cfg = _issue_store_cfg()
    backend = IssueStoreBackend(tmp_path, cfg)
    unit = "093-prd-recovery"
    paths = _fixture_doc_set(backend, project_key="freeze-first-093", prd_unit=unit,
                            brainstorm_unit="brainstorm-recovery", tasks_unit="tasks-093-recovery")
    client = backend._client
    original_get = client.issue_get
    original_comment = client.issue_comment
    original_search = client.issue_search
    native = {"value": True}
    clock = {"tick": 10000000000}

    def get(issue_id):
        record = deepcopy(original_get(issue_id))
        record.native_locked = native["value"]
        return record

    def comment(issue_id, body, **kwargs):
        result = original_comment(issue_id, body, **kwargs)
        # Fixture persistence must reflect GitHub's comment-driven issue revision.
        record = original_get(issue_id)
        clock["tick"] += 1
        record.updated_at = str(clock["tick"])
        record.etag = compute_etag(record.updated_at, record.body, record.title, record.labels)
        return result

    monkeypatch.setattr(client, "issue_search", lambda **kwargs: deepcopy(original_search(**kwargs)))
    monkeypatch.setattr(client, "issue_get", get)
    monkeypatch.setattr(client, "issue_comment", comment)
    return backend, unit, paths[0], native, original_get


def _interrupt_freeze(store, monkeypatch):
    backend, unit, path, _, _ = store
    monkeypatch.setenv("SW_FREEZE_DISTILL_FAIL", "1")
    with pytest.raises(SystemExit):
        backend.freeze(unit, path)
    monkeypatch.delenv("SW_FREEZE_DISTILL_FAIL")
    record = backend._lookup_record(unit, path)
    assert FREEZE_INCOMPLETE_LABEL in record.labels
    return record


@pytest.mark.parametrize("raw", [True, False, None, "true", "false", 1, 0])
def test_native_lock_is_strict_transient_evidence(raw):
    payload = {"number": 1, "body": "body", "title": "title", "locked": raw,
               "updated_at": "2026-10-01", "labels": [FROZEN_LABEL, FREEZE_INCOMPLETE_LABEL]}
    record = _record_from_issue(payload)
    assert record.locked is True
    assert record.native_locked is (raw if type(raw) is bool else None)
    assert "native_locked" not in record.to_snapshot_dict()
    assert record.etag == compute_etag(payload["updated_at"], "body", "title", payload["labels"])
    assert fields(IssueRecord)[-1].name == "native_locked"
    old = IssueRecord("1", 1, "t", "b", "open", [], [], [], [], True, "u", "e", "p", "prd", "unit", False, False)
    assert old.native_locked is None and old.unit_id == "unit" and old.locked
    assert IssueRecord.from_dict(record.to_snapshot_dict()).native_locked is None


def test_pointer_comment_revision_uses_fresh_etag(recovery_store):
    backend, unit, path, _, _ = recovery_store
    result = backend.freeze(unit, path)
    assert result["verdict"] == "ok"
    assert backend._find_linked_brainstorm(unit).state == "closed"


def test_incomplete_recovery_preserves_receipt_and_is_idempotent(recovery_store, monkeypatch):
    backend, unit, path, _, _ = recovery_store
    before = _interrupt_freeze(recovery_store, monkeypatch)
    monkeypatch.setattr(backend._client, "issue_lock", lambda *a, **kw: pytest.fail("recovery must never relock"))
    result = backend.freeze(unit, path)
    assert result["verdict"] == "ok"
    after = backend._lookup_record(unit, path)
    assert FREEZE_INCOMPLETE_LABEL not in after.labels
    assert before.body == after.body
    assert before.comments == after.comments
    brainstorm = backend._find_linked_brainstorm(unit)
    assert brainstorm.state == "closed"
    assert sum("sw-memory-pointer" in c.body for c in brainstorm.comments) == 1
    with pytest.raises(SystemExit):
        backend.freeze(unit, path)
    assert backend._find_linked_brainstorm(unit).comments == brainstorm.comments


@pytest.mark.parametrize("native", [False, None, "true", 1])
def test_incomplete_recovery_refuses_native_unknown_or_false(recovery_store, monkeypatch, native):
    backend, unit, path, evidence, _ = recovery_store
    before = _interrupt_freeze(recovery_store, monkeypatch)
    evidence["value"] = native
    with pytest.raises(SystemExit):
        backend.freeze(unit, path)
    assert backend._lookup_record(unit, path).comments == before.comments
    assert FREEZE_INCOMPLETE_LABEL in backend._lookup_record(unit, path).labels
    assert not backend._find_linked_brainstorm(unit).comments


@pytest.mark.parametrize("drift", ["title", "body", "state", "labels", "unit_id", "project_key", "artifact_type", "receipt", "ambiguous", "ambiguous-hashes", "comment", "native_links"])
def test_incomplete_recovery_refuses_drift(recovery_store, monkeypatch, drift):
    backend, unit, path, _, raw_get = recovery_store
    before = _interrupt_freeze(recovery_store, monkeypatch)
    live = raw_get(before.id)
    if drift == "native_links": live.native_links.append({"type": "depends-on", "target": "999"})
    elif drift == "labels": live.labels.append("unexpected")
    elif drift == "receipt": live.comments.clear()
    elif drift == "ambiguous": live.comments.append(deepcopy(live.comments[0]))
    elif drift == "ambiguous-hashes": live.comments[0].body += live.comments[0].body
    elif drift == "comment": live.comments.append(CommentRecord("extra", "changed requirements", "now", []))
    else: setattr(live, drift, getattr(live, drift) + "-drift")
    with pytest.raises(SystemExit):
        backend.freeze(unit, path)
    assert FREEZE_INCOMPLETE_LABEL in raw_get(before.id).labels
    assert not backend._find_linked_brainstorm(unit).comments


@pytest.mark.parametrize("after_removal", [False, True])
def test_native_loss_never_returns_success(recovery_store, monkeypatch, after_removal):
    backend, unit, path, native, _ = recovery_store
    _interrupt_freeze(recovery_store, monkeypatch)
    original = backend._client.issue_label
    if after_removal:
        def label(issue_id, labels, **kwargs):
            result = original(issue_id, labels, **kwargs)
            if FREEZE_INCOMPLETE_LABEL not in labels: native["value"] = False
            return result
        monkeypatch.setattr(backend._client, "issue_label", label)
    else:
        original_absorb = backend._ensure_absorb_linkage_at_freeze
        def absorb(*args):
            native["value"] = False
            return original_absorb(*args)
        monkeypatch.setattr(backend, "_ensure_absorb_linkage_at_freeze", absorb)
    with pytest.raises(SystemExit):
        backend.freeze(unit, path)
    assert FREEZE_INCOMPLETE_LABEL in backend._lookup_record(unit, path).labels

@pytest.mark.parametrize("closed", [False, True])
def test_resume_pointer_publication_deduplicates(recovery_store, monkeypatch, closed):
    backend, unit, path, _, _ = recovery_store
    original_update = backend._client.issue_update
    def interrupt_close(*args, **kwargs):
        if kwargs.get("state") == "closed":
            if closed: original_update(*args, **kwargs)
            raise RuntimeError("interrupted-close")
        return original_update(*args, **kwargs)
    monkeypatch.setattr(backend._client, "issue_update", interrupt_close)
    with pytest.raises(SystemExit): backend.freeze(unit, path)
    before = backend._find_linked_brainstorm(unit)
    assert len(before.comments) == 1
    monkeypatch.setattr(backend._client, "issue_update", original_update)
    assert backend.freeze(unit, path)["verdict"] == "ok"
    after = backend._find_linked_brainstorm(unit)
    assert after.comments == before.comments
    assert after.state == "closed"


@pytest.mark.parametrize("mode", ["pointer-mismatch", "closed-without-pointer", "absorb-failure", "absorb-exception", "close-body-drift", "label-conflict", "restoration-conflict", "post-body-drift", "pre-body-drift"])
def test_recovery_failure_boundaries(recovery_store, monkeypatch, capsys, mode):
    backend, unit, path, native, raw_get = recovery_store
    before = _interrupt_freeze(recovery_store, monkeypatch)
    brainstorm = raw_get(backend._find_linked_brainstorm(unit).id)
    if mode == "pointer-mismatch":
        backend._client.issue_comment(brainstorm.id, "<!-- sw-memory-pointer -->\nwrong", markers=["sw-memory-pointer"])
    elif mode == "closed-without-pointer": brainstorm.state = "closed"
    elif mode.startswith("absorb"):
        def absorb(*args):
            if mode == "absorb-exception": raise RuntimeError("absorb-failed")
            return {"verdict": "fail"}
        monkeypatch.setattr(backend, "_ensure_absorb_linkage_at_freeze", absorb)
    elif mode == "close-body-drift":
        original_comment = backend._client.issue_comment
        def comment(*args, **kwargs):
            result = original_comment(*args, **kwargs)
            raw_get(args[0]).body += "drift"
            return result
        monkeypatch.setattr(backend._client, "issue_comment", comment)
    elif mode == "pre-body-drift":
        def absorb(*args):
            raw_get(before.id).body += "\n"
            return {"verdict": "skipped"}
        monkeypatch.setattr(backend, "_ensure_absorb_linkage_at_freeze", absorb)
    else:
        original_label = backend._client.issue_label
        def label(issue_id, labels, **kwargs):
            if mode == "label-conflict" or (mode == "restoration-conflict" and FREEZE_INCOMPLETE_LABEL in labels):
                raise IssueRevisionConflict("revision-conflict")
            result = original_label(issue_id, labels, **kwargs)
            if FREEZE_INCOMPLETE_LABEL not in labels:
                if mode == "post-body-drift": raw_get(issue_id).body += "\n"
                else: native["value"] = False
            return result
        monkeypatch.setattr(backend._client, "issue_label", label)
    with pytest.raises(SystemExit): backend.freeze(unit, path)
    output = capsys.readouterr().out
    if mode in {"restoration-conflict", "post-body-drift"}:
        assert '"error": "freeze-recovery-partial-apply"' in output
        assert '"partialApply": true' in output
    else: assert FREEZE_INCOMPLETE_LABEL in raw_get(before.id).labels
    assert raw_get(before.id).comments == before.comments


@pytest.mark.parametrize("authority", [False, True])
def test_http404_cache_notice_and_authority_refusal(recovery_store, monkeypatch, authority):
    import planning_store as ps
    from urllib.error import HTTPError
    backend, unit, path, _, _ = recovery_store
    _interrupt_freeze(recovery_store, monkeypatch)
    backend.cfg["memory"] = {"provider": "recallium", "project": "freeze-first-093",
                             "connection": {"restBaseUrl": "http://localhost:8001"}}
    ReplicatedPlanningCacheBackend = backend._distill_brainstorm_rationale.__globals__["ReplicatedPlanningCacheBackend"]
    monkeypatch.setattr(ReplicatedPlanningCacheBackend, "configured_provider", lambda self: "recallium")
    monkeypatch.setattr(ReplicatedPlanningCacheBackend, "_has_configured_remote_planning_authority", lambda self: authority)
    def not_found(req, **kwargs): raise HTTPError(req.full_url, 404, "not found", {}, None)
    monkeypatch.setattr(ps, "_urlopen", not_found)
    if authority:
        with pytest.raises(SystemExit): backend.freeze(unit, path)
        assert FREEZE_INCOMPLETE_LABEL in backend._lookup_record(unit, path).labels
        assert not backend._find_linked_brainstorm(unit).comments
    else:
        result = backend.freeze(unit, path)
        assert "provider-http-404" in result["distillation"]["notice"]
        assert "local cache" in result["distillation"]["notice"]
        assert "round-trip ok" not in result["distillation"]["notice"]


def _seed_closed_witness(store, *, include_body_path=True):
    from planning_doc_review_transport import (build_open_manifest_block, upsert_review_round_block,
        build_completion_receipt_body, body_manifest_id, default_completion_idempotency_key,
        build_doc_review_comment_body, pin_rows_from_ordered_comments)
    backend, unit, path, _, raw_get = store
    record = raw_get(backend._lookup_record(unit, path).id)
    retained_path = path if include_body_path else None
    finding = CommentRecord("review-finding", build_doc_review_comment_body(
        round_id="r2", persona="security", payload={"verdict": "pass", "findings": []},
        unit_id=unit, body_path=retained_path), "before", ["sw-doc-review"], author_id="reviewer")
    pins, error = pin_rows_from_ordered_comments([finding], ordered_comment_ids=[finding.id])
    assert error is None
    record.comments.append(finding)
    manifest = build_open_manifest_block(round_id="r2", unit_id=unit, issue_id=record.id,
        manifest_key="r2", etag="prior-review", body="prior reviewed input", pins=pins, body_path=retained_path)
    manifest["status"] = "closed"
    record.body = upsert_review_round_block(record.body, manifest)
    record.touch()
    manifest_id = body_manifest_id(issue_id=record.id, round_id="r2")
    receipt = build_completion_receipt_body(unit_id=unit, round_id="r2", manifest_id=manifest_id,
        manifest_revision_token="prior-review", body_path=retained_path,
        idempotency_key_value=default_completion_idempotency_key(round_id="r2", manifest_id=manifest_id))
    record.comments.append(CommentRecord("review-complete", receipt, "now", ["sw:doc-review-completion"]))
    return record


@pytest.mark.parametrize("drift", [None, "completion", "ambiguous-completion", "path", "open", "pin", "missing-witness", "pre-witness", "post-witness"])
def test_closed_witness_retained_binding(recovery_store, monkeypatch, drift):
    backend, unit, path, _, raw_get = recovery_store
    _seed_closed_witness(recovery_store)
    before = _interrupt_freeze(recovery_store, monkeypatch)
    live = raw_get(before.id)
    if drift == "completion": live.comments[1].body = live.comments[1].body.replace('"verified"', '"failed"')
    elif drift == "ambiguous-completion":
        extra = deepcopy(live.comments[1])
        extra.id = "ambiguous"
        extra.body = extra.body.replace('"verified"', '""')
        live.comments.append(extra)
    elif drift == "path": path = "docs/prds/wrong/prd-wrong.md"
    elif drift == "open": live.body = live.body.replace('"closed"', '"open"')
    elif drift == "pin": live.comments[0].body += "\n"
    elif drift == "missing-witness":
        from planning_doc_review_transport import strip_review_round_blocks
        live.body = strip_review_round_blocks(live.body)
    elif drift == "pre-witness":
        def absorb(*args):
            live.body = live.body.replace('"closed"', '"open"')
            return {"verdict": "skipped"}
        monkeypatch.setattr(backend, "_ensure_absorb_linkage_at_freeze", absorb)
    elif drift == "post-witness":
        original_label = backend._client.issue_label
        def label(*args, **kwargs):
            result = original_label(*args, **kwargs)
            live.body = live.body.replace('"closed"', '"open"')
            return result
        monkeypatch.setattr(backend._client, "issue_label", label)
    if drift:
        with pytest.raises(SystemExit): backend.freeze(unit, path)
    else:
        assert backend.freeze(unit, path)["verdict"] == "ok"
        assert live.body == before.body
        assert live.comments == before.comments


def test_recovery_refuses_unbound_body_path_and_private_destination(recovery_store, monkeypatch):
    backend, unit, path, _, _ = recovery_store
    before = _interrupt_freeze(recovery_store, monkeypatch)
    with pytest.raises(SystemExit): backend.freeze(unit, "docs/prds/wrong/prd-wrong.md")
    def deny(*args): raise SystemExit("private-destination-refused")
    monkeypatch.setattr(backend, "_guard_write_visibility", deny)
    with pytest.raises(SystemExit): backend.freeze(unit, path)
    assert backend._lookup_record(unit, path).comments == before.comments
    assert not backend._find_linked_brainstorm(unit).comments


def test_missing_native_and_snapshot_hash_compatibility():
    from planning_canonical import canonical_hash, IssueSnapshot
    record = _record_from_issue({"number": 1, "body": "body", "labels": []})
    assert record.native_locked is None and record.locked is False
    snapshot = IssueSnapshot(title=record.title, body=record.body, state=record.state, labels=record.labels,
                             comments=record.comments, native_links=record.native_links)
    digest = canonical_hash(snapshot)
    old = record.to_snapshot_dict()
    record.native_locked = True
    assert old == record.to_snapshot_dict()
    assert canonical_hash(snapshot) == digest


def test_private_destination_rechecked_on_recovery(recovery_store, monkeypatch):
    backend, unit, path, _, raw_get = recovery_store
    live = raw_get(backend._lookup_record(unit, path).id)
    live.body = live.body.replace("visibility: public", "visibility: private")
    live.labels = [label for label in live.labels if label != "sw:visibility:public"] + ["sw:visibility:private"]
    live.touch()
    ps = backend._guard_write_visibility.__globals__["_ps"]()
    visibility = ps.issue_store_visibility_gate.__globals__
    monkeypatch.setitem(visibility, "probe_store_host_privacy", lambda *a: {"storeHostPrivacy": "private"})
    before = _interrupt_freeze(recovery_store, monkeypatch)
    monkeypatch.setitem(visibility, "probe_store_host_privacy", lambda *a: {"storeHostPrivacy": "public"})
    with pytest.raises(SystemExit): backend.freeze(unit, path)
    assert raw_get(before.id).comments == before.comments
    assert FREEZE_INCOMPLETE_LABEL in raw_get(before.id).labels
    assert not backend._find_linked_brainstorm(unit).comments


@pytest.mark.parametrize("evidence", ["missing-brainstorm", "retargeted", "missing-search", "ambiguous"])
def test_recovery_requires_unique_brainstorm_evidence(recovery_store, monkeypatch, evidence):
    backend, unit, path, _, raw_get = recovery_store
    before = _interrupt_freeze(recovery_store, monkeypatch)
    brainstorm = raw_get(backend._find_linked_brainstorm(unit).id)
    original_comments = deepcopy(brainstorm.comments)
    if evidence == "missing-brainstorm":
        brainstorm.tombstoned = True
    elif evidence == "retargeted":
        brainstorm.body = brainstorm.body.replace(unit, "another-prd")
        brainstorm.touch()
    elif evidence == "missing-search":
        original_search = backend._client.issue_search
        monkeypatch.setattr(backend._client, "issue_search", lambda **kwargs:
            [] if kwargs.get("artifact_type") == "brainstorm" else original_search(**kwargs))
    else:
        extra_unit = "brainstorm-ambiguous-recovery"
        body = (f"---\nid: {extra_unit}\ntype: brainstorm\nstatus: draft\nvisibility: public\n---\n"
                "# Another linked brainstorm\n" + build_edges_block([{"rel": "produces", "target": unit}]))
        assert backend.put(extra_unit, _default_body_path(extra_unit, "brainstorm"), body).verdict == "ok"
    with pytest.raises(SystemExit):
        backend.freeze(unit, path)
    after = raw_get(before.id)
    assert FREEZE_INCOMPLETE_LABEL in after.labels
    assert after.body == before.body and after.comments == before.comments
    assert brainstorm.state == "open" and brainstorm.comments == original_comments


def test_first_freeze_without_brainstorm_stays_optional(recovery_store):
    backend, unit, path, _, raw_get = recovery_store
    brainstorm = raw_get(backend._find_linked_brainstorm(unit).id)
    brainstorm.tombstoned = True
    result = backend.freeze(unit, path)
    assert result["verdict"] == "ok" and result["distillation"] is None
    assert FREEZE_INCOMPLETE_LABEL not in backend._lookup_record(unit, path).labels


@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("drift_after_pointer", [False, True])
def test_github_search_native_link_projection(recovery_store, monkeypatch, recover, drift_after_pointer):
    from planning_canonical import SW_EDGES_FENCE, parse_edges_block

    backend, unit, path, _, raw_get = recovery_store
    brainstorm = raw_get(backend._find_linked_brainstorm(unit).id)
    native = [{"type": "sub-issue-of", "target": "99"}]
    edges = parse_edges_block(brainstorm.body)
    assert edges is not None
    brainstorm.body = SW_EDGES_FENCE.sub(lambda _: build_edges_block(edges["edges"], native), brainstorm.body)
    brainstorm.native_links = deepcopy(native)
    brainstorm.touch()
    if recover:
        _interrupt_freeze(recovery_store, monkeypatch)

    original_search = backend._client.issue_search
    def github_search(**kwargs):
        records = original_search(**kwargs)
        if kwargs.get("artifact_type") != "brainstorm":
            return records
        projected = []
        for record in records:
            item = _record_from_issue({"number": record.number, "title": record.title,
                "body": record.body, "state": record.state, "labels": record.labels,
                "locked": record.locked, "updated_at": record.updated_at}, project_key=record.project_key)
            # Fixture transport uses UUID IDs; retain that locator while using
            # actual GitHub search normalization (no comments or native links).
            item.id = record.id
            assert item.comments == [] and item.native_links == []
            projected.append(item)
        return projected
    monkeypatch.setattr(backend._client, "issue_search", github_search)
    if drift_after_pointer:
        original_comment = backend._client.issue_comment
        def publish_then_drift(issue_id, body, **kwargs):
            result = original_comment(issue_id, body, **kwargs)
            if issue_id == brainstorm.id:
                brainstorm.native_links = [{"type": "sub-issue-of", "target": "100"}]
            return result
        monkeypatch.setattr(backend._client, "issue_comment", publish_then_drift)
        with pytest.raises(SystemExit):
            backend.freeze(unit, path)
        assert FREEZE_INCOMPLETE_LABEL in raw_get(backend._lookup_record(unit, path).id).labels
        assert brainstorm.state == "open"
    else:
        result = backend.freeze(unit, path)
        assert result["verdict"] == "ok"
        assert brainstorm.state == "closed" and brainstorm.native_links == native
        assert FREEZE_INCOMPLETE_LABEL not in backend._lookup_record(unit, path).labels
    # Drift must be caught on a subsequent full read, not by falsely treating
    # the initial search projection's empty native list as evidence of change.
    assert sum("sw-memory-pointer" in c.body for c in brainstorm.comments) == 1


@pytest.mark.parametrize("binding", ["unit-only", "manifest-path-mismatch", "receipt-path-mismatch"])
def test_unit_only_v1_virtual_path(recovery_store, monkeypatch, binding):
    from planning_doc_review_transport import (inspect_review_round_block,
        parse_completion_receipt, upsert_review_round_block)

    backend, unit, _, native, raw_get = recovery_store
    # This filename shape is already supported by the canonical issue facade;
    # it is intentionally different from the convenience _default_body_path.
    virtual_path = f"docs/prds/093-recovery/{unit}.md"
    assert virtual_path != _default_body_path(unit, "prd")
    store = backend, unit, virtual_path, native, raw_get
    live = _seed_closed_witness(store, include_body_path=False)
    manifest, error = inspect_review_round_block(live.body)
    assert error is None
    assert manifest["apiVersion"] == "shipwright.dev/doc-review-manifest/v1"
    assert manifest["artifact"] == {"unitId": unit}
    receipt = parse_completion_receipt(live.comments[1].body)
    assert receipt["apiVersion"] == "shipwright.dev/doc-review-completion/v1"
    assert receipt["artifact"] == {"unitId": unit}
    if binding == "manifest-path-mismatch":
        manifest["artifact"]["bodyPath"] = "docs/prds/other/prd-other.md"
        live.body = upsert_review_round_block(live.body, manifest)
        live.touch()
    elif binding == "receipt-path-mismatch":
        live.comments[1].body = live.comments[1].body.replace(
            '"unitId":', '"bodyPath": "docs/prds/other/prd-other.md", "unitId":')
    before = _interrupt_freeze(store, monkeypatch)
    if binding == "unit-only":
        result = backend.freeze(unit, virtual_path)
        assert result["verdict"] == "ok" and result["bodyPath"] == virtual_path
        assert FREEZE_INCOMPLETE_LABEL not in live.labels
    else:
        with pytest.raises(SystemExit): backend.freeze(unit, virtual_path)
        assert FREEZE_INCOMPLETE_LABEL in live.labels
        assert not backend._find_linked_brainstorm(unit).comments
    assert live.body == before.body and live.comments == before.comments
