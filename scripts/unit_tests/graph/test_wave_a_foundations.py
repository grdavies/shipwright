#!/usr/bin/env python3
"""Wave A foundations fixtures — pools, fan-in, isolation (PRD 092 R6/R7/R8)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.fanin_policy import (  # noqa: E402
    CoverageAction,
    FanInMode,
    FanInPolicy,
    NodeOutcome,
    evaluate_fanin,
    parse_fanin_policy,
)
from graph.isolation_policy import (  # noqa: E402
    IsolationMode,
    IsolationPolicy,
    NodeIsolationClaim,
    WriteScope,
    analyze_write_contention,
    parse_isolation_policy,
)
from graph.resource_pools import (  # noqa: E402
    PoolExhausted,
    PoolName,
    ResourcePoolRegistry,
)


def test_pool_exhaustion_backpressure() -> None:
    reg = ResourcePoolRegistry.from_config(
        limits={"code-writers": 2},
        hard_ceiling=16,
    )
    reg.acquire(PoolName.CODE_WRITERS)
    reg.acquire(PoolName.CODE_WRITERS)
    with pytest.raises(PoolExhausted) as exc:
        reg.acquire(PoolName.CODE_WRITERS)
    assert exc.value.pool == PoolName.CODE_WRITERS
    assert exc.value.limit == 2
    snap = reg.snapshot()
    assert snap["code-writers"]["waiters"] == 1
    reg.release(PoolName.CODE_WRITERS)
    reg.acquire(PoolName.CODE_WRITERS)  # succeeds after release


def test_pool_limit_cannot_exceed_hard_ceiling() -> None:
    reg = ResourcePoolRegistry.from_config(
        limits={"code-writers": 100},
        hard_ceiling=4,
    )
    assert reg.pools[PoolName.CODE_WRITERS].limit == 4


@pytest.mark.parametrize(
    "mode,outcomes,expected_verdict,expect_halt",
    [
        (
            FanInMode.ALL_SUCCESS,
            [
                NodeOutcome("a", True),
                NodeOutcome("b", True),
            ],
            "pass",
            False,
        ),
        (
            FanInMode.ALL_SUCCESS,
            [
                NodeOutcome("a", True),
                NodeOutcome("b", False),
            ],
            "fail",
            True,
        ),
        (
            FanInMode.ALL_SETTLED,
            [
                NodeOutcome("a", True),
                NodeOutcome("b", False),
            ],
            "degraded",
            True,
        ),
        (
            FanInMode.QUORUM,
            [
                NodeOutcome("a", True),
                NodeOutcome("b", False),
                NodeOutcome("c", True),
            ],
            "degraded",
            False,
        ),
        (
            FanInMode.MINIMUM_COVERAGE,
            [
                NodeOutcome("a", False),
                NodeOutcome("b", False),
            ],
            "fail",
            True,
        ),
    ],
)
def test_fanin_matrix(mode, outcomes, expected_verdict, expect_halt) -> None:
    policy = FanInPolicy(
        mode=mode,
        minimum_successful=2 if mode in (FanInMode.QUORUM, FanInMode.MINIMUM_COVERAGE) else None,
        on_insufficient_coverage=CoverageAction.HALT,
    )
    result = evaluate_fanin(policy, outcomes)
    assert result.verdict == expected_verdict
    assert result.halt is expect_halt
    # Failed nodes always visible — never silently excluded
    failed_ids = {o.node_id for o in outcomes if o.settled and not o.success}
    assert set(result.failed) == failed_ids


def test_fanin_required_nodes_not_silently_dropped() -> None:
    policy = parse_fanin_policy(
        {
            "mode": "quorum",
            "minimumSuccessful": 1,
            "requiredNodes": ["gate"],
            "onInsufficientCoverage": "halt",
        }
    )
    result = evaluate_fanin(
        policy,
        [NodeOutcome("a", True), NodeOutcome("gate", False)],
    )
    assert result.halt is True
    assert "gate" in result.failed
    assert "gate" in result.missing_required


def test_isolation_worktree_vs_readonly() -> None:
    writers = NodeIsolationClaim(
        node_id="writer",
        policy=IsolationPolicy(IsolationMode.NONE, WriteScope.SCOPED),
        write_paths=frozenset({"scripts/graph/scheduler.py"}),
    )
    peer = NodeIsolationClaim(
        node_id="peer-writer",
        policy=parse_isolation_policy({"mode": "process", "writeScope": "scoped"}),
        write_paths=frozenset({"scripts/graph/scheduler.py"}),
    )
    reader = NodeIsolationClaim(
        node_id="reviewer",
        policy=IsolationPolicy(IsolationMode.NONE, WriteScope.READ_ONLY),
        write_paths=frozenset({"scripts/graph/scheduler.py"}),
    )
    # Concurrent writers on shared path without worktree isolation → contention
    findings = analyze_write_contention([writers, peer])
    assert findings and findings[0].path.endswith("scheduler.py")

    # Read-only dispatch does not contend with a writer
    assert analyze_write_contention([writers, reader]) == []

    # Worktree-isolated writers on same logical path are allowed
    wt_a = NodeIsolationClaim(
        "a",
        IsolationPolicy(IsolationMode.WORKTREE, WriteScope.WORKTREE),
        frozenset({"scripts/graph/scheduler.py"}),
    )
    wt_b = NodeIsolationClaim(
        "b",
        IsolationPolicy(IsolationMode.WORKTREE, WriteScope.WORKTREE),
        frozenset({"scripts/graph/scheduler.py"}),
    )
    assert analyze_write_contention([wt_a, wt_b]) == []


def test_owner_token_lease_reentry_mismatch_and_park(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R5: matching owner re-enters; foreign release refused; contention parks."""
    import subprocess

    from wave_lock import (
        acquire_ship_lease,
        owner_token_matches,
        release_ship_lease,
        resolve_node_id,
    )

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    (root / ".cursor" / "sw-deliver-locks").mkdir(parents=True)
    monkeypatch.chdir(root)

    args_a = [
        "--integration",
        "feat/graph-execution-engine",
        "--phase-branch",
        "feat/graph-execution-engine-phase-a",
        "--node-id",
        "node-a",
    ]
    first = acquire_ship_lease(root, args_a)
    assert first.get("verdict") == "pass"
    assert first.get("ownerToken", {}).get("nodeId") == "node-a"

    reentry = acquire_ship_lease(root, args_a)
    assert reentry.get("verdict") == "pass"
    assert reentry.get("reentrant") is True

    args_b = [
        "--integration",
        "feat/graph-execution-engine",
        "--phase-branch",
        "feat/graph-execution-engine-phase-a",
        "--node-id",
        "node-b",
    ]
    parked = acquire_ship_lease(root, args_b)
    assert parked.get("verdict") == "park"
    assert parked.get("error") == "ship-lease-parked"
    assert "ship-lease-held" not in str(parked.get("error"))

    # Foreign owner cannot release — including finalize.
    foreign = release_ship_lease(root, args_b, finalize=True)
    assert foreign.get("verdict") == "fail"
    assert foreign.get("error") == "ship-lease-owner-mismatch"

    # Matching owner releases.
    released = release_ship_lease(root, args_a)
    assert released.get("verdict") == "pass"

    # After release, other node can acquire.
    second = acquire_ship_lease(root, args_b)
    assert second.get("verdict") == "pass"
    assert owner_token_matches(
        {
            "pid": second["ownerToken"]["pid"],
            "threadId": second["ownerToken"]["threadId"],
            "nodeId": "node-b",
        },
        resolve_node_id(args_b),
    )
    release_ship_lease(root, args_b)
