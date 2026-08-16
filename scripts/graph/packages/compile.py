#!/usr/bin/env python3
"""High-level package trust compile path (PRD 272 R19–R22)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from graph.kernel_compiler import KERNEL_VERSION, KernelCompilationError, compile_workflow_graph
from graph.packages.approval_tuple import (
    ExpansionApproval,
    ExpansionTuple,
    assert_expansion_approved,
    expansion_requires_reapproval,
)
from graph.packages.resolver import PackageResolver, ResolvedPackage
from graph.packages.trust import TrustAnchorStore


def requirement_set_digest(required_capability_ids: Mapping[str, str]) -> str:
    canonical = (
        json.dumps(required_capability_ids, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def pack_digest_from_resolved(packages: tuple[ResolvedPackage, ...]) -> str:
    body = {package.pin: package.digest for package in packages}
    canonical = (
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_expansion_tuple(
    *,
    packages: tuple[ResolvedPackage, ...],
    profile_id: str,
    required_capability_ids: Mapping[str, str],
    kernel_version: str = KERNEL_VERSION,
) -> ExpansionTuple:
    return ExpansionTuple(
        pack_digest=pack_digest_from_resolved(packages),
        profile_id=profile_id,
        requirement_set_digest=requirement_set_digest(required_capability_ids),
        kernel_version=kernel_version,
    )


def compile_with_package_trust(
    graph: Mapping[str, Any],
    *,
    resolver: PackageResolver,
    trust_store: TrustAnchorStore,
    profile_id: str,
    required_capability_ids: Mapping[str, str],
    expansion_approval: Mapping[str, Any] | None,
    baseline_nodes: Mapping[str, Any] | None = None,
    **kernel_options: Any,
) -> dict[str, Any]:
    """Resolve trusted packs, assert expansion approval, and compile through kernel."""
    _ = trust_store  # resolution already verified signatures
    packages = resolver.resolve_all()
    expansion_tuple = build_expansion_tuple(
        packages=packages,
        profile_id=profile_id,
        required_capability_ids=required_capability_ids,
    )
    approval = assert_expansion_approved(expansion_approval, expansion_tuple)
    if baseline_nodes is not None:
        baseline = baseline_nodes.get("spec", {}).get("nodes", ())
        candidate = graph.get("spec", {}).get("nodes", ())
        if expansion_requires_reapproval(baseline, candidate):
            raise KernelCompilationError(
                "expansion weakens approved graph; fresh approval required"
            )
    compiled = compile_workflow_graph(
        graph,
        expansion_approval=approval.to_dict(),
        expansion_tuple=expansion_tuple.to_dict(),
        **kernel_options,
    )
    compiled["expansionApproval"] = approval.to_dict()
    compiled["expansionTuple"] = expansion_tuple.to_dict()
    return compiled
