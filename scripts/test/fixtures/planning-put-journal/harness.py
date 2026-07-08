#!/usr/bin/env python3
"""Partial-write journal + fail-closed manifest rewrite fixture (PRD 057 R26).

Proves, fully offline and deterministically (fixture issues store, no
network):

1. **Zero: a small (unchunked) body never journals** — `put` for a body under
   the chunk threshold never writes a `put-journal` entry and never applies
   `sw:put-incomplete`; there is nothing to resume.
2. **Failure after `issue_create` leaves a resumable journal** — a simulated
   crash between the head write and the first overflow-comment post leaves
   exactly one issue, tagged `sw:put-incomplete`, with a `put-journal` entry
   naming that issue id and step.
3. **Retry converges to one issue** — retrying the same `put` call resolves
   back to the SAME journaled issue (never a duplicate), succeeds, clears the
   journal entry and the `sw:put-incomplete` label, and `get` reassembles the
   original content byte-exact.
4. **`planning-doctor.py` surfaces `put-partial` during the outage** — the
   journal-backed finding names the stuck unit id, issue id, and step, with
   an actionable remediation, and clears once the retry completes.
5. **`planning-doctor.py` surfaces `chunk-cardinality-mismatch` during the
   outage** — the manifest's synthetic placeholder id can never resolve to a
   real comment mid-outage, so the cardinality finding also fires (both
   findings are independent signals of the same underlying interruption),
   and both clear once the retry completes.

No network, no live issue store required (`SW_ISSUES_FIXTURE=1`).

ZOMBIES: Zero (unchunked body, no journal) · One (single chunked put)
· Exceptions (crash after issue_create) · State (journal + label written,
then cleared on convergence) · Interfaces (doctor findings) · Boundaries
(retry resolves to the same issue id, not a duplicate).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

os.environ.setdefault("SW_ISSUES_FIXTURE", "1")

from planning_canonical import BODY_SIZE_LIMIT, compose_issue_body  # noqa: E402


def _load_module(rel_path: str, name: str) -> ModuleType:
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prefix_byte_len(project_key: str, artifact_type: str, unit_id: str) -> int:
    composed = compose_issue_body(project_key, artifact_type, unit_id, "X")
    idx = composed.index("X")
    return len(composed[:idx].encode("utf-8"))


def _clean_overflow_content(project_key: str, artifact_type: str, unit_id: str) -> str:
    """Content sized so the chunk cut lands on a paragraph break, giving a
    byte-exact reassembly round trip (mirrors planning-chunk-reassembly)."""
    prefix = "# Title\n\n"
    target_len = BODY_SIZE_LIMIT - _prefix_byte_len(project_key, artifact_type, unit_id)
    filler_len = target_len - len(prefix) - 2
    head = prefix + ("A" * filler_len) + "\n\n"
    tail = "Paragraph tail content here\n\nEND"
    return head + tail


def _fixture_root(tmp: str, *, project_key: str = "put-journal-fixture") -> tuple[Path, dict]:
    root = Path(tmp)
    cfg = {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
                "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
            }
        },
        "host": {"provider": "github"},
    }
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root, cfg


def check_zero_small_body_never_journals() -> dict:
    import planning_store as ps

    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="put-journal-zero")
        backend = ps.get_backend(root, cfg)
        backend.put("unit-1", "docs/prds/x/x.md", "# small body\n\ncontent")
        journal = ps.load_put_journal(root)
        from issues_lib import FixtureIssuesStore

        store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
        record = next(iter(store._issues.values()))
    ok = not journal and ps.PUT_INCOMPLETE_LABEL not in record.labels
    return {
        "name": "zero-small-body-never-journals",
        "ok": ok,
        "detail": f"journalEntries={len(journal)} labels={record.labels}",
    }


def _simulate_crash_after_create(root: Path, cfg: dict, unit_id: str, content: str):
    import planning_store as ps

    backend = ps.get_backend(root, cfg)

    def boom(*_a, **_k):
        raise RuntimeError("simulated crash after issue_create")

    backend._client.issue_comment = boom
    raised = False
    try:
        backend.put(unit_id, "docs/prds/x/x.md", content)
    except RuntimeError:
        raised = True
    return raised


def check_crash_after_create_leaves_resumable_journal() -> dict:
    import planning_store as ps
    from issues_lib import FixtureIssuesStore

    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="put-journal-crash")
        content = _clean_overflow_content(cfg["planning"]["store"]["projectKey"], "prd", "unit-1")
        raised = _simulate_crash_after_create(root, cfg, "unit-1", content)
        store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
        one_issue = len(store._issues) == 1
        record = next(iter(store._issues.values())) if one_issue else None
        has_label = bool(record) and ps.PUT_INCOMPLETE_LABEL in record.labels
        journal = ps.load_put_journal(root)
        idx_key = ps.issue_index_key(cfg["planning"]["store"]["projectKey"], "unit-1")
        entry = journal.get(idx_key)
    ok = (
        raised
        and one_issue
        and has_label
        and entry is not None
        and entry.get("step") == "body-written"
        and entry.get("issueId") == record.id
        and entry.get("postedCommentIds") == []
    )
    return {
        "name": "crash-after-create-leaves-resumable-journal",
        "ok": ok,
        "detail": f"raised={raised} issues={len(store._issues)} label={has_label} entry={entry}",
    }


def check_retry_converges_to_one_issue() -> dict:
    import planning_store as ps
    from issues_lib import FixtureIssuesStore

    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="put-journal-retry")
        project_key = cfg["planning"]["store"]["projectKey"]
        content = _clean_overflow_content(project_key, "prd", "unit-1")
        _simulate_crash_after_create(root, cfg, "unit-1", content)
        store_mid = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
        issue_id_mid = next(iter(store_mid._issues.values())).id

        backend2 = ps.get_backend(root, cfg)
        result = backend2.put("unit-1", "docs/prds/x/x.md", content)
        got = backend2.get("unit-1", "docs/prds/x/x.md")

        store_final = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
        one_issue = len(store_final._issues) == 1
        record = next(iter(store_final._issues.values()))
        journal = ps.load_put_journal(root)
    ok = (
        result.verdict == "ok"
        and one_issue
        and record.id == issue_id_mid
        and got.content == content
        and ps.PUT_INCOMPLETE_LABEL not in record.labels
        and not journal
    )
    return {
        "name": "retry-converges-to-one-issue",
        "ok": ok,
        "detail": (
            f"putOk={result.verdict == 'ok'} sameIssue={record.id == issue_id_mid} "
            f"exactMatch={got.content == content} labelCleared={ps.PUT_INCOMPLETE_LABEL not in record.labels} "
            f"journalCleared={not journal}"
        ),
    }


def check_doctor_flags_put_partial_during_outage() -> dict:
    doctor = _load_module("scripts/planning-doctor.py", "_put_journal_doctor_1")
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="put-journal-doctor-1")
        content = _clean_overflow_content(cfg["planning"]["store"]["projectKey"], "prd", "unit-1")
        _simulate_crash_after_create(root, cfg, "unit-1", content)
        finding = doctor.put_partial_finding(root)
    ok = (
        finding is not None
        and finding.get("check") == "put-partial"
        and finding.get("status") == "drift"
        and any(u.get("unitId") == "unit-1" for u in finding.get("units") or [])
        and bool(finding.get("remediation"))
    )
    return {"name": "doctor-flags-put-partial-during-outage", "ok": ok, "detail": finding}


def check_doctor_flags_cardinality_mismatch_during_outage() -> dict:
    doctor = _load_module("scripts/planning-doctor.py", "_put_journal_doctor_2")
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="put-journal-doctor-2")
        content = _clean_overflow_content(cfg["planning"]["store"]["projectKey"], "prd", "unit-1")
        _simulate_crash_after_create(root, cfg, "unit-1", content)
        finding = doctor.chunk_cardinality_finding(root)
    ok = (
        finding is not None
        and finding.get("check") == "chunk-cardinality-mismatch"
        and finding.get("status") == "drift"
        and any(u.get("unitId") == "unit-1" for u in finding.get("units") or [])
        and bool(finding.get("remediation"))
    )
    return {"name": "doctor-flags-cardinality-mismatch-during-outage", "ok": ok, "detail": finding}


def check_doctor_findings_clear_after_retry() -> dict:
    import planning_store as ps

    doctor = _load_module("scripts/planning-doctor.py", "_put_journal_doctor_3")
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = _fixture_root(tmp, project_key="put-journal-doctor-3")
        content = _clean_overflow_content(cfg["planning"]["store"]["projectKey"], "prd", "unit-1")
        _simulate_crash_after_create(root, cfg, "unit-1", content)
        before_partial = doctor.put_partial_finding(root)
        before_cardinality = doctor.chunk_cardinality_finding(root)

        backend2 = ps.get_backend(root, cfg)
        backend2.put("unit-1", "docs/prds/x/x.md", content)

        after_partial = doctor.put_partial_finding(root)
        after_cardinality = doctor.chunk_cardinality_finding(root)
    ok = (
        before_partial is not None
        and before_cardinality is not None
        and after_partial is None
        and after_cardinality is None
    )
    return {
        "name": "doctor-findings-clear-after-retry",
        "ok": ok,
        "detail": f"beforePartial={before_partial is not None} beforeCardinality={before_cardinality is not None} "
        f"afterPartial={after_partial} afterCardinality={after_cardinality}",
    }


def main() -> int:
    checks = [
        check_zero_small_body_never_journals(),
        check_crash_after_create_leaves_resumable_journal(),
        check_retry_converges_to_one_issue(),
        check_doctor_flags_put_partial_during_outage(),
        check_doctor_flags_cardinality_mismatch_during_outage(),
        check_doctor_findings_clear_after_retry(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-put-journal",
        "rid": "R26",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
