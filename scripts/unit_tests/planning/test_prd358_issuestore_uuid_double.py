"""PRD 358 R5 / D6 / AS6 — UUID-minting IssueStoreBackend Linear adapter double.

Regression coverage drives put → get → materialize through a Linear-shaped adapter
that (a) mints 36-character ids and (b) still runs prepare_body_with_overflow on
update. Fixture comment-N stores and fixture client branches that skip
prepare_body_with_overflow are not this scenario.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_canonical as pc
import planning_linear_client as plc
import planning_store as ps
from issues_lib import CommentRecord, FixtureIssuesStore
from planning.backends.issues import IssueStoreBackend
from planning.backends.issues_helpers import r6_canonical_body
from planning_canonical import (
    BODY_SIZE_LIMIT,
    compose_issue_body,
    load_chunk_manifest,
    operator_body_from_canonical,
)
from planning_linear_canonical import LINEAR_OVERFLOW_COMMENT_ID_UTF8_LEN, _utf8_byte_len

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "prd358_facade_double_chunk.json"
UUID_MINTING_DOUBLE = "uuid-minting-issuestorebackend-double"
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_LINEAR_ACTOR = "linear-uuid-double-actor"


def _load_fixture() -> dict[str, Any]:
    data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert data["name"] == UUID_MINTING_DOUBLE
    assert int(data["overflowChunkCount"]) >= int(data["minOverflowChunks"])
    assert int(data["headBytesAfterRewrite"]) == int(data["linearLimitBytes"]) == BODY_SIZE_LIMIT
    return data


def _operator_from_fixture(data: dict[str, Any]) -> str:
    return str(data["markers"]) + str(data["title"]) + str(data["repeatLine"]) * int(data["repeatCount"])


def _prd_content(unit_id: str, operator: str) -> str:
    return (
        f"---\n"
        f"id: {unit_id}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"---\n"
        f"{operator}"
    )


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor").mkdir(parents=True, exist_ok=True)


def _linear_issue_store_cfg(project_key: str) -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "linear",
                "projectKey": project_key,
                "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
            }
        },
        "host": {"provider": "github"},
    }


class UuidMintingLinearStore(FixtureIssuesStore):
    """Linear-shaped adapter: mint 36-char UUIDs and still run prepare_body_with_overflow."""

    def __init__(self, path: Path | None = None) -> None:
        super().__init__(path)
        self.prepare_overflow_ops: list[str] = []

    def authenticated_principal_id(self) -> str:
        return _LINEAR_ACTOR

    def add_comment(
        self,
        issue_id: str,
        body: str,
        *,
        markers: list[str] | None = None,
        author_id: str = "",
    ) -> CommentRecord:
        record = self._resolve_get(issue_id)
        created_at = str(int(time.time()))
        comment_id = str(uuid.uuid4())
        comment = CommentRecord(
            id=comment_id,
            body=body,
            created_at=created_at,
            markers=list(markers or []),
            author_id=author_id or _LINEAR_ACTOR,
            revision=created_at,
        )
        record.comments.append(comment)
        record.touch()
        self._persist()
        return comment

    def _post_overflow(self, issue_id: str, extra: list[CommentRecord], head: str) -> None:
        posted_ids: list[str] = []
        for comment in extra:
            posted = self.add_comment(
                issue_id,
                comment.body,
                markers=list(comment.markers),
                author_id=_LINEAR_ACTOR,
            )
            posted_ids.append(posted.id)
        rewritten = pc.rewrite_chunk_manifest_ids(head, posted_ids)
        if rewritten != head:
            self.update(issue_id, body=rewritten)

    def create(self, **kwargs: Any) -> Any:
        body = str(kwargs.get("body") or "")
        head, extra = plc.prepare_body_with_overflow(body, [])
        self.prepare_overflow_ops.append("create")
        kwargs = {**kwargs, "body": head}
        record = super().create(**kwargs)
        if extra:
            self._post_overflow(record.id, extra, head)
            record = self.get(record.id)
        return record

    def update(self, issue_id: str, **kwargs: Any) -> Any:
        body = kwargs.get("body")
        extra: list[CommentRecord] = []
        if body is not None:
            head, extra = plc.prepare_body_with_overflow(body, [])
            self.prepare_overflow_ops.append("update")
            kwargs = {**kwargs, "body": head}
        else:
            self.prepare_overflow_ops.append("update")
        record = super().update(issue_id, **kwargs)
        if extra:
            self._post_overflow(issue_id, extra, str(kwargs.get("body") or ""))
            record = self.get(issue_id)
        return record


def _backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_key: str,
    *,
    uuid_minting: bool,
) -> tuple[IssueStoreBackend, UuidMintingLinearStore | FixtureIssuesStore]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    monkeypatch.chdir(tmp_path)
    cfg = _linear_issue_store_cfg(project_key)
    (tmp_path / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    backend = IssueStoreBackend(tmp_path, cfg)
    store_path = tmp_path / ".cursor/hooks/state/issue-store-fixture.json"
    store: UuidMintingLinearStore | FixtureIssuesStore
    if uuid_minting:
        store = UuidMintingLinearStore(store_path)
    else:
        store = FixtureIssuesStore(store_path)
    backend._client._fixture = store
    return backend, store


def _overflow_comments(record: Any) -> list[Any]:
    return [c for c in record.comments if "sw-chunk-overflow" in (c.markers or [])]


def _assert_uuid_comment_ids(record: Any) -> list[str]:
    overflow = _overflow_comments(record)
    assert overflow, "expected Linear overflow comments"
    for comment in overflow:
        cid = comment.id
        assert not str(cid).startswith("comment-"), cid
        assert _UUID_RE.fullmatch(str(cid)), cid
        assert len(str(cid).encode("utf-8")) == LINEAR_OVERFLOW_COMMENT_ID_UTF8_LEN
    manifest = load_chunk_manifest(record.body)
    assert manifest is not None
    posted = [str(entry["commentId"]) for entry in manifest["chunks"] if isinstance(entry, dict)]
    comment_by_id = {c.id: c for c in record.comments}
    for cid in posted:
        assert cid in comment_by_id, cid
        assert "sw-chunk-overflow" in (comment_by_id[cid].markers or [])
    return posted


def _pre_chunk_body(project_key: str, unit_id: str, content: str) -> str:
    store_content = operator_body_from_canonical(content) if pc.has_raw_yaml_frontmatter(content) else content
    return compose_issue_body(project_key, "prd", unit_id, store_content)


def _assert_r6_round_trip(record: Any, pre_chunk_body: str) -> None:
    reassembled = ps.strip_markers_and_edges(
        ps.reassemble_body(record.body, record.comments, linear_bind=True)
    )
    expected = ps.strip_markers_and_edges(pre_chunk_body)
    assert r6_canonical_body(expected, issues_provider="linear", ps_mod=ps) == r6_canonical_body(
        reassembled, issues_provider="linear", ps_mod=ps
    )
    assert _utf8_byte_len(record.body) == BODY_SIZE_LIMIT


def test_fixture_documents_three_plus_overflow_and_60k_head() -> None:
    """Named corpus: ≥3 overflow chunks and a 60,000-byte head after UUID rewrite."""
    fixture = _load_fixture()
    operator = _operator_from_fixture(fixture)
    head, extras = pc.chunk_body_if_needed(operator, [], provider="linear")
    assert len(extras) == int(fixture["overflowChunkCount"])
    assert len(extras) >= int(fixture["minOverflowChunks"])
    posted = [str(uuid.uuid4()) for _ in extras]
    rewritten = pc.rewrite_chunk_manifest_ids(head, posted)
    assert _utf8_byte_len(rewritten) == int(fixture["headBytesAfterRewrite"])
    assert _utf8_byte_len(rewritten) <= int(fixture["linearLimitBytes"])


def test_comment_n_skip_path_is_not_this_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E — fixture comment-N ids are not the UUID-minting production split."""
    fixture = _load_fixture()
    project_key = "uuid-double-comment-n"
    unit_id = "358-prd-uuid-comment-n"
    _init_repo(tmp_path)
    backend, store = _backend(tmp_path, monkeypatch, project_key, uuid_minting=False)
    content = _prd_content(unit_id, _operator_from_fixture(fixture))
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"
    result = backend.put(unit_id, body_path, content)
    assert result.verdict == "ok"
    record = store.find_by_unit(project_key, unit_id)
    assert record is not None
    ids = [c.id for c in _overflow_comments(record)]
    assert ids
    assert all(cid.startswith("comment-") for cid in ids)
    assert not any(_UUID_RE.fullmatch(cid) for cid in ids)


