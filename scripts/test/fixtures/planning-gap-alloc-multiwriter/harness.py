#!/usr/bin/env python3
"""Atomic gap-number allocation under concurrency (PRD 057 R25; task 10.4).

Proves, deterministically and hermetically (``SW_ISSUES_FIXTURE=1`` — no
network, no live provider):

1. **Concurrent allocation, distinct ids** — N threads calling
   ``allocate_gap_unit_id`` with the *same* title concurrently (maximum
   overlap via a ``threading.Barrier``) each win a distinct, gapless,
   monotonic gap number — the local claim-by-create lock
   (``os.O_CREAT | os.O_EXCL``) serializes the race instead of letting two
   writers compute and persist the same candidate number.
2. **Deterministic retry-on-collision** — a pre-existing local claim for the
   next candidate number (simulating a concurrent writer that already won
   it) forces the allocator to retry with the following number, without
   relying on real thread interleaving to exercise the branch.
3. **Sequential end-to-end capture** — two full ``capture_gap`` calls persist
   two distinct gap issues with two distinct unit ids.
4. **Stale cache never wins** — a query cache pre-poisoned with a stale
   (fewer-units) snapshot never leaks into the allocated number: invalidate
   happens before every allocation attempt (R10), so the allocated number
   always reflects the true live unit set.

ZOMBIES: Zero (no prior gaps) · One (single allocation) · Many (N-way
concurrent race) · Interfaces (``allocate_gap_unit_id`` retry-on-collision) ·
State (claim files persist, never re-used; poisoned cache never wins).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_gap_capture as pgc  # noqa: E402
import planning_index_gen as pig  # noqa: E402
from planning_query_cache import put_entry, query_fingerprint  # noqa: E402

_PROJECT_KEY = "gap-alloc-multiwriter-fixture"

_CFG = {
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": _PROJECT_KEY,
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
    root = Path(tempfile.mkdtemp(prefix="sw-gap-alloc-multiwriter-"))
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    cfg_path = root / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(_CFG, indent=2), encoding="utf-8")
    return root


def _gap_number(unit_id: str) -> int:
    m = re.match(r"gap-(\d+)-", unit_id)
    assert m, unit_id
    return int(m.group(1))


def _fake_body_path(unit_id: str) -> str:
    return f"docs/prds/gap/{unit_id}/{unit_id}.md"


def check_concurrent_allocation_distinct_ids() -> dict:
    """N threads racing the same title never collide on a gap number (R25)."""
    with _FixtureEnv():
        root = _sandbox()
        writer_count = 6
        barrier = threading.Barrier(writer_count)
        results: list[str] = [""] * writer_count
        errors: list[BaseException] = []

        def worker(idx: int) -> None:
            try:
                barrier.wait(timeout=5)
                unit_id, _body_path = pgc.allocate_gap_unit_id(root, "concurrent gap race", _fake_body_path)
                results[idx] = unit_id
            except BaseException as exc:  # noqa: BLE001 - surfaced via errors list
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(writer_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        numbers = sorted(_gap_number(uid) for uid in results if uid)
    ok = (
        not errors
        and all(results)
        and len(set(results)) == writer_count
        and numbers == list(range(1, writer_count + 1))
    )
    return {
        "name": "concurrent-allocation-distinct-ids",
        "ok": ok,
        "detail": f"results={results} numbers={numbers} errors={[str(e) for e in errors]}",
    }


def check_deterministic_retry_on_local_collision() -> dict:
    """A pre-existing local claim for the next number forces a retry (R25),
    deterministically — no reliance on real thread interleaving."""
    with _FixtureEnv():
        root = _sandbox()
        claims_dir = root / ".cursor" / "hooks" / "state" / "planning-gap-claims"
        claims_dir.mkdir(parents=True, exist_ok=True)
        (claims_dir / "001.claim").write_text("pre-claimed-by-other-writer\n", encoding="utf-8")
        unit_id, _body_path = pgc.allocate_gap_unit_id(root, "collides with pre-claimed number", _fake_body_path)
    ok = _gap_number(unit_id) == 2
    return {
        "name": "deterministic-retry-on-local-collision",
        "ok": ok,
        "detail": f"unitId={unit_id}",
    }


def check_sequential_capture_persists_distinct_issues() -> dict:
    """Two sequential full ``capture_gap`` calls persist two distinct gap issues."""
    with _FixtureEnv():
        root = _sandbox()
        first = pgc.capture_gap(root, signal_id="sig-a", title="first captured gap", problem="first captured gap", context="fixture", dry_run=False)
        second = pgc.capture_gap(root, signal_id="sig-b", title="second captured gap", problem="second captured gap", context="fixture", dry_run=False)
        units = [u.id for u in pig.discover_units(root)]
    ok = (
        first["unitId"] != second["unitId"]
        and first["unitId"] in units
        and second["unitId"] in units
        and len(units) == 2
    )
    return {
        "name": "sequential-capture-persists-distinct-issues",
        "ok": ok,
        "detail": f"first={first['unitId']} second={second['unitId']} units={units}",
    }


def check_stale_cache_never_wins() -> dict:
    """A pre-poisoned (stale, fewer-units) cache entry never leaks into the
    allocated gap number — invalidate-before-allocate always wins (R10)."""
    with _FixtureEnv():
        root = _sandbox()
        real = pgc.capture_gap(root, signal_id="sig-real", title="already captured gap", problem="already captured gap", context="fixture", dry_run=False)
        real_number = _gap_number(real["unitId"])

        # Poison the query cache with a stale snapshot claiming zero units,
        # as if a reader had cached the view *before* `real` was created.
        put_entry(
            root,
            project_key=_PROJECT_KEY,
            fingerprint=query_fingerprint(_PROJECT_KEY),
            projections=[],
            metadata={"units": {}},
        )
        unit_id, _body_path = pgc.allocate_gap_unit_id(root, "second gap after poisoned cache", _fake_body_path)
        allocated_number = _gap_number(unit_id)
    ok = allocated_number == real_number + 1
    return {
        "name": "stale-cache-never-wins",
        "ok": ok,
        "detail": f"realNumber={real_number} allocatedNumber={allocated_number}",
    }


def main() -> int:
    checks = [
        check_concurrent_allocation_distinct_ids(),
        check_deterministic_retry_on_local_collision(),
        check_sequential_capture_persists_distinct_issues(),
        check_stale_cache_never_wins(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-gap-alloc-multiwriter",
        "rid": "R25",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
