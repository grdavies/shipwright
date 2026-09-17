"""PRD 358 R3 / D5 — reconstruct-before-ok on chunked Linear issue-store puts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_canonical as pc
import planning_store as ps
from issues_lib import FixtureIssuesStore
from planning.backends.issues import IssueStoreBackend
from planning_canonical import BODY_SIZE_LIMIT, compose_issue_body

_ORACLE_FIXTURE = Path(__file__).parent / "fixtures" / "prd358_reconstruct_oracle.json"
_FACADE_REPRO = Path(__file__).parent / "fixtures" / "prd358_facade_double_chunk_repro.json"

# Live 2.19.0 dogfood repro: truncated reassembly vs full pre-chunk body (R3 oracle).
ORACLE_EXPECTED_BYTES = 194_480
ORACLE_TRUNCATED_BYTES = 57_881


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


def _chunked_prd_content(project_key: str, unit_id: str) -> str:
    """Sized for Linear chunking with a byte-exact reassembly round trip."""
    prefix = "# Title\n\n"
    composed_probe = compose_issue_body(project_key, "prd", unit_id, "X")
    marker_len = composed_probe.index("X")
    target = BODY_SIZE_LIMIT - marker_len - len(prefix) - 2
    head = prefix + ("A" * target) + "\n\n"
    tail = "Paragraph tail for reconstruct-before-ok.\n\nEND"
    operator = head + tail
    return (
        f"---\n"
        f"id: {unit_id}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"---\n"
        f"{operator}"
    )


def _backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_key: str) -> IssueStoreBackend:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    monkeypatch.chdir(tmp_path)
    cfg = _linear_issue_store_cfg(project_key)
    (tmp_path / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return IssueStoreBackend(tmp_path, cfg)


def _fail_payload(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    captured = capsys.readouterr()
    start = captured.out.find("{")
    if start < 0:
        raise AssertionError(f"no fail json in stdout: {captured.out!r}")
    return json.loads(captured.out[start:])


def test_chunked_put_passes_reconstruct_and_clears_put_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_repo(tmp_path)
    project_key = "reconstruct-ok-pass"
    unit_id = "358-prd-reconstruct-pass"
    backend = _backend(tmp_path, monkeypatch, project_key)
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"
    content = _chunked_prd_content(project_key, unit_id)
    result = backend.put(unit_id, body_path, content)
    assert result.verdict == "ok"
    assert result.content == content

    store = FixtureIssuesStore(tmp_path / ".cursor/hooks/state/issue-store-fixture.json")
    record = store.find_by_unit(project_key, unit_id)
    assert record is not None
    assert ps.PUT_INCOMPLETE_LABEL not in record.labels


def test_reconstruct_incomplete_comments_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_repo(tmp_path)
    project_key = "reconstruct-incomplete"
    unit_id = "358-prd-reconstruct-incomplete"
    backend = _backend(tmp_path, monkeypatch, project_key)
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"
    content = _chunked_prd_content(project_key, unit_id)

    orig_get = backend._client.issue_get

    def incomplete_get(issue_id: str):
        record = orig_get(issue_id)
        if pc.load_chunk_manifest(record.body):
            record.comments_complete = False
        return record

    monkeypatch.setattr(backend._client, "issue_get", incomplete_get)

    with pytest.raises(SystemExit) as exc:
        backend.put(unit_id, body_path, content)
    assert exc.value.code == 2
    payload = _fail_payload(capsys)
    assert payload["code"] == "reconstruct-incomplete-comments"

    store = FixtureIssuesStore(tmp_path / ".cursor/hooks/state/issue-store-fixture.json")
    record = store.find_by_unit(project_key, unit_id)
    assert record is not None
    assert ps.PUT_INCOMPLETE_LABEL in record.labels


def test_reconstruct_missing_overflow_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_repo(tmp_path)
    project_key = "reconstruct-missing-overflow"
    unit_id = "358-prd-reconstruct-missing"
    backend = _backend(tmp_path, monkeypatch, project_key)
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"
    content = _chunked_prd_content(project_key, unit_id)

    orig_reassemble = ps.reassemble_body

    def drop_overflow(body: str, comments: list, **kwargs: Any) -> str:
        if pc.load_chunk_manifest(body):
            return orig_reassemble(body, [], **kwargs)
        return orig_reassemble(body, comments, **kwargs)

    monkeypatch.setattr(ps, "reassemble_body", drop_overflow)

    with pytest.raises(SystemExit):
        backend.put(unit_id, body_path, content)
    payload = _fail_payload(capsys)
    assert payload["code"] == "reconstruct-mismatch"

    store = FixtureIssuesStore(tmp_path / ".cursor/hooks/state/issue-store-fixture.json")
    record = store.find_by_unit(project_key, unit_id)
    assert record is not None
    assert ps.PUT_INCOMPLETE_LABEL in record.labels


def test_reconstruct_unreferenced_overflow_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Manifest references overflow ids that are not present on the refetched issue."""
    _init_repo(tmp_path)
    project_key = "reconstruct-unreferenced"
    unit_id = "358-prd-reconstruct-unreferenced"
    backend = _backend(tmp_path, monkeypatch, project_key)
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"
    content = _chunked_prd_content(project_key, unit_id)

    orig_reassemble = ps.reassemble_body

    def unreferenced_overflow(body: str, comments: list, **kwargs: Any) -> str:
        manifest = pc.load_chunk_manifest(body)
        if manifest and isinstance(manifest.get("chunks"), list) and manifest["chunks"]:
            return orig_reassemble(body, [], **kwargs)
        return orig_reassemble(body, comments, **kwargs)

    monkeypatch.setattr(ps, "reassemble_body", unreferenced_overflow)

    with pytest.raises(SystemExit):
        backend.put(unit_id, body_path, content)
    payload = _fail_payload(capsys)
    assert payload["code"] == "reconstruct-mismatch"

    store = FixtureIssuesStore(tmp_path / ".cursor/hooks/state/issue-store-fixture.json")
    record = store.find_by_unit(project_key, unit_id)
    assert record is not None
    assert ps.PUT_INCOMPLETE_LABEL in record.labels