def test_put_get_materialize_uuid_double_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Z/O/M/B/I — ≥3 UUID overflow chunks, 60k head, put/get/materialize R6 match."""
    fixture = _load_fixture()
    project_key = "uuid-double-roundtrip"
    unit_id = "358-prd-uuid-roundtrip"
    _init_repo(tmp_path)
    backend, store = _backend(tmp_path, monkeypatch, project_key, uuid_minting=True)
    content = _prd_content(unit_id, _operator_from_fixture(fixture))
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"
    pre_chunk = _pre_chunk_body(project_key, unit_id, content)

    put = backend.put(unit_id, body_path, content)
    assert put.verdict == "ok"
    record = store.find_by_unit(project_key, unit_id)
    assert record is not None
    ids = _assert_uuid_comment_ids(record)
    assert len(ids) >= int(fixture["minOverflowChunks"])
    _assert_r6_round_trip(record, pre_chunk)

    got = backend.get(unit_id, body_path)
    assert got.verdict == "ok"
    assert got.content
    dest = tmp_path / "materialized" / f"{unit_id}.md"
    materialized = backend.materialize(unit_id, body_path, dest)
    assert materialized.verdict == "ok"
    assert dest.is_file()
    assert dest.read_text(encoding="utf-8") == got.content
    assert ps.PUT_INCOMPLETE_LABEL not in record.labels


def test_update_still_runs_prepare_body_with_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S — update/retry still invokes prepare_body_with_overflow; skip-on-manifest holds."""
    fixture = _load_fixture()
    project_key = "uuid-double-update"
    unit_id = "358-prd-uuid-update"
    _init_repo(tmp_path)
    backend, store = _backend(tmp_path, monkeypatch, project_key, uuid_minting=True)
    assert isinstance(store, UuidMintingLinearStore)
    content = _prd_content(unit_id, _operator_from_fixture(fixture))
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"
    first = backend.put(unit_id, body_path, content)
    assert first.verdict == "ok"
    store.prepare_overflow_ops.clear()

    calls: list[dict[str, Any]] = []
    orig = plc.prepare_body_with_overflow

    def _spy(body: str, comments: list[Any] | None = None) -> tuple[str, list[Any]]:
        head, extra = orig(body, comments)
        calls.append(
            {
                "hadManifest": load_chunk_manifest(body) is not None,
                "extra": len(extra),
                "headBytes": _utf8_byte_len(head),
            }
        )
        return head, extra

    monkeypatch.setattr(plc, "prepare_body_with_overflow", _spy)
    retry = backend.put(unit_id, body_path, content)
    assert retry.verdict == "ok"
    assert "update" in store.prepare_overflow_ops
    manifested_updates = [c for c in calls if c["hadManifest"]]
    assert manifested_updates, calls
    assert all(c["extra"] == 0 for c in manifested_updates)
    record = store.find_by_unit(project_key, unit_id)
    assert record is not None
    _assert_uuid_comment_ids(record)
    _assert_r6_round_trip(record, _pre_chunk_body(project_key, unit_id, content))


