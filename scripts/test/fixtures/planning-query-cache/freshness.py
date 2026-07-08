#!/usr/bin/env python3
"""Query-cache freshness under symmetric-diff revalidation (PRD 057 R10; task 10.5).

Proves, hermetically (``SW_ISSUES_FIXTURE=1`` — no network, no live provider),
that a long-lived (well within TTL) cached ``discover_units_issue`` view is
never allowed to mask a live membership or state change made by another
writer:

1. **New remote unit visible before TTL expiry** — a unit created directly in
   the fixture store by "another writer" (bypassing this process's cache)
   appears on the very next ``discover_units`` call, without waiting for the
   cache TTL to expire.
2. **Removed/closed unit reflected before TTL expiry** — a unit tombstoned by
   another writer disappears from the next ``discover_units`` call, even
   though the prior code only invalidated on *open* removals.
3. **State drift detected before TTL expiry** — a state change on an
   already-cached unit (open -> closed) is reflected on the next call.
4. **Cache reuse when nothing changed** — when nothing drifts, a second call
   within the TTL window reuses the cached projections (a single
   ``discover-revalidate`` live call, no second full ``issue-search``),
   proving the fix does not regress caching itself into an always-refetch.

ZOMBIES: Zero (empty store) · One (single cached unit) · Many (multi-unit
membership diff) · Interfaces (``revalidate_live_metadata`` symmetric-diff) ·
State (cache entries always reflect the live view before TTL expiry).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_index_gen as pig  # noqa: E402
from issues_lib import get_fixture_store  # noqa: E402
from planning_canonical import compose_issue_body, project_label, type_label  # noqa: E402
from planning_request_budget import RequestBudgetLedger  # noqa: E402

_PROJECT_KEY = "query-cache-freshness-fixture"

# A generous TTL so every assertion below proves freshness comes from
# symmetric-diff revalidation (R10), never from TTL expiry.
_CFG = {
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": _PROJECT_KEY,
            "requestBudget": {
                "github-issues": {
                    "maxCalls": 200,
                    "maxPaginationDepth": 5,
                    "alertThreshold": 0.8,
                    "cacheTtlSeconds": 600,
                }
            },
        }
    },
    "host": {"provider": "github"},
}


class _FixtureEnv:
    """Scope ``SW_ISSUES_FIXTURE=1`` + issue-sourced discovery to a block
    (hermetic, no network)."""

    _VARS = {"SW_ISSUES_FIXTURE": "1", "SW_DISCOVER_SOURCE": "issue"}

    def __enter__(self) -> "_FixtureEnv":
        self._prev = {name: os.environ.get(name) for name in self._VARS}
        os.environ.update(self._VARS)
        return self

    def __exit__(self, *exc: object) -> None:
        for name, value in self._prev.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _sandbox() -> Path:
    root = Path(tempfile.mkdtemp(prefix="sw-query-cache-freshness-"))
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    cfg_path = root / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(_CFG, indent=2), encoding="utf-8")
    return root


def _create_unit(root: Path, *, unit_id: str, artifact_type: str = "prd", title: str = "Fixture unit") -> None:
    # No explicit `status:` in frontmatter: status derives from `record.state`
    # (open -> proposed, closed -> complete) so the state-drift check below
    # observes the live-state signal, not a frozen frontmatter value.
    body = compose_issue_body(
        _PROJECT_KEY,
        artifact_type,
        unit_id,
        f"---\nid: {unit_id}\ntype: {artifact_type}\ntitle: {title}\nvisibility: public\n---\n",
    )
    store = get_fixture_store(root)
    store.create(
        title=f"[sw] {artifact_type}:{unit_id}",
        body=body,
        labels=sorted({project_label(_PROJECT_KEY), type_label(artifact_type), "sw:visibility:public"}),
        project_key=_PROJECT_KEY,
        artifact_type=artifact_type,
        unit_id=unit_id,
    )


def _ids(root: Path) -> list[str]:
    return sorted(u.id for u in pig.discover_units(root))


def check_new_remote_unit_visible_before_ttl_expiry() -> dict:
    """A unit created by another writer is visible on the very next call,
    well within the (generous) cache TTL (R10)."""
    with _FixtureEnv():
        root = _sandbox()
        _create_unit(root, unit_id="prd-001")
        first = _ids(root)
        _create_unit(root, unit_id="prd-002")  # "another writer" — this process's cache is unaware
        second = _ids(root)
    ok = first == ["prd-001"] and second == ["prd-001", "prd-002"]
    return {
        "name": "new-remote-unit-visible-before-ttl-expiry",
        "ok": ok,
        "detail": f"first={first} second={second}",
    }


def check_removed_unit_reflected_before_ttl_expiry() -> dict:
    """A unit tombstoned by another writer disappears on the next call —
    even though the pre-R10 code only invalidated on *open* removals."""
    with _FixtureEnv():
        root = _sandbox()
        _create_unit(root, unit_id="prd-001")
        _create_unit(root, unit_id="prd-002")
        first = _ids(root)
        store = get_fixture_store(root)
        record = store.find_by_unit(_PROJECT_KEY, "prd-002")
        assert record is not None
        store.mark_tombstone(record.id)
        second = _ids(root)
    ok = first == ["prd-001", "prd-002"] and second == ["prd-001"]
    return {
        "name": "removed-unit-reflected-before-ttl-expiry",
        "ok": ok,
        "detail": f"first={first} second={second}",
    }


def check_state_drift_detected_before_ttl_expiry() -> dict:
    """A state change on an already-cached unit (open -> closed) is reflected
    on the next call, without waiting for TTL expiry."""
    with _FixtureEnv():
        root = _sandbox()
        _create_unit(root, unit_id="prd-001")
        first = {u.id: u.status for u in pig.discover_units(root)}
        store = get_fixture_store(root)
        record = store.find_by_unit(_PROJECT_KEY, "prd-001")
        assert record is not None
        store.update(record.id, state="closed")
        second = {u.id: u.status for u in pig.discover_units(root)}
    ok = first.get("prd-001") != second.get("prd-001") and second.get("prd-001") == "complete"
    return {
        "name": "state-drift-detected-before-ttl-expiry",
        "ok": ok,
        "detail": f"first={first} second={second}",
    }


def check_cache_reused_when_no_drift() -> dict:
    """When nothing drifts, a second call within the TTL window reuses the
    cache: a single ``discover-revalidate`` live call, not a second full
    ``issue-search`` — the fix must not regress caching into always-refetch."""
    with _FixtureEnv():
        root = _sandbox()
        _create_unit(root, unit_id="prd-001")
        first = _ids(root)
        second = _ids(root)
        ops = RequestBudgetLedger.from_config(root, "github-issues").snapshot()["operations"]
    ok = (
        first == ["prd-001"]
        and second == ["prd-001"]
        and ops.get("issue-search") == 1
        and ops.get("discover-revalidate") == 1
    )
    return {
        "name": "cache-reused-when-no-drift",
        "ok": ok,
        "detail": f"first={first} second={second} operations={ops}",
    }


def main() -> int:
    checks = [
        check_new_remote_unit_visible_before_ttl_expiry(),
        check_removed_unit_reflected_before_ttl_expiry(),
        check_state_drift_detected_before_ttl_expiry(),
        check_cache_reused_when_no_drift(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-query-cache.freshness",
        "rid": "R10",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