def test_reconstruct_nested_overflow_manifest_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nested sw-chunk-manifest inside overflow must not satisfy reconstruct-before-ok."""
    _init_repo(tmp_path)
    project_key = "reconstruct-nested"
    unit_id = "358-prd-reconstruct-nested"
    backend = _backend(tmp_path, monkeypatch, project_key)
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"
    content = _chunked_prd_content(project_key, unit_id)

    orig_reassemble = ps.reassemble_body

    def nested_overflow(body: str, comments: list, **kwargs: Any) -> str:
        if pc.load_chunk_manifest(body) and comments:
            return orig_reassemble(body, [], **kwargs)
        return orig_reassemble(body, comments, **kwargs)

    monkeypatch.setattr(ps, "reassemble_body", nested_overflow)

    with pytest.raises(SystemExit):
        backend.put(unit_id, body_path, content)
    payload = _fail_payload(capsys)
    assert payload["code"] == "reconstruct-mismatch"

    store = FixtureIssuesStore(tmp_path / ".cursor/hooks/state/issue-store-fixture.json")
    record = store.find_by_unit(project_key, unit_id)
    assert record is not None
    assert ps.PUT_INCOMPLETE_LABEL in record.labels


def test_facade_double_chunk_oracle_bytes_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Named 2.19.0 repro: truncated reconstruct must not return ok (194480 vs 57881)."""
    oracle = json.loads(_ORACLE_FIXTURE.read_text(encoding="utf-8"))
    repro = json.loads(_FACADE_REPRO.read_text(encoding="utf-8"))
    assert oracle["fixture"] == repro["name"]
    assert oracle["expectedCanonicalBytes"] == ORACLE_EXPECTED_BYTES
    assert oracle["truncatedReassemblyBytes"] == ORACLE_TRUNCATED_BYTES

    _init_repo(tmp_path)
    project_key = "reconstruct-oracle"
    unit_id = "358-prd-linear-issue-store-fidelity"
    backend = _backend(tmp_path, monkeypatch, project_key)
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"
    body = (
        str(repro["markers"])
        + str(repro["title"])
        + str(repro["repeatLine"]) * int(repro["repeatCount"])
    )
    content = (
        f"---\n"
        f"id: {unit_id}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"---\n"
        f"{body}"
    )

    orig_reassemble = ps.reassemble_body

    def truncated_oracle(body_text: str, comments: list, **kwargs: Any) -> str:
        if pc.load_chunk_manifest(body_text):
            return "z" * ORACLE_TRUNCATED_BYTES
        return orig_reassemble(body_text, comments, **kwargs)

    monkeypatch.setattr(ps, "reassemble_body", truncated_oracle)

    with pytest.raises(SystemExit):
        backend.put(unit_id, body_path, content)
    payload = _fail_payload(capsys)
    assert payload["code"] == "reconstruct-mismatch"
    assert payload["actualBytes"] == ORACLE_TRUNCATED_BYTES
    assert payload["expectedBytes"] > payload["actualBytes"]

    store = FixtureIssuesStore(tmp_path / ".cursor/hooks/state/issue-store-fixture.json")
    record = store.find_by_unit(project_key, unit_id)
    assert record is not None
    assert ps.PUT_INCOMPLETE_LABEL in record.labels
