#!/usr/bin/env python3
"""WorkflowPackage marketplace P3 spec stub — trust policy metadata, fail-closed resolver (PRD 333 phase 10)."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from graph.packages.trust import TrustAnchorStore

REGISTRY_ID = "marketplace"
SPEC_REL_PATH = "core/providers/workflow-package/marketplace.md"
PROGRAM_PRIORITY_ID = "workflow-package-marketplace"
TRUST_POLICY_VERSION = "1.0.0"

MANDATORY_TRUST_DIMENSIONS: tuple[str, ...] = (
    "digest-pinning",
    "signer-policy",
    "revocation",
    "transitive-dependency-policy",
    "reproducible-resolution",
    "audit-evidence",
)

NORMALIZED_MARKETPLACE_REFUSALS: frozenset[str] = frozenset(
    {
        "unpinned-reference",
        "unsigned-package",
        "revoked-signer",
        "pin-mismatch",
        "transitive-policy-refused",
        "non-reproducible-resolution",
        "missing-audit-evidence",
        "malformed-registry",
        "not-enabled",
    }
)

MARKETPLACE_CORPUS_SCENARIOS: frozenset[str] = frozenset(
    {
        "marketplace-trust-resolution",
        "package-transitive-closure",
        "marketplace-revocation-handling",
    }
)

SHIPPED_PACKAGE_REGISTRIES: frozenset[str] = frozenset({"local-catalog"})
P3_PACKAGE_REGISTRY_STUBS: frozenset[str] = frozenset({REGISTRY_ID})
ALL_PACKAGE_REGISTRIES: frozenset[str] = SHIPPED_PACKAGE_REGISTRIES | P3_PACKAGE_REGISTRY_STUBS

MARKETPLACE_CONFORMANCE_FIXTURES_REL = Path("scripts/test/fixtures/workflow-package-marketplace")

PIN_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*@[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
HTTPS_REGISTRY_RE = re.compile(
    r"^https://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=-]+)?/?$"
)


class MarketplaceRegistryError(ValueError):
    """Invalid marketplace pin reference or gate state."""


@dataclass(frozen=True)
class MarketplacePinReference:
    """Validated lock-pinned marketplace reference (local validation only)."""

    pin: str
    digest: str
    signer_key_id: str
    dependencies: tuple[str, ...] = ()
    registry_url: str | None = None


@dataclass(frozen=True)
class MarketplaceTrustContext:
    """Inputs for trust-policy evaluation (hermetic fixtures / enablement tests)."""

    pin: str
    digest: str
    signer_key_id: str
    expected_digest: str
    expected_signer_key_id: str
    dependencies: tuple[str, ...] = ()
    resolved_dependencies: tuple[str, ...] = ()
    signed: bool = True
    signer_status: str = "active"
    reproducible: bool = True
    prior_resolution_digest: str | None = None
    audit_events: tuple[Mapping[str, Any], ...] = ()
    require_audit: bool = True


def validate_registry_url(registry_url: str | None) -> str | None:
    if registry_url is None:
        return None
    raw = str(registry_url).strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        raise MarketplaceRegistryError("malformed-registry")
    if parsed.username or parsed.password:
        raise MarketplaceRegistryError("malformed-registry")
    if not HTTPS_REGISTRY_RE.match(raw):
        raise MarketplaceRegistryError("malformed-registry")
    return raw.rstrip("/")


def validate_pinned_reference(raw: Mapping[str, Any]) -> MarketplacePinReference:
    """Validate a lock-pinned marketplace reference without remote resolution (R10, R21)."""
    pin = str(raw.get("pin") or "").strip()
    if not PIN_IDENTITY_RE.match(pin):
        raise MarketplaceRegistryError("unpinned-reference")

    digest = str(raw.get("digest") or "").strip().lower()
    if not DIGEST_RE.match(digest):
        raise MarketplaceRegistryError("pin-mismatch")

    signer_key_id = str(raw.get("signerKeyId") or "").strip()
    if not signer_key_id:
        raise MarketplaceRegistryError("unsigned-package")

    deps_raw = raw.get("dependencies") or ()
    if not isinstance(deps_raw, (list, tuple)):
        raise MarketplaceRegistryError("transitive-policy-refused")
    dependencies = tuple(str(item).strip() for item in deps_raw if str(item).strip())
    for dep in dependencies:
        if not PIN_IDENTITY_RE.match(dep):
            raise MarketplaceRegistryError("transitive-policy-refused")

    registry_url = validate_registry_url(raw.get("registryUrl"))

    return MarketplacePinReference(
        pin=pin,
        digest=digest,
        signer_key_id=signer_key_id,
        dependencies=dependencies,
        registry_url=registry_url,
    )


def marketplace_capability_matrix() -> dict[str, Any]:
    return {
        "trustPolicyVersion": TRUST_POLICY_VERSION,
        "registry": REGISTRY_ID,
        "dimensions": list(MANDATORY_TRUST_DIMENSIONS),
        "normalizedRefusals": sorted(NORMALIZED_MARKETPLACE_REFUSALS),
        "corpusScenarios": sorted(MARKETPLACE_CORPUS_SCENARIOS),
    }


def register_marketplace_registry_stub() -> dict[str, Any]:
    """Registration surface for package resolver — metadata only, not enabled."""
    matrix = marketplace_capability_matrix()
    return {
        "registryId": REGISTRY_ID,
        "status": "not-enabled",
        "shipped": False,
        "trustComplete": False,
        "parityComplete": False,
        "specPath": SPEC_REL_PATH,
        "programPriorityId": PROGRAM_PRIORITY_ID,
        "trustPolicyVersion": matrix["trustPolicyVersion"],
        "mandatoryDimensions": list(MANDATORY_TRUST_DIMENSIONS),
        "corpusScenarios": sorted(MARKETPLACE_CORPUS_SCENARIOS),
        "normalizedRefusals": sorted(NORMALIZED_MARKETPLACE_REFUSALS),
    }


def evaluate_marketplace_trust(context: MarketplaceTrustContext) -> dict[str, Any]:
    """Evaluate one trust context; fail closed on any violated dimension (R10, R11, R21)."""
    failures: list[dict[str, Any]] = []

    if not PIN_IDENTITY_RE.match(context.pin):
        failures.append({"dimension": "digest-pinning", "error": "unpinned-reference"})
    elif context.digest != context.expected_digest:
        failures.append({"dimension": "digest-pinning", "error": "pin-mismatch"})

    if not context.signed or not context.signer_key_id:
        failures.append({"dimension": "signer-policy", "error": "unsigned-package"})
    elif context.signer_key_id != context.expected_signer_key_id:
        failures.append({"dimension": "signer-policy", "error": "unsigned-package"})

    if context.signer_status == "revoked":
        failures.append({"dimension": "revocation", "error": "revoked-signer"})
    elif context.signer_status == "expired":
        failures.append({"dimension": "revocation", "error": "revoked-signer"})

    required_closure = {context.pin, *context.dependencies}
    observed_closure = {context.pin, *context.resolved_dependencies}
    if required_closure != observed_closure:
        failures.append(
            {
                "dimension": "transitive-dependency-policy",
                "error": "transitive-policy-refused",
                "missing": sorted(required_closure - observed_closure),
            }
        )

    if (
        not context.reproducible
        or (
            context.prior_resolution_digest is not None
            and context.prior_resolution_digest != context.digest
        )
    ):
        failures.append(
            {"dimension": "reproducible-resolution", "error": "non-reproducible-resolution"}
        )

    if context.require_audit and not context.audit_events:
        failures.append({"dimension": "audit-evidence", "error": "missing-audit-evidence"})

    return {
        "verdict": "ok" if not failures else "fail",
        "action": "marketplace-trust-prerequisites",
        "registry": REGISTRY_ID,
        "failures": failures,
    }


def marketplace_trust_gate(claim: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on trust or enablement claims for the P3 stub (R10, R13, R18, R21)."""
    failures: list[dict[str, Any]] = []
    registry = str(claim.get("registry") or claim.get("registryId") or "")
    if registry != REGISTRY_ID:
        failures.append({"field": "registry", "error": "unexpected-registry", "observed": registry})

    policy_version = str(claim.get("trustPolicyVersion") or "")
    if policy_version != TRUST_POLICY_VERSION:
        failures.append(
            {
                "field": "trustPolicyVersion",
                "error": "stale-trust-policy",
                "observed": policy_version,
                "expected": TRUST_POLICY_VERSION,
            }
        )

    dimensions = claim.get("dimensions") or {}
    missing = [dim for dim in MANDATORY_TRUST_DIMENSIONS if dim not in dimensions]
    for dim in missing:
        failures.append({"field": "dimensions", "error": "missing-trust-dimension", "dimension": dim})

    corpus_ids = claim.get("corpusScenarioIds") or claim.get("corpusScenarios") or []
    if not isinstance(corpus_ids, (list, tuple, set)):
        corpus_ids = []
    missing_corpus = sorted(MARKETPLACE_CORPUS_SCENARIOS - set(corpus_ids))
    for scenario in missing_corpus:
        failures.append(
            {"field": "corpusScenarioIds", "error": "missing-corpus-evidence", "scenario": scenario}
        )

    if claim.get("trustComplete") is True:
        failures.append({"field": "trustComplete", "error": "p3-stub-trust-claim-refused"})
    if claim.get("parityComplete") is True:
        failures.append({"field": "parityComplete", "error": "p3-stub-parity-claim-refused"})
    if claim.get("enabled") is True or claim.get("status") == "enabled":
        failures.append({"field": "status", "error": "p3-stub-enablement-refused"})
    if claim.get("shipped") is True:
        failures.append({"field": "shipped", "error": "p3-stub-shipped-claim-refused"})

    return {
        "verdict": "ok" if not failures else "fail",
        "action": "marketplace-trust-gate",
        "registry": REGISTRY_ID,
        "failures": failures,
    }


