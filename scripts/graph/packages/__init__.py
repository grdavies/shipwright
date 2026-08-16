"""Semver workflow packages, lockfile trust, and expansion-tuple approval (PRD 272 R19–R22)."""
from __future__ import annotations

from graph.packages.adoption import (
    AdoptionMetrics,
    NAMED_CONSUMERS,
    NAMED_PRODUCERS,
    report_adoption_metrics,
)
from graph.packages.approval_tuple import (
    ExpansionApproval,
    ExpansionTuple,
    assert_expansion_approved,
    approve_expansion_tuple,
    compute_expansion_tuple_digest,
    expansion_is_additive,
    expansion_requires_reapproval,
    record_expansion_tuple_on_receipt,
)
from graph.packages.lockfile import (
    LOCKFILE_SCHEMA_VERSION,
    LockfileError,
    compute_lock_digest,
    load_lockfile,
    require_lock_edit_approval,
    validate_lock_transitive_closure,
)
from graph.packages.resolver import (
    PackageResolver,
    PackageResolverError,
    ResolvedPackage,
    discover_packages,
)
from graph.packages.trust import (
    TrustAnchorError,
    TrustAnchorStore,
    load_trust_anchors,
    sign_package_content,
    verify_package_signature,
)

__all__ = [
    "LOCKFILE_SCHEMA_VERSION",
    "AdoptionMetrics",
    "ExpansionApproval",
    "ExpansionTuple",
    "LockfileError",
    "NAMED_CONSUMERS",
    "NAMED_PRODUCERS",
    "PackageResolver",
    "PackageResolverError",
    "ResolvedPackage",
    "TrustAnchorError",
    "TrustAnchorStore",
    "approve_expansion_tuple",
    "assert_expansion_approved",
    "compute_expansion_tuple_digest",
    "compute_lock_digest",
    "discover_packages",
    "expansion_is_additive",
    "expansion_requires_reapproval",
    "load_lockfile",
    "load_trust_anchors",
    "record_expansion_tuple_on_receipt",
    "report_adoption_metrics",
    "require_lock_edit_approval",
    "resolve_trusted_packages",
    "sign_package_content",
    "validate_lock_transitive_closure",
    "verify_package_signature",
]


def resolve_trusted_packages(
    *,
    lock_path: str,
    trust_store: TrustAnchorStore,
    repo_root: str,
) -> tuple[ResolvedPackage, ...]:
    """Resolve and verify every pinned package in a lockfile (discover≠trust)."""
    resolver = PackageResolver(
        lock_path=lock_path,
        trust_store=trust_store,
        repo_root=repo_root,
    )
    return resolver.resolve_all()