def test_restart_recovery_converges_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S — crash mid-overflow, retry resumes the same issue and reconstructs."""
    fixture = _load_fixture()
    project_key = "uuid-double-restart"
    unit_id = "358-prd-uuid-restart"
    _init_repo(tmp_path)
    backend, store = _backend(tmp_path, monkeypatch, project_key, uuid_minting=True)
    content = _prd_content(unit_id, _operator_from_fixture(fixture))
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"

    orig_comment = backend._client.issue_comment
    posted = {"n": 0}

    def _fail_after_one(issue_id: str, body: str, *, markers: list[str] | None = None, **kwargs: Any):
        posted["n"] += 1
        if posted["n"] == 1:
            result = orig_comment(issue_id, body, markers=markers, **kwargs)
            raise RuntimeError("simulated-overflow-crash")
        return orig_comment(issue_id, body, markers=markers, **kwargs)

    monkeypatch.setattr(backend._client, "issue_comment", _fail_after_one)
    with pytest.raises(RuntimeError, match="simulated-overflow-crash"):
        backend.put(unit_id, body_path, content)

    first_id = store.find_by_unit(project_key, unit_id)
    assert first_id is not None
    crash_issue_id = first_id.id
    monkeypatch.setattr(backend._client, "issue_comment", orig_comment)

    retry = backend.put(unit_id, body_path, content)
    assert retry.verdict == "ok"
    record = store.find_by_unit(project_key, unit_id)
    assert record is not None
    assert record.id == crash_issue_id
    ids = _assert_uuid_comment_ids(record)
    assert len(ids) >= int(fixture["minOverflowChunks"])
    _assert_r6_round_trip(record, _pre_chunk_body(project_key, unit_id, content))
    got = backend.get(unit_id, body_path)
    assert got.verdict == "ok"
