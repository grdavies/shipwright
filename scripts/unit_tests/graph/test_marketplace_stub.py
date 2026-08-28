"""PRD 333 phase 10 — WorkflowPackage marketplace P3 spec stub (R10, R11, R13, R18, R21)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from graph.packages import (  # noqa: E402
    ALL_PACKAGE_REGISTRIES,
    P3_PACKAGE_REGISTRY_STUBS,
    SHIPPED_PACKAGE_REGISTRIES,
    PackageResolverError,
    load_trust_anchors,
    package_p3_stub_registration_footprint,
    package_registry_default_off,
    package_registry_kind,
    resolve_registry_package,
)
from graph.packages.marketplace import (  # noqa: E402
    MARKETPLACE_CORPUS_SCENARIOS,
    REGISTRY_ID,
    TRUST_POLICY_VERSION,
    MarketplaceRegistryError,
    MarketplaceTrustContext,
    evaluate_marketplace_trust,
    marketplace_trust_gate,
    register_marketplace_registry_stub,
    resolve_marketplace_package,
    validate_pinned_reference,
)

_TEST_DIGEST = "a" * 64
_TEST_PIN = "shipwright-review@1.0.0"
_TEST_SIGNER = "shipwright-test"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _valid_pin_reference(**overrides: object) -> dict:
    base = {
        "pin": _TEST_PIN,
        "digest": _TEST_DIGEST,
        "signerKeyId": _TEST_SIGNER,
        "dependencies": [],
    }
    base.update(overrides)
    return base


def _valid_context(**overrides: object) -> MarketplaceTrustContext:
    base = MarketplaceTrustContext(
        pin=_TEST_PIN,
        digest=_TEST_DIGEST,
        signer_key_id=_TEST_SIGNER,
        expected_digest=_TEST_DIGEST,
        expected_signer_key_id=_TEST_SIGNER,
        dependencies=(),
        resolved_dependencies=(),
        signed=True,
        signer_status="active",
        reproducible=True,
        audit_events=({"phase": "resolve", "correlationId": "fixture-1"},),
        require_audit=True,
    )
    if not overrides:
        return base
    data = base.__dict__.copy()
    data.update(overrides)
    return MarketplaceTrustContext(**data)


def _full_trust_claim(*, trust_complete: bool = True, parity_complete: bool = False) -> dict:
    return {
        "registry": REGISTRY_ID,
        "trustPolicyVersion": TRUST_POLICY_VERSION,
        "dimensions": {
            "digest-pinning": {"verdict": "ok"},
            "signer-policy": {"verdict": "ok"},
            "revocation": {"verdict": "ok"},
            "transitive-dependency-policy": {"verdict": "ok"},
            "reproducible-resolution": {"verdict": "ok"},
            "audit-evidence": {"verdict": "ok"},
        },
        "corpusScenarioIds": sorted(MARKETPLACE_CORPUS_SCENARIOS),
        "trustComplete": trust_complete,
        "parityComplete": parity_complete,
        "enabled": False,
        "shipped": False,
    }


def test_spec_only_boundary() -> None:
    """R10 — spec defines trust policy; stub validates pins without remote resolution."""
    spec_path = _repo_root() / "core/providers/workflow-package/marketplace.md"
    assert spec_path.is_file()
    text = spec_path.read_text(encoding="utf-8")
    for heading in (
        "digest pinning",
        "signer policy",
        "revocation",
        "transitive dependency",
        "reproducible resolution",
        "audit evidence",
        "fail closed",
    ):
        assert heading in text.lower()

    registration = register_marketplace_registry_stub()
    assert registration["status"] == "not-enabled"
    assert registration["shipped"] is False
    assert registration["trustComplete"] is False
    assert registration["parityComplete"] is False

    result = resolve_marketplace_package(_valid_pin_reference())
    assert result["status"] == "not-enabled"
    assert result["remoteResolution"] is False
    assert result["installation"] is False
    assert result["shipped"] is False


def test_completion_boundary() -> None:
    """R13 — stub is registered but not shipped and reports not-enabled."""
    registration = register_marketplace_registry_stub()
    assert registration["registryId"] == REGISTRY_ID
    assert registration["status"] == "not-enabled"
    assert registration["shipped"] is False

    assert REGISTRY_ID not in SHIPPED_PACKAGE_REGISTRIES
    assert REGISTRY_ID in P3_PACKAGE_REGISTRY_STUBS
    assert REGISTRY_ID in ALL_PACKAGE_REGISTRIES

    footprint = package_p3_stub_registration_footprint()
    assert footprint["verdict"] == "ok"
    stub_entry = footprint["stubs"][REGISTRY_ID]
    assert stub_entry["status"] == "not-enabled"
    assert stub_entry["shipped"] is False


def test_unpinned_reference_rejected() -> None:
    """R10 — floating or malformed pins are refused."""
    with pytest.raises(MarketplaceRegistryError, match="unpinned-reference"):
        validate_pinned_reference(_valid_pin_reference(pin="shipwright-review"))

    with pytest.raises(MarketplaceRegistryError, match="unpinned-reference"):
        validate_pinned_reference(_valid_pin_reference(pin="bad name@1.0.0"))


def test_unsigned_package_rejected() -> None:
    """R21 — packages without signer binding are refused."""
    with pytest.raises(MarketplaceRegistryError, match="unsigned-package"):
        validate_pinned_reference(_valid_pin_reference(signerKeyId=""))

    result = evaluate_marketplace_trust(_valid_context(signed=False, signer_key_id=""))
    assert result["verdict"] == "fail"
    assert any(f["error"] == "unsigned-package" for f in result["failures"])


def test_revoked_signer_rejected(tmp_path: Path) -> None:
    """R11/R21 — revoked signer keys fail closed."""
    trust_path = tmp_path / "trust.json"
    trust_path.write_text(
        (
            '{"schemaVersion":1,"keys":{"shipwright-test":'
            '{"status":"revoked","secret":"secret","notBefore":"2020-01-01T00:00:00Z",'
            '"notAfter":"2099-12-31T23:59:59Z"}}}\n'
        ),
        encoding="utf-8",
    )
    trust_store = load_trust_anchors(trust_path)

    with pytest.raises(MarketplaceRegistryError, match="revoked-signer"):
        resolve_marketplace_package(_valid_pin_reference(), trust_store=trust_store)

    result = evaluate_marketplace_trust(_valid_context(signer_status="revoked"))
    assert result["verdict"] == "fail"
    assert any(f["error"] == "revoked-signer" for f in result["failures"])


def test_pin_mismatch_rejected() -> None:
    """R10 — digest pinning must match lock expectation."""
    reference = validate_pinned_reference(_valid_pin_reference(digest="b" * 64))
    assert reference.digest == "b" * 64

    result = evaluate_marketplace_trust(
        _valid_context(digest="a" * 64, expected_digest="c" * 64)
    )
    assert result["verdict"] == "fail"
    assert any(f["error"] == "pin-mismatch" for f in result["failures"])


def test_transitive_policy_refused() -> None:
    """R21 — transitive closure must be explicit and complete."""
    with pytest.raises(MarketplaceRegistryError, match="transitive-policy-refused"):
        validate_pinned_reference(
            _valid_pin_reference(dependencies=["shipwright-base@not-semver"])
        )

    result = evaluate_marketplace_trust(
        _valid_context(
            dependencies=("shipwright-base@1.0.0",),
            resolved_dependencies=(),
        )
    )
    assert result["verdict"] == "fail"
    assert any(f["error"] == "transitive-policy-refused" for f in result["failures"])


def test_non_reproducible_resolution_rejected() -> None:
    """R10/R18 — resolution must be reproducible for the same pin."""
    result = evaluate_marketplace_trust(
        _valid_context(
            reproducible=False,
            prior_resolution_digest="d" * 64,
        )
    )
    assert result["verdict"] == "fail"
    assert any(f["error"] == "non-reproducible-resolution" for f in result["failures"])


def test_missing_audit_evidence_rejected() -> None:
    """R11 — structured audit trail is mandatory for trust claims."""
    result = evaluate_marketplace_trust(_valid_context(audit_events=()))
    assert result["verdict"] == "fail"
    assert any(f["error"] == "missing-audit-evidence" for f in result["failures"])


def test_trust_gate_blocks_stub_claims() -> None:
    """R13/R18 — full trust/corpus claim still refused for P3 stub."""
    claim = _full_trust_claim(trust_complete=True, parity_complete=True)
    result = marketplace_trust_gate(claim)
    assert result["verdict"] == "fail"
    errors = {f["error"] for f in result["failures"]}
    assert "p3-stub-trust-claim-refused" in errors
    assert "p3-stub-parity-claim-refused" in errors

    partial = {
        "registry": REGISTRY_ID,
        "trustPolicyVersion": TRUST_POLICY_VERSION,
        "dimensions": {"digest-pinning": {"verdict": "ok"}},
        "corpusScenarioIds": [],
        "trustComplete": False,
    }
    partial_result = marketplace_trust_gate(partial)
    assert partial_result["verdict"] == "fail"
    assert any(f["error"] == "missing-corpus-evidence" for f in partial_result["failures"])


def test_enablement_and_shipped_claim_refused() -> None:
    """R13 — accidental enablement or shipped claims fail closed."""
    claim = _full_trust_claim(trust_complete=False)
    claim["enabled"] = True
    claim["shipped"] = True
    result = marketplace_trust_gate(claim)
    assert result["verdict"] == "fail"
    errors = {f["error"] for f in result["failures"]}
    assert "p3-stub-enablement-refused" in errors
    assert "p3-stub-shipped-claim-refused" in errors


def test_default_off_configuration() -> None:
    """R18 — marketplace registry is never selected by default."""
    assert package_registry_default_off({}) is True
    assert package_registry_default_off({"graphExecution": {"packages": {}}}) is True
    assert (
        package_registry_default_off(
            {"graphExecution": {"packages": {"registry": "local-catalog"}}}
        )
        is True
    )
    assert package_registry_kind({}) == "local-catalog"
    assert (
        package_registry_kind({"graphExecution": {"packages": {"registry": "marketplace"}}})
        == "marketplace"
    )
    assert (
        package_registry_default_off(
            {"graphExecution": {"packages": {"registry": "marketplace"}}}
        )
        is False
    )

    with pytest.raises(PackageResolverError, match="lockfile context"):
        resolve_registry_package(
            _valid_pin_reference(),
            cfg={"graphExecution": {"packages": {"registry": "local-catalog"}}},
        )

    marketplace_result = resolve_registry_package(
        _valid_pin_reference(),
        cfg={"graphExecution": {"packages": {"registry": "marketplace"}}},
    )
    assert marketplace_result["status"] == "not-enabled"
    assert marketplace_result["remoteResolution"] is False
