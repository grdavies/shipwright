"""PRD 359 R8–R10 / R14 — Markdown-aware Linear splits and fail-closed oversized constructs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import json
import subprocess
from typing import Any

import planning_canonical as pc
import planning_store as ps
from planning.backends.issues import IssueStoreBackend
from planning_canonical import BODY_SIZE_LIMIT, CommentRecord, chunk_body_if_needed
from planning_linear_canonical import (
    LinearOversizedConstructError,
    _split_overflow_comments,
    _split_positions,
    _utf8_byte_len,
    chunk_body_for_linear,
    linear_public_markdown_equivalent,
)
from planning.backends.issues import scan_put_payloads
from planning.backends.issues_helpers import reconstruct_bodies_equivalent

UNIQUE = "SPAN-TOKEN-NEVER-IN-ERROR-prd359"
REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_BRANCH = "feat/linear-public-markdown-remaining"
PRD_358_MATERIALIZED = (
    REPO_ROOT
    / ".cursor"
    / "planning-materialized"
    / "docs"
    / "prds"
    / "358-linear-issue-store-fidelity"
)
PRD_357_DIR = REPO_ROOT / "docs" / "prds" / "357-linear-issue-store-production-readiness"
TIE7_UNIT_ID = "tie-7-journal"


def _assert_no_interior_cuts(text: str, start: int, end: int) -> None:
    for pos in _split_positions(text):
        assert not (start < pos < end), f"illegal cut {pos} inside [{start},{end})"


class TestPrd359SplitPositions:
    def test_no_cut_inside_inline_code(self) -> None:
        text = f"before `{UNIQUE} interior` after\n"
        start = text.index("`")
        end = text.rindex("`") + 1
        _assert_no_interior_cuts(text, start, end)

    def test_no_cut_inside_markdown_link(self) -> None:
        text = f"see [{UNIQUE}](https://example.com/{UNIQUE}) please\n"
        start = text.index("[")
        end = text.index(")") + 1
        _assert_no_interior_cuts(text, start, end)

    def test_no_cut_inside_emphasis_run(self) -> None:
        text = f"keep **{UNIQUE} bold** here\n"
        start = text.index("**")
        end = text.rindex("**") + 2
        _assert_no_interior_cuts(text, start, end)

    def test_no_cut_inside_fenced_code(self) -> None:
        text = f"intro\n```\n{UNIQUE}\nstill-inside\n```\nout\n"
        start = text.index("```")
        end = text.rindex("```") + 3
        _assert_no_interior_cuts(text, start, end)

    def test_no_cut_inside_gfm_table(self) -> None:
        text = f"| Col | {UNIQUE} |\n| --- | --- |\n| a | b |\n\n"
        start = 0
        end = text.rindex("|") + 1
        _assert_no_interior_cuts(text, start, end)

    def test_cuts_allowed_immediately_before_and_after_span(self) -> None:
        text = f"aa `{UNIQUE}` bb\n"
        start = text.index("`")
        end = text.rindex("`") + 1
        positions = set(_split_positions(text))
        assert start in positions
        assert end in positions


class TestPrd359OversizedClosedSet:
    def test_oversized_inline_code_raises_opaque_typed_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import planning_linear_canonical as llc

        monkeypatch.setattr(llc, "_LINEAR_CHUNK_LIMIT", 64)
        inner = UNIQUE + ("x" * 80)
        body = f"`{inner}`"
        with pytest.raises(LinearOversizedConstructError) as exc:
            chunk_body_for_linear(body, [])
        err = exc.value
        assert err.kind == "inline-code"
        assert err.code == "oversized-closed-set"
        assert err.length == _utf8_byte_len(body)
        payload = str(err)
        assert UNIQUE not in payload
        parsed = json.loads(payload)
        assert parsed == {"code": "oversized-closed-set", "kind": "inline-code", "length": err.length}

    def test_overflow_does_not_fallback_max_prefix_inside_fence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import planning_linear_canonical as llc

        monkeypatch.setattr(llc, "_LINEAR_CHUNK_LIMIT", 80)

        def _boom(text: str, max_bytes: int) -> int:
            raise AssertionError("_max_prefix_chars must not run inside closed-set")

        monkeypatch.setattr(llc, "_max_prefix_chars", _boom)
        fence = f"```\n{UNIQUE}\n" + ("y" * 120) + "\n```"
        with pytest.raises(LinearOversizedConstructError) as exc:
            _split_overflow_comments(fence, [], write_token="0" * 12)
        assert exc.value.kind == "fenced-code"
        assert UNIQUE not in str(exc.value)

    def test_plain_text_still_chunks_without_closed_set_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import planning_linear_canonical as llc

        monkeypatch.setattr(llc, "_LINEAR_CHUNK_LIMIT", 200)
        remaining = "z" * 800
        comments = llc._split_overflow_comments(remaining, [], write_token="0" * 12)
        assert comments
        assert all(UNIQUE not in (c.body or "") for c in comments)
        for comment in comments:
            assert "sw-chunk-overflow" in (comment.markers or [])


class TestPrd359SecretScanContract:
    def test_scan_put_payloads_covers_pre_chunk_head_and_overflow(self) -> None:
        seen: list[str] = []

        def guard(*texts: str, path_hint: str | None = None) -> None:
            seen.extend([t for t in texts if t])

        overflows = [
            CommentRecord(id="c1", body="overflow-one", markers=["sw-chunk-overflow"]),
            CommentRecord(id="c2", body="overflow-two", markers=["sw-chunk-overflow"]),
        ]
        scan_put_payloads(
            guard,
            pre_chunk_body="PRE-CHUNK",
            head="HEAD-BODY",
            overflow_bodies=[c.body for c in overflows],
            path_hint="docs/prds/359.md",
        )
        assert seen == ["PRE-CHUNK", "HEAD-BODY", "overflow-one", "overflow-two"]

    def test_scan_put_payloads_is_the_absorb_surface(self) -> None:
        src = Path(__file__).resolve().parents[2] / "planning" / "backends" / "issues.py"
        text = src.read_text(encoding="utf-8")
        assert "GAP-474" in text and "GAP-475" in text
        assert "scan_put_payloads(" in text


class _Ps:
    @staticmethod
    def strip_markers_and_edges(text: str) -> str:
        return text

    @staticmethod
    def fail(message: str, **_kwargs: object) -> None:
        raise AssertionError(message)


class TestPrd359ReconstructEquivalent:
    def test_comparison_form_mismatch_is_not_equivalent(self) -> None:
        left = "See [docs](https://example.com/a) please\n"
        right = "See [docs](https://example.com/b) please\n"
        assert linear_public_markdown_equivalent(left, right) is False
        assert (
            reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=_Ps)
            is False
        )

    def test_identity_token_equality_alone_is_not_ok(self) -> None:
        left = "## R1 Title\n\nBody.\n"
        right = "R1 Title\n\nBody.\n"
        assert linear_public_markdown_equivalent(left, right) is False
        assert (
            reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=_Ps)
            is False
        )

    def test_escaped_unmatched_ticks_are_not_equal_code_tokens(self) -> None:
        left = "use `code` here\n"
        right = "use \\`code\\` here\n"
        assert linear_public_markdown_equivalent(left, right) is False
        assert (
            reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=_Ps)
            is False
        )

    def test_enumerated_rewrite_still_equivalent(self) -> None:
        left = "hello  world\n"
        right = "hello world\n"
        assert reconstruct_bodies_equivalent(
            left, right, issues_provider="linear", ps_mod=_Ps
        ) is linear_public_markdown_equivalent(left, right)

    def test_github_provider_does_not_call_linear_equivalent(self) -> None:
        left = "same-bytes"
        right = "same-bytes"
        assert (
            reconstruct_bodies_equivalent(left, right, issues_provider="github", ps_mod=_Ps)
            is True
        )


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(provider: str, project_key: str) -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": provider,
                "projectKey": project_key,
            }
        },
        "host": {"provider": "github"},
    }


def _backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str, project_key: str
) -> IssueStoreBackend:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    monkeypatch.chdir(tmp_path)
    cfg = _issue_store_cfg(provider, project_key)
    (tmp_path / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return IssueStoreBackend(tmp_path, cfg)


def _fail_payload(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    captured = capsys.readouterr()
    start = captured.out.find("{")
    if start < 0:
        raise AssertionError(f"no fail json in stdout: {captured.out!r}")
    return json.loads(captured.out[start:])


class TestPrd359ProviderNoOpAndTie7Journal:
    def test_github_chunk_output_unchanged_vs_default(self) -> None:
        body = "Z" * (BODY_SIZE_LIMIT + 64)
        head_default, comments_default = chunk_body_if_needed(body, [], provider=None)
        head_github, comments_github = chunk_body_if_needed(body, [], provider="github-issues")
        assert len(comments_github) == len(comments_default) == 1
        assert [c.body for c in comments_github] == [c.body for c in comments_default]
        assert pc.load_chunk_manifest(head_github) is not None
        assert pc.load_chunk_manifest(head_default) is not None

    def test_non_linear_providers_do_not_invoke_linear_chunker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = "Z" * (BODY_SIZE_LIMIT + 64)

        def _boom(*_args: object, **_kwargs: object) -> tuple[str, list[CommentRecord]]:
            raise AssertionError("linear chunker must not run for non-linear providers")

        monkeypatch.setattr(
            "planning_linear_canonical.chunk_body_for_linear",
            _boom,
        )
        chunk_body_if_needed(body, [], provider="github-issues")
        chunk_body_if_needed(body, [], provider="notion")

    def test_github_put_skips_linear_reconstruct_before_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        def _track(*_args: object, **_kwargs: object) -> object:
            calls.append("verify")
            raise AssertionError("linear reconstruct-before-ok must not run for GitHub")

        monkeypatch.setattr(
            "planning.backends.issues_helpers.verify_reconstruct_before_ok",
            _track,
        )
        _init_repo(tmp_path)
        backend = _backend(tmp_path, monkeypatch, "github-issues", "prd359-github-noop")
        unit_id = "359-prd-github-reconstruct-noop"
        body_path = f"docs/prds/{unit_id}/{unit_id}.md"
        content = (
            f"---\nid: {unit_id}\ntype: prd\nstatus: open\nvisibility: public\n---\n"
            f"# GitHub reconstruct gate\n\nSmall body.\n"
        )
        assert backend.put(unit_id, body_path, content).verdict == "ok"
        assert calls == []

    def test_tie7_put_incomplete_not_cleared_as_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """R13/D3 — TIE-7 stays sw:put-incomplete; freeze is not ok."""
        _init_repo(tmp_path)
        backend = _backend(tmp_path, monkeypatch, "linear", "prd359-tie7")
        unit_id = TIE7_UNIT_ID
        body_path = f"docs/prds/{unit_id}/{unit_id}.md"
        content = (
            f"---\nid: {unit_id}\ntype: prd\nstatus: open\nvisibility: public\n---\n"
            f"# TIE-7 journal\n\nStuck put-incomplete witness.\n"
        )
        put_result = backend.put(unit_id, body_path, content)
        assert put_result.verdict == "ok"
        fixture = backend._client._require_fixture()
        record = fixture.find_by_unit("prd359-tie7", unit_id)
        assert record is not None
        stuck_labels = sorted(set(record.labels) | {ps.PUT_INCOMPLETE_LABEL})
        record = backend._client.issue_label(record.id, stuck_labels, if_match=record.etag)

        with pytest.raises(SystemExit):
            backend.freeze(unit_id, body_path, distill=False, pre_chunk_body=content)
        payload = _fail_payload(capsys)
        assert payload["code"] == "reconstruct-mismatch"
        assert payload.get("reason") == "put-incomplete"

        record = backend._client.issue_get(record.id)
        assert ps.PUT_INCOMPLETE_LABEL in record.labels

    def test_frozen_prd358_materialized_not_amended_vs_integration(self) -> None:
        if not PRD_358_MATERIALIZED.is_dir():
            pytest.skip("PRD 358 materialized tree not present")
        rel = PRD_358_MATERIALIZED.relative_to(REPO_ROOT).as_posix()
        diff = subprocess.run(
            ["git", "diff", "--name-only", INTEGRATION_BRANCH, "--", rel],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if diff.returncode != 0:
            pytest.skip(f"cannot diff against {INTEGRATION_BRANCH}")
        changed = [line for line in diff.stdout.splitlines() if line.strip()]
        assert changed == [], f"PRD 358 materialized must not be amended: {changed}"

    def test_frozen_prd357_docs_not_amended_vs_integration(self) -> None:
        if not PRD_357_DIR.is_dir():
            pytest.skip("PRD 357 docs tree not present")
        rel = PRD_357_DIR.relative_to(REPO_ROOT).as_posix()
        diff = subprocess.run(
            ["git", "diff", "--name-only", INTEGRATION_BRANCH, "--", rel],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if diff.returncode != 0:
            pytest.skip(f"cannot diff against {INTEGRATION_BRANCH}")
        changed = [line for line in diff.stdout.splitlines() if line.strip()]
        assert changed == [], f"PRD 357 must not be amended: {changed}"
