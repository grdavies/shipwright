#!/usr/bin/env python3
"""Provider-aware Jira chunking in the standard write path fixture (PRD 057 R9).

Proves, fully offline and deterministically (fixture issues store, no
network):

1. **Jira's ADF payload limit is far tighter than the generic byte limit** —
   a body well under the generic `BODY_SIZE_LIMIT` (60,000 raw bytes) can
   still exceed Jira Cloud's ADF description limit (`JIRA_CLOUD_DESCRIPTION_
   LIMIT`, ~32KB of JSON) once converted, which is exactly what
   `JiraIssuesClient.create`/`.update` reject with a `RuntimeError` today.
2. **`chunk_body_if_needed(provider="jira")` pre-chunks that body** — so it
   never reaches the client at all; the result matches calling
   `chunk_body_for_jira_cloud` directly (the behavior is ported in, not
   duplicated).
3. **Non-Jira providers are unaffected** — the same oversized-for-Jira body
   passes through `chunk_body_if_needed` untouched for `provider=None`/
   `"github-issues"`, since it fits the generic limit; providers other than
   Jira never pay a chunking cost they don't need.
4. **Many: a much larger body chunks into multiple Jira-sized comments** —
   every chunk (the head description and each overflow comment) individually
   fits `JIRA_CLOUD_DESCRIPTION_LIMIT`.
5. **The standard write path (`IssueStoreBackend.put`) produces a Jira-safe
   body end to end** — with `issuesProvider: jira`, `put` never sends the
   client a body/comment over the ADF limit, and `get` reassembles it
   byte-exact.
6. **Zero: a small Jira body is untouched** — same zero-chunking behavior as
   the generic path.

No network, no live Jira required (`SW_ISSUES_FIXTURE=1`; the fixture issues
store persists markdown directly, so this exercises the size-based
pre-chunking decision itself, independent of live ADF wire conversion).

ZOMBIES: Zero (small body) · Boundaries (Jira ADF limit vs generic byte
limit) · Many (multi-chunk oversized body) · Exceptions (client would reject
if not pre-chunked) · Interfaces (provider-aware `chunk_body_if_needed`).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

os.environ.setdefault("SW_ISSUES_FIXTURE", "1")

from planning_canonical import BODY_SIZE_LIMIT, chunk_body_if_needed, compose_issue_body  # noqa: E402
from planning_jira_canonical import (  # noqa: E402
    JIRA_CLOUD_DESCRIPTION_LIMIT,
    chunk_body_for_jira_cloud,
    jira_adf_payload_size,
)


def _paragraphs(tag: str, n: int) -> str:
    parts = [f"Paragraph {tag}-{i} " + " ".join(["word"] * 10) for i in range(n)]
    return f"# Title {tag}\n\n" + "\n\n".join(parts) + f"\n\nEND-{tag}"


def check_body_over_jira_limit_under_generic_limit() -> dict:
    """The exact scenario R9 targets: fits GitHub, would reject on Jira."""
    body = compose_issue_body("proj", "prd", "unit-x", _paragraphs("R9", 300))
    raw_len = len(body.encode("utf-8"))
    adf_len = jira_adf_payload_size(body)
    ok = raw_len <= BODY_SIZE_LIMIT and adf_len > JIRA_CLOUD_DESCRIPTION_LIMIT
    return {
        "name": "body-over-jira-limit-under-generic-limit",
        "ok": ok,
        "detail": f"rawBytes={raw_len} adfBytes={adf_len} genericLimit={BODY_SIZE_LIMIT} jiraLimit={JIRA_CLOUD_DESCRIPTION_LIMIT}",
    }


def check_jira_provider_prechunks_matching_direct_call() -> dict:
    body = compose_issue_body("proj", "prd", "unit-x", _paragraphs("R9", 300))
    head_delegated, comments_delegated = chunk_body_if_needed(body, [], provider="jira")
    head_direct, comments_direct = chunk_body_for_jira_cloud(body, [])
    matches = head_delegated == head_direct and [c.body for c in comments_delegated] == [
        c.body for c in comments_direct
    ]
    within_limit = jira_adf_payload_size(head_delegated) <= JIRA_CLOUD_DESCRIPTION_LIMIT and all(
        jira_adf_payload_size(c.body) <= JIRA_CLOUD_DESCRIPTION_LIMIT for c in comments_delegated
    )
    ok = head_delegated != body and matches and within_limit
    return {
        "name": "jira-provider-prechunks-matching-direct-call",
        "ok": ok,
        "detail": f"chunked={head_delegated != body} matchesDirect={matches} withinLimit={within_limit} numComments={len(comments_delegated)}",
    }


def check_non_jira_providers_unaffected() -> dict:
    body = compose_issue_body("proj", "prd", "unit-x", _paragraphs("R9", 300))
    head_none, comments_none = chunk_body_if_needed(body, [], provider=None)
    head_gh, comments_gh = chunk_body_if_needed(body, [], provider="github-issues")
    ok = head_none == body and not comments_none and head_gh == body and not comments_gh
    return {
        "name": "non-jira-providers-unaffected",
        "ok": ok,
        "detail": f"providerNoneChunked={head_none != body} providerGithubChunked={head_gh != body}",
    }


def check_multi_chunk_large_jira_body() -> dict:
    body = compose_issue_body("proj", "prd", "unit-x", _paragraphs("R9BIG", 900))
    head, comments = chunk_body_if_needed(body, [], provider="jira")
    all_within_limit = jira_adf_payload_size(head) <= JIRA_CLOUD_DESCRIPTION_LIMIT and all(
        jira_adf_payload_size(c.body) <= JIRA_CLOUD_DESCRIPTION_LIMIT for c in comments
    )
    ok = len(comments) >= 2 and all_within_limit
    return {
        "name": "multi-chunk-large-jira-body",
        "ok": ok,
        "detail": f"numComments={len(comments)} allWithinLimit={all_within_limit}",
    }


def _jira_fixture_root(tmp: str) -> tuple[Path, dict]:
    root = Path(tmp)
    cfg = {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "jira",
                "projectKey": "jira-chunk-fixture",
                "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
            }
        },
        "host": {"provider": "github"},
    }
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root, cfg


def check_standard_write_path_produces_jira_safe_body() -> dict:
    import planning_store as ps
    from issues_lib import FixtureIssuesStore

    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _jira_fixture_root(tmp)
        backend = ps.get_backend(root, cfg)
        ok_provider = backend.issues_provider == "jira"
        content = _paragraphs("WRITEPATH", 900)
        put_result = backend.put("unit-1", "docs/prds/x/x.md", content)
        got = backend.get("unit-1", "docs/prds/x/x.md")
        store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
        record = next(iter(store._issues.values()))
        body_within_limit = jira_adf_payload_size(record.body) <= JIRA_CLOUD_DESCRIPTION_LIMIT
        comments_within_limit = all(
            jira_adf_payload_size(c.body) <= JIRA_CLOUD_DESCRIPTION_LIMIT for c in record.comments
        )
    ok = (
        ok_provider
        and put_result.verdict == "ok"
        and got.content == content
        and body_within_limit
        and comments_within_limit
        and len(record.comments) >= 2
    )
    return {
        "name": "standard-write-path-produces-jira-safe-body",
        "ok": ok,
        "detail": (
            f"provider={backend.issues_provider if ok_provider else 'MISMATCH'} "
            f"exactMatch={got.content == content} bodyWithinLimit={body_within_limit} "
            f"commentsWithinLimit={comments_within_limit} numComments={len(record.comments)}"
        ),
    }


def check_zero_small_jira_body_untouched() -> dict:
    body = compose_issue_body("proj", "prd", "unit-x", "# small\n\nJira body")
    head, comments = chunk_body_if_needed(body, [], provider="jira")
    ok = head == body and not comments
    return {"name": "zero-small-jira-body-untouched", "ok": ok, "detail": f"chunked={head != body}"}


def main() -> int:
    checks = [
        check_body_over_jira_limit_under_generic_limit(),
        check_jira_provider_prechunks_matching_direct_call(),
        check_non_jira_providers_unaffected(),
        check_multi_chunk_large_jira_body(),
        check_standard_write_path_produces_jira_safe_body(),
        check_zero_small_jira_body_untouched(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-jira-chunking",
        "rid": "R9",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
