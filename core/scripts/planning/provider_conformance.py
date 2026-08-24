"""PRD 090 R3 — shared provider-conformance contract and evidence records."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from issues_lib import (
    FixtureIssuesStore,
    IssueArchivedProject,
    IssueBudgetExhausted,
    IssueCapabilityError,
    IssueNotFound,
    IssueRateLimited,
    IssueRevisionConflict,
    IssueTombstone,
    IssueTransferred,
    IssuesClient,
    classify_lifecycle_error,
    get_fixture_store,
    use_fixture_mode,
)

CONFORMANCE_FIXTURES_REL = Path("scripts/test/fixtures/planning-provider-conformance")

CONFORMANCE_DIMENSIONS: tuple[str, ...] = (
    "auth-success",
    "auth-failure",
    "identity-mismatch",
    "visibility",
    "crud-lifecycle",
    "optimistic-concurrency",
    "idempotent-retries",
    "rate-limits",
    "pagination",
    "partial-outage",
    "redaction",
    "concurrent-writes",
    "timeout-recovery",
    "archival",
)

# Providers that may appear in SHIPPED_ISSUES_PROVIDERS only with green conformance evidence.
CONFORMANCE_GATED_PROVIDERS: frozenset[str] = frozenset({"github-issues", "jira", "linear", "notion"})
DOCS_GATED_PROVIDERS: frozenset[str] = frozenset({"notion"})

_SAMPLE_BODY = "---\nunitId: conf-sample\ntitle: Conformance\n---\n\n# conformance sample\n"


def provider_fixture_slug(provider: str) -> str:
    return provider.replace("-issues", "")


def conformance_fixture_path(root: Path, provider: str) -> Path:
    slug = provider_fixture_slug(provider)
    return (root / CONFORMANCE_FIXTURES_REL / f"{slug}.ok.json").resolve()


def load_conformance_record(root: Path, provider: str) -> dict[str, Any]:
    path = conformance_fixture_path(root, provider)
    if not path.is_file():
        return {
            "verdict": "fail",
            "provider": provider,
            "error": "missing-conformance-record",
            "fixturePath": str(path),
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "verdict": "fail",
            "provider": provider,
            "error": "invalid-conformance-record",
            "fixturePath": str(path),
            "message": str(exc),
        }
    if not isinstance(payload, dict):
        return {
            "verdict": "fail",
            "provider": provider,
            "error": "invalid-conformance-record",
            "fixturePath": str(path),
        }
    payload.setdefault("provider", provider)
    payload.setdefault("fixturePath", str(path))
    return payload


def conformance_record_hash(record: dict[str, Any]) -> str:
    """Deterministic hash over dimension outcomes (excludes writtenAt)."""
    dimensions = record.get("dimensions")
    if not isinstance(dimensions, dict):
        return ""
    canonical = {
        "provider": record.get("provider"),
        "dimensions": {
            key: {"verdict": (dimensions[key].get("verdict") if isinstance(dimensions[key], dict) else None)}
            for key in sorted(dimensions.keys())
        },
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def providers_with_green_conformance(root: Path) -> frozenset[str]:
    shipped: set[str] = set()
    for provider in sorted(CONFORMANCE_GATED_PROVIDERS):
        record = load_conformance_record(root, provider)
        if record.get("verdict") == "ok" and _dimensions_all_green(record):
            if provider in DOCS_GATED_PROVIDERS and not _provider_docs_gate_green(root, provider):
                continue
            shipped.add(provider)
    return frozenset(shipped)


def _provider_docs_gate_green(root: Path, provider: str) -> bool:
    if provider != "notion":
        return True
    from planning_notion_client import docs_gate

    return docs_gate(root).get("verdict") == "ok"


def _dimensions_all_green(record: dict[str, Any]) -> bool:
    dimensions = record.get("dimensions")
    if not isinstance(dimensions, dict):
        return False
    for dim in CONFORMANCE_DIMENSIONS:
        entry = dimensions.get(dim)
        if not isinstance(entry, dict) or entry.get("verdict") != "ok":
            return False
    return True


def conformance_evidence(root: Path, provider: str) -> dict[str, Any]:
    """Recorded fixture + live suite — both must be green for promotion."""
    recorded = load_conformance_record(root, provider)
    live = run_conformance_suite(provider, root)
    failures: list[dict[str, str]] = []
    if recorded.get("verdict") != "ok":
        failures.append({"phase": "recorded", "verdict": str(recorded.get("verdict"))})
    if live.get("verdict") != "ok":
        failures.append({"phase": "live", "verdict": str(live.get("verdict"))})
    recorded_hash = conformance_record_hash(recorded) if recorded.get("verdict") == "ok" else ""
    live_hash = conformance_record_hash(live) if live.get("verdict") == "ok" else ""
    hash_mismatch = bool(recorded_hash and live_hash and recorded_hash != live_hash)
    if hash_mismatch:
        failures.append({"phase": "hash", "verdict": "mismatch"})
    return {
        "verdict": "ok" if not failures else "fail",
        "action": "provider-conformance-evidence",
        "provider": provider,
        "dimensions": list(CONFORMANCE_DIMENSIONS),
        "fixturePath": str(conformance_fixture_path(root, provider)),
        "recorded": recorded,
        "live": live,
        "recordedHash": recorded_hash,
        "liveHash": live_hash,
        "failures": failures,
    }


def _dimension_ok(dimension: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"verdict": "ok", "dimension": dimension}
    payload.update(extra)
    return payload


def _dimension_fail(dimension: str, error: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"verdict": "fail", "dimension": dimension, "error": error}
    payload.update(extra)
    return payload


def _run_dimension_checks(provider: str, root: Path, client: IssuesClient, store: FixtureIssuesStore) -> dict[str, Any]:
    results: dict[str, Any] = {}
    project_key = "conf090"

    def run(name: str, fn: Callable[[], dict[str, Any]]) -> None:
        try:
            results[name] = fn()
        except Exception as exc:  # noqa: BLE001 — conformance harness captures failures
            results[name] = _dimension_fail(name, type(exc).__name__, message=str(exc))

    run("auth-success", lambda: _check_auth_success(client, project_key))
    run("auth-failure", lambda: _check_auth_failure(root, provider))
    run("identity-mismatch", lambda: _check_identity_mismatch(store, project_key))
    run("visibility", lambda: _check_visibility(store, project_key))
    run("crud-lifecycle", lambda: _check_crud_lifecycle(client, project_key))
    run("optimistic-concurrency", lambda: _check_optimistic_concurrency(store, project_key))
    run("idempotent-retries", lambda: _check_idempotent_retries(client, project_key))
    run("rate-limits", lambda: _check_rate_limits(client))
    run("pagination", lambda: _check_pagination(store, project_key))
    run("partial-outage", lambda: _check_partial_outage(client, project_key))
    run("redaction", lambda: _check_redaction(root))
    run("concurrent-writes", lambda: _check_concurrent_writes(store, project_key))
    run("timeout-recovery", lambda: _check_timeout_recovery(client, project_key))
    run("archival", lambda: _check_archival(store, project_key))

    failures = [name for name, entry in results.items() if entry.get("verdict") != "ok"]
    return {
        "verdict": "ok" if not failures else "fail",
        "provider": provider,
        "action": "provider-conformance-suite",
        "dimensions": results,
        "failedDimensions": failures,
        "recordHash": conformance_record_hash({"provider": provider, "dimensions": results}),
    }


def run_conformance_suite(provider: str, root: Path) -> dict[str, Any]:
    if not use_fixture_mode():
        return {
            "verdict": "fail",
            "provider": provider,
            "error": "fixture-mode-required",
            "message": "SW_ISSUES_FIXTURE=1 required for hermetic conformance suite",
        }
    store = get_fixture_store(root)
    store.clear()
    client = IssuesClient(root, provider)
    return _run_dimension_checks(provider, root, client, store)


def _check_auth_success(client: IssuesClient, project_key: str) -> dict[str, Any]:
    record = client.issue_create(
        title="auth-success",
        body=_SAMPLE_BODY,
        labels=["sw:conformance"],
        project_key=project_key,
        artifact_type="prd",
        unit_id="conf-auth-success",
    )
    if not record.id:
        return _dimension_fail("auth-success", "empty-issue-id")
    return _dimension_ok("auth-success", issueId=record.id)


def _check_auth_failure(root: Path, provider: str) -> dict[str, Any]:
    from credentials.model import ResolutionState
    from planning_store_facade import resolve_issues_credential

    token_key = f"ISSUES_{provider.upper().replace('-', '_')}_TOKEN"
    saved = os.environ.get(token_key)
    os.environ.pop(token_key, None)
    try:
        cfg = {
            "planning": {
                "store": {
                    "backend": "issue-store",
                    "issuesProvider": provider,
                    "projectKey": "conf090",
                    "issues": {"tokenEnv": token_key},
                }
            }
        }
        res = resolve_issues_credential(root, issues_provider=provider, cfg=cfg)
        if res.state == ResolutionState.UNRESOLVED:
            return _dimension_ok("auth-failure", observed=res.reason)
        return _dimension_fail("auth-failure", "missing-token-not-rejected", state=str(res.state))
    finally:
        if saved is not None:
            os.environ[token_key] = saved
        elif token_key in os.environ:
            os.environ.pop(token_key)


def _check_identity_mismatch(store: FixtureIssuesStore, project_key: str) -> dict[str, Any]:
    record = store.create(
        title="identity",
        body=_SAMPLE_BODY,
        labels=[],
        project_key=project_key,
        artifact_type="prd",
        unit_id="conf-identity",
    )
    wrong = store.find_by_unit("other-project", record.unit_id)
    if wrong is not None:
        return _dimension_fail("identity-mismatch", "cross-project-leak")
    return _dimension_ok("identity-mismatch", issueId=record.id)


def _check_visibility(store: FixtureIssuesStore, project_key: str) -> dict[str, Any]:
    tomb = store.create(
        title="tomb",
        body=_SAMPLE_BODY,
        labels=[],
        project_key=project_key,
        artifact_type="prd",
        unit_id="conf-tomb",
    )
    transfer = store.create(
        title="transfer",
        body=_SAMPLE_BODY,
        labels=[],
        project_key=project_key,
        artifact_type="prd",
        unit_id="conf-transfer",
    )
    store.mark_tombstone(tomb.id)
    store.mark_transferred(transfer.id)
    try:
        store.get(tomb.id)
        return _dimension_fail("visibility", "tombstone-not-hidden")
    except IssueTombstone:
        pass
    try:
        store.get(transfer.id)
        return _dimension_fail("visibility", "transfer-not-hidden")
    except IssueTransferred:
        pass
    tomb_record = store._issues[tomb.id]  # noqa: SLF001 — harness inspects tombstone flag
    if classify_lifecycle_error(tomb_record) != "lifecycle-tombstone":
        return _dimension_fail("visibility", "lifecycle-classification")
    return _dimension_ok("visibility")


def _check_crud_lifecycle(client: IssuesClient, project_key: str) -> dict[str, Any]:
    record = client.issue_create(
        title="crud",
        body=_SAMPLE_BODY,
        labels=["sw:draft"],
        project_key=project_key,
        artifact_type="tasks",
        unit_id="conf-crud",
    )
    got = client.issue_get(record.id)
    updated = client.issue_update(record.id, body=_SAMPLE_BODY + "\nupdated\n", if_match=got.etag)
    client.issue_comment(record.id, "conformance comment")
    client.issue_label(record.id, ["sw:draft", "sw:frozen"], if_match=updated.etag)
    matches = client.issue_search(project_key=project_key, unit_id="conf-crud")
    if not matches:
        return _dimension_fail("crud-lifecycle", "search-miss")
    return _dimension_ok("crud-lifecycle", issueId=record.id, commentCount=len(matches[0].comments))


def _check_optimistic_concurrency(store: FixtureIssuesStore, project_key: str) -> dict[str, Any]:
    record = store.create(
        title="etag",
        body=_SAMPLE_BODY,
        labels=[],
        project_key=project_key,
        artifact_type="prd",
        unit_id="conf-etag",
    )
    stale = record.etag
    store.update(record.id, body=_SAMPLE_BODY + "\nfirst\n")
    try:
        store.update(record.id, body=_SAMPLE_BODY + "\nsecond\n", if_match=stale)
        return _dimension_fail("optimistic-concurrency", "stale-etag-accepted")
    except IssueRevisionConflict as exc:
        if exc.expected != stale:
            return _dimension_fail("optimistic-concurrency", "wrong-expected-etag")
    current = store.get(record.id)
    store.update(record.id, body=_SAMPLE_BODY + "\nsecond\n", if_match=current.etag)
    return _dimension_ok("optimistic-concurrency")


def _check_idempotent_retries(client: IssuesClient, project_key: str) -> dict[str, Any]:
    calls = {"n": 0}

    def flaky() -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise IssueCapabilityError("transient-simulated")
        return client.issue_create(
            title="retry",
            body=_SAMPLE_BODY,
            labels=[],
            project_key=project_key,
            artifact_type="prd",
            unit_id="conf-retry",
        )

    record = client._with_resilience("issue-create", flaky)  # noqa: SLF001 — harness exercises retry path
    if calls["n"] < 2:
        return _dimension_fail("idempotent-retries", "no-retry")
    return _dimension_ok("idempotent-retries", attempts=calls["n"], issueId=record.id)


def _check_rate_limits(client: IssuesClient) -> dict[str, Any]:
    def boom() -> None:
        raise IssueRateLimited("simulated", cumulative_wait_ms=10, reason="fixture")

    try:
        client._with_resilience("rate-limit-probe", boom)  # noqa: SLF001
        return _dimension_fail("rate-limits", "not-raised")
    except IssueRateLimited as exc:
        if not exc.retryable:
            return _dimension_fail("rate-limits", "unexpected-non-retryable")
    return _dimension_ok("rate-limits")


def _check_pagination(store: FixtureIssuesStore, project_key: str) -> dict[str, Any]:
    for idx in range(3):
        store.create(
            title=f"page-{idx}",
            body=_SAMPLE_BODY,
            labels=["sw:page"],
            project_key=project_key,
            artifact_type="tasks",
            unit_id=f"conf-page-{idx}",
        )
    matches = store.search(project_key=project_key, labels=["sw:page"])
    if len(matches) < 3:
        return _dimension_fail("pagination", "incomplete-page", count=len(matches))
    numbers = [m.number for m in matches]
    if numbers != sorted(numbers):
        return _dimension_fail("pagination", "unordered")
    return _dimension_ok("pagination", count=len(matches))


def _check_partial_outage(client: IssuesClient, project_key: str) -> dict[str, Any]:
    calls = {"n": 0}

    def flaky() -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("simulated-outage")
        return client.issue_create(
            title="outage",
            body=_SAMPLE_BODY,
            labels=[],
            project_key=project_key,
            artifact_type="prd",
            unit_id="conf-outage",
        )

    record = client._with_resilience("issue-create", flaky)  # noqa: SLF001
    if calls["n"] < 2:
        return _dimension_fail("partial-outage", "no-retry")
    return _dimension_ok("partial-outage", attempts=calls["n"], issueId=record.id)


def _check_redaction(root: Path) -> dict[str, Any]:
    from planning_store_facade import redact_content

    raw = "ghp_abcdefghijklmnopqrstuvwxyz1234567890 email=user@example.com"
    redacted = redact_content(raw)
    if "ghp_" in redacted or "user@example.com" in redacted:
        return _dimension_fail("redaction", "secrets-leaked")
    return _dimension_ok("redaction")


def _check_concurrent_writes(store: FixtureIssuesStore, project_key: str) -> dict[str, Any]:
    record = store.create(
        title="concurrent",
        body=_SAMPLE_BODY,
        labels=[],
        project_key=project_key,
        artifact_type="prd",
        unit_id="conf-concurrent",
    )
    etag_a = record.etag
    store.update(record.id, body=_SAMPLE_BODY + "\na\n")
    try:
        store.update(record.id, body=_SAMPLE_BODY + "\nb\n", if_match=etag_a)
        return _dimension_fail("concurrent-writes", "lost-update")
    except IssueRevisionConflict:
        pass
    return _dimension_ok("concurrent-writes")


def _check_timeout_recovery(client: IssuesClient, project_key: str) -> dict[str, Any]:
    start = time.monotonic()
    calls = {"n": 0}

    def slow_then_ok() -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(0.05)
            raise TimeoutError("simulated-timeout")
        return client.issue_create(
            title="timeout",
            body=_SAMPLE_BODY,
            labels=[],
            project_key=project_key,
            artifact_type="prd",
            unit_id="conf-timeout",
        )

    record = client._with_resilience("issue-create", slow_then_ok)  # noqa: SLF001
    elapsed_ms = int((time.monotonic() - start) * 1000)
    if calls["n"] < 2:
        return _dimension_fail("timeout-recovery", "no-retry")
    return _dimension_ok("timeout-recovery", attempts=calls["n"], elapsedMs=elapsed_ms, issueId=record.id)


def _check_archival(store: FixtureIssuesStore, project_key: str) -> dict[str, Any]:
    record = store.create(
        title="archival",
        body=_SAMPLE_BODY,
        labels=[],
        project_key=project_key,
        artifact_type="prd",
        unit_id="conf-archival",
    )
    store.mark_archived_project(record.id)
    try:
        store.get(record.id)
        return _dimension_fail("archival", "archived-readable")
    except IssueArchivedProject:
        pass
    except IssueNotFound:
        return _dimension_fail("archival", "wrong-exception")
    converted = store.create(
        title="converted",
        body=_SAMPLE_BODY,
        labels=[],
        project_key=project_key,
        artifact_type="prd",
        unit_id="conf-converted",
    )
    store.mark_type_converted(converted.id)
    try:
        store.get(converted.id)
        return _dimension_fail("archival", "converted-readable")
    except IssueTombstone:
        pass
    return _dimension_ok("archival")


def write_conformance_record(root: Path, provider: str, suite: dict[str, Any]) -> Path:
    path = conformance_fixture_path(root, provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "verdict": suite.get("verdict"),
        "provider": provider,
        "action": "provider-conformance-record",
        "dimensions": suite.get("dimensions", {}),
        "recordHash": suite.get("recordHash") or conformance_record_hash(suite),
        "writtenAt": int(time.time()),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
