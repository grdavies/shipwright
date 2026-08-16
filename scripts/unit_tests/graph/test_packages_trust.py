#!/usr/bin/env python3
"""PRD 272 phase-7 workflow package trust, lockfile, and expansion tuple tests."""
from __future__ import annotations

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.kernel_compiler import KERNEL_VERSION, compile_workflow_graph  # noqa: E402
from graph.packages import (  # noqa: E402
    ExpansionTuple,
    LockfileError,
    PackageResolver,
    PackageResolverError,
    TrustAnchorError,
    approve_expansion_tuple,
    compute_lock_digest,
    discover_packages,
    expansion_is_additive,
    expansion_requires_reapproval,
    load_lockfile,
    load_trust_anchors,
    report_adoption_metrics,
    require_lock_edit_approval,
    resolve_trusted_packages,
)
from graph.packages.trust import sign_package_content  # noqa: E402

_TEST_SECRET = b"test-trust-secret-shipwright"
_TEST_KEY_ID = "shipwright-test"


def _trust_anchor_payload() -> dict:
    return {
        "schemaVersion": 1,
        "keys": {
            _TEST_KEY_ID: {
                "status": "active",
                "secret": _TEST_SECRET.decode(),
                "notBefore": "2020-01-01T00:00:00Z",
                "notAfter": "2099-12-31T23:59:59Z",
            }
        },
    }


def _minimal_graph() -> dict:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "package-fixture"},
        "spec": {
            "nodes": [
                {
                    "id": "run",
                    "kind": "command",
                    "target": {"step": "sw-execute"},
                    "resources": {
                        "pool": "code-writers",
                        "slots": 1,
                        "timeoutSeconds": 30,
                    },
                    "isolation": {"mode": "worktree", "writeScope": "worktree"},
                    "verification": {"required": True, "strategy": "mechanical"},
                }
            ],
            "edges": [],
            "resourceLimits": {"maxConcurrency": 1, "maxDurationSeconds": 120},
            "verification": {"required": True, "failClosed": True},
        },
    }


def _signed_package(
    *,
    name: str,
    version: str,
    dependencies: list[str] | None = None,
) -> dict:
    body = {
        "schemaVersion": 1,
        "kind": "WorkflowPackage",
        "name": name,
        "version": version,
        "dependencies": dependencies or [],
        "producer": "shipwright-dogfood",
        "graph": {
            "nodes": [
                {
                    "id": "run",
                    "kind": "command",
                    "target": {"step": "sw-execute"},
                }
            ],
            "edges": [],
        },
    }
    provenance = sign_package_content(body, key_id=_TEST_KEY_ID, secret=_TEST_SECRET)
    signed = dict(body)
    signed["provenance"] = provenance
    return signed


@pytest.fixture
def package_fixture(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    catalog = repo / ".sw" / "workflows" / "packages"
    catalog.mkdir(parents=True)
    review = _signed_package(name="shipwright-review", version="0.2.0")
    quick = _signed_package(
        name="shipwright-quick",
        version="1.0.0",
        dependencies=["shipwright-review@0.2.0"],
    )
    (catalog / "shipwright-review@0.2.0.json").write_text(
        json.dumps(review, indent=2) + "\n"
    )
    (catalog / "shipwright-quick@1.0.0.json").write_text(
        json.dumps(quick, indent=2) + "\n"
    )
    lock = {
        "schemaVersion": 1,
        "packages": {
            "shipwright-quick@1.0.0": {
                "digest": quick["provenance"]["contentDigest"],
                "signerKeyId": _TEST_KEY_ID,
                "dependencies": ["shipwright-review@0.2.0"],
            },
            "shipwright-review@0.2.0": {
                "digest": review["provenance"]["contentDigest"],
                "signerKeyId": _TEST_KEY_ID,
                "dependencies": [],
            },
        },
    }
    lock_path = repo / ".sw" / "workflows" / "lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")
    trust_path = tmp_path / "trust.json"
    trust_path.write_text(json.dumps(_trust_anchor_payload(), indent=2) + "\n")
    return {
        "repo": repo,
        "lock": lock_path,
        "trust": trust_path,
        "catalog": catalog,
    }