def marketplace_default_off(cfg: Mapping[str, Any]) -> bool:
    """True when workflow config does not silently select marketplace (R18)."""
    graph_exec = cfg.get("graphExecution") or {}
    packages = graph_exec.get("packages") or {}
    registry_kind = str(packages.get("registry") or "local-catalog").strip().lower()
    return registry_kind != REGISTRY_ID


def resolve_marketplace_package(
    raw_reference: Mapping[str, Any],
    *,
    trust_store: TrustAnchorStore | None = None,
) -> dict[str, Any]:
    """Validate pinned reference and return not-enabled — no remote resolution (R10, R13, R18, R21)."""
    reference = validate_pinned_reference(raw_reference)
    if trust_store is not None:
        status = trust_store.key_status(reference.signer_key_id)
        if status == "revoked":
            raise MarketplaceRegistryError("revoked-signer")
        if status == "expired":
            raise MarketplaceRegistryError("revoked-signer")
        if status == "unknown":
            raise MarketplaceRegistryError("unsigned-package")

    registration = register_marketplace_registry_stub()
    return {
        "status": "not-enabled",
        "registry": REGISTRY_ID,
        "pin": reference.pin,
        "digest": reference.digest,
        "signerKeyId": reference.signer_key_id,
        "dependencies": list(reference.dependencies),
        "registryUrl": reference.registry_url,
        "remoteResolution": False,
        "installation": False,
        "shipped": registration["shipped"],
        "trustComplete": registration["trustComplete"],
        "parityComplete": registration["parityComplete"],
        "notice": "workflow-package marketplace is a P3 spec stub — not shipped",
    }


def conformance_metadata_only() -> dict[str, Any]:
    payload = register_marketplace_registry_stub()
    payload["action"] = "marketplace-registry-conformance-metadata"
    return payload