def test_package_lock_pin_and_unsigned_refused(package_fixture: dict[str, Path]) -> None:
    discovered = discover_packages(package_fixture["catalog"])
    assert {item.pin for item in discovered} == {
        "shipwright-quick@1.0.0",
        "shipwright-review@0.2.0",
    }
    trust_store = load_trust_anchors(package_fixture["trust"])
    resolved = resolve_trusted_packages(
        lock_path=package_fixture["lock"],
        trust_store=trust_store,
        repo_root=package_fixture["repo"],
    )
    assert {item.pin for item in resolved} == {
        "shipwright-quick@1.0.0",
        "shipwright-review@0.2.0",
    }
    unsigned = _signed_package(name="shipwright-rogue", version="9.9.9")
    unsigned.pop("provenance")
    rogue_path = package_fixture["catalog"] / "shipwright-rogue@9.9.9.json"
    rogue_path.write_text(json.dumps(unsigned, indent=2) + "\n")
    with pytest.raises(PackageResolverError):
        PackageResolver(
            lock_path=package_fixture["lock"],
            trust_store=trust_store,
            repo_root=package_fixture["repo"],
        ).resolve_pin("shipwright-rogue@9.9.9")


def test_producer_consumer_adoption_metrics_reported() -> None:
    metrics = report_adoption_metrics(
        {
            "reuseCount": 12,
            "updateFrictionSeconds": 4.5,
            "brokenPinAttempts": 1,
            "resolveAttempts": 20,
        }
    )
    payload = metrics.to_dict()
    assert payload["reuseCount"] == 12
    assert "shipwright-dogfood" in payload["producers"]
    assert "shipwright-sibling-consumer" in payload["consumers"]
    assert payload["compatPolicy"]["revocation"] == "fail-closed"


def test_unknown_revoked_signer_and_lock_edit_approval(
    package_fixture: dict[str, Path],
) -> None:
    trust_payload = _trust_anchor_payload()
    trust_payload["keys"][_TEST_KEY_ID]["status"] = "revoked"
    revoked_path = package_fixture["trust"].with_name("revoked-trust.json")
    revoked_path.write_text(json.dumps(trust_payload, indent=2) + "\n")
    with pytest.raises(PackageResolverError, match="revoked signer key"):
        resolve_trusted_packages(
            lock_path=package_fixture["lock"],
            trust_store=load_trust_anchors(revoked_path),
            repo_root=package_fixture["repo"],
        )

    lock = load_lockfile(package_fixture["lock"])
    updated = deepcopy(lock)
    updated["packages"]["shipwright-quick@1.0.0"] = dict(
        updated["packages"]["shipwright-quick@1.0.0"],
        digest="0" * 64,
    )
    with pytest.raises(LockfileError):
        require_lock_edit_approval(previous=lock, updated=updated, approval=None)

    digest = compute_lock_digest(updated)
    require_lock_edit_approval(
        previous=lock,
        updated=updated,
        approval={
            "approved": True,
            "lockDigest": digest,
            "approvedBy": "operator",
            "approvedAt": "2026-08-16T00:00:00Z",
        },
    )


def test_approval_tuple_additive_inject_no_reapprove() -> None:
    baseline = _minimal_graph()["spec"]["nodes"]
    expanded = list(baseline) + [
        {
            "id": "verify",
            "kind": "verifier",
            "target": {"step": "sw-verify"},
            "resources": {"pool": "read-only-reviewers", "slots": 1, "timeoutSeconds": 30},
            "isolation": {"mode": "none", "writeScope": "read-only"},
            "verification": {"required": True, "strategy": "mechanical"},
        }
    ]
    assert expansion_is_additive(baseline, expanded) is True
    assert expansion_requires_reapproval(baseline, expanded) is False

    weakened = deepcopy(baseline)
    weakened[0]["verification"]["required"] = False
    assert expansion_requires_reapproval(baseline, weakened) is True

    expansion_tuple = ExpansionTuple(
        pack_digest="a" * 64,
        profile_id="standard",
        requirement_set_digest="b" * 64,
        kernel_version=KERNEL_VERSION,
    )
    approval = approve_expansion_tuple(
        expansion_tuple,
        approved_by="operator",
        approved_at="2026-08-16T00:00:00Z",
    )
    compiled = compile_workflow_graph(
        _minimal_graph(),
        expansion_tuple=expansion_tuple.to_dict(),
        expansion_approval=approval.to_dict(),
    )
    assert compiled["expansionTuple"]["profileId"] == "standard"
    assert compiled["expansionApproval"]["tupleDigest"] == approval.tuple_digest

    with pytest.raises(Exception):
        compile_workflow_graph(
            _minimal_graph(),
            expansion_tuple=expansion_tuple.to_dict(),
            expansion_approval=None,
        )
