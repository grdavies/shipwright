#!/usr/bin/env python3
"""Workflow package authoring SDK — schema, node-kind, capability, and instruction conformance (PRD 280 gap-326)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from capability_manifest_validate import validate_capability_block
from graph.ir import WorkflowGraphValidationError, validate_workflow_graph
from graph.kernel_compiler import KERNEL_VERSION
from graph.node_kinds import CLOSED_NODE_KINDS, NODE_KIND_REGISTRY, lookup_node_kind
from graph.packages.trust import package_content_digest
from kernel_classification import load_classification, normalize_step
from skills_spec_guard import Finding, _scan_skill_md, partition_findings

PACKAGE_KIND = "WorkflowPackage"
PACKAGE_SCHEMA_VERSION = 1
KERNEL_COMPAT_TIER = "2.x"
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
MUTATING_KINDS = frozenset({"command", "convergence-loop"})


@dataclass(frozen=True)
class ConformanceFinding:
    phase: str
    code: str
    message: str
    severity: str = "critical"

    def as_dict(self) -> dict[str, str]:
        payload = {
            "phase": self.phase,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        return payload


def _load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"package document must be an object: {path}")
    return document


def extract_graph(pack: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    fragment = pack.get("fragment")
    if isinstance(fragment, Mapping):
        graph = fragment.get("graph")
        if isinstance(graph, Mapping):
            return dict(graph), "fragment.graph"
    graph = pack.get("graph")
    if isinstance(graph, Mapping):
        return dict(graph), "graph"
    return None, ""


def _graph_nodes_edges(graph: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if graph.get("kind") == "WorkflowGraph":
        spec = graph.get("spec") or {}
        nodes = list(spec.get("nodes") or [])
        edges = list(spec.get("edges") or [])
        return nodes, edges
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    return nodes, edges


def validate_pack_schema(pack: Mapping[str, Any]) -> list[ConformanceFinding]:
    findings: list[ConformanceFinding] = []
    phase = "schema"
    if int(pack.get("schemaVersion") or 0) != PACKAGE_SCHEMA_VERSION:
        findings.append(
            ConformanceFinding(phase, "schema-version", "schemaVersion must be 1")
        )
    if pack.get("kind") != PACKAGE_KIND:
        findings.append(
            ConformanceFinding(phase, "package-kind", f"kind must be {PACKAGE_KIND!r}")
        )
    name = pack.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"^[a-z][a-z0-9-]{0,62}$", name):
        findings.append(ConformanceFinding(phase, "package-name", "name must be a lowercase slug"))
    version = pack.get("version")
    if not isinstance(version, str) or not SEMVER_RE.fullmatch(version):
        findings.append(ConformanceFinding(phase, "package-version", "version must be semver x.y.z"))
    graph, graph_path = extract_graph(pack)
    if graph is None:
        findings.append(
            ConformanceFinding(phase, "graph-missing", "pack must declare graph or fragment.graph")
        )
    elif graph_path:
        nodes, _ = _graph_nodes_edges(graph)
        if not nodes:
            findings.append(
                ConformanceFinding(phase, "graph-empty", f"{graph_path} must contain at least one node")
            )
    dependencies = pack.get("dependencies")
    if dependencies is not None:
        if not isinstance(dependencies, list):
            findings.append(
                ConformanceFinding(phase, "dependencies-shape", "dependencies must be an array when present")
            )
        else:
            for index, dep in enumerate(dependencies):
                if not isinstance(dep, str) or "@" not in dep:
                    findings.append(
                        ConformanceFinding(
                            phase,
                            "dependency-pin",
                            f"dependencies[{index}] must be a name@version pin",
                        )
                    )
    return findings


def validate_node_kinds(
    pack: Mapping[str, Any],
    *,
    repo_root: Path,
) -> list[ConformanceFinding]:
    findings: list[ConformanceFinding] = []
    phase = "nodeKinds"
    graph, graph_path = extract_graph(pack)
    if graph is None:
        return findings
    if graph.get("kind") == "WorkflowGraph":
        try:
            validate_workflow_graph(graph)
        except WorkflowGraphValidationError as exc:
            findings.append(
                ConformanceFinding(phase, "workflow-graph-schema", f"{graph_path}: {exc}")
            )
    nodes, _ = _graph_nodes_edges(graph)
    known_steps: set[str] | None = None
    try:
        classification = load_classification(repo_root)
        known_steps = set()
        for item in classification.get("planPolicySteps") or []:
            if isinstance(item, Mapping) and item.get("id"):
                known_steps.add(normalize_step(str(item["id"])))
    except (OSError, ValueError, json.JSONDecodeError):
        known_steps = None
    seen_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, Mapping):
            findings.append(ConformanceFinding(phase, "node-shape", "graph node must be an object"))
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            findings.append(ConformanceFinding(phase, "node-id", "each node requires a non-empty id"))
            continue
        if node_id in seen_ids:
            findings.append(ConformanceFinding(phase, "node-id-duplicate", f"duplicate node id: {node_id}"))
        seen_ids.add(node_id)
        kind = str(node.get("kind") or "")
        if not is_closed_node_kind(kind):
            findings.append(
                ConformanceFinding(
                    phase,
                    "node-kind-closed",
                    f"node {node_id} uses unknown or closed node kind {kind!r}",
                )
            )
            continue
        spec = lookup_node_kind(kind)
        if spec and spec.read_only:
            isolation = node.get("isolation") or {}
            write_scope = isolation.get("writeScope") if isinstance(isolation, Mapping) else None
            if write_scope not in (None, "none", "read-only"):
                findings.append(
                    ConformanceFinding(
                        phase,
                        "read-only-side-effect",
                        f"node {node_id} kind {kind!r} is read-only but declares writeScope={write_scope!r}",
                    )
                )
        target = node.get("target")
        if isinstance(target, Mapping):
            step = target.get("step")
            if isinstance(step, str) and step and known_steps is not None:
                normalized = normalize_step(step)
                if normalized not in known_steps:
                    findings.append(
                        ConformanceFinding(
                            phase,
                            "unknown-command-step",
                            f"node {node_id} target.step {step!r} is not in kernel command catalog",
                        )
                    )
    return findings


def is_closed_node_kind(kind: str) -> bool:
    return kind in CLOSED_NODE_KINDS


def validate_capabilities(pack: Mapping[str, Any]) -> list[ConformanceFinding]:
    findings: list[ConformanceFinding] = []
    phase = "capabilities"
    capabilities = pack.get("capabilities")
    if capabilities is None:
        return findings
    if not isinstance(capabilities, list):
        findings.append(
            ConformanceFinding(phase, "capabilities-shape", "capabilities must be an array when present")
        )
        return findings
    for index, block in enumerate(capabilities):
        source = f"capabilities[{index}]"
        if not isinstance(block, Mapping):
            findings.append(
                ConformanceFinding(phase, "capability-object", f"{source} must be an object")
            )
            continue
        cap = block.get("capability") if "capability" in block else block
        for error in validate_capability_block(cap, source=source):
            findings.append(ConformanceFinding(phase, "capability-schema", error))
    return findings


def validate_side_effects(pack: Mapping[str, Any]) -> list[ConformanceFinding]:
    findings: list[ConformanceFinding] = []
    phase = "sideEffects"
    graph, _ = extract_graph(pack)
    if graph is None:
        return findings
    declared = pack.get("declaredSideEffects")
    declared_set: set[str] = set()
    if declared is not None:
        if not isinstance(declared, list) or not all(isinstance(item, str) for item in declared):
            findings.append(
                ConformanceFinding(
                    phase,
                    "declared-side-effects-shape",
                    "declaredSideEffects must be a string array when present",
                )
            )
        else:
            declared_set = set(declared)
    node_caps = pack.get("nodeCapabilities")
    node_cap_map: dict[str, Any] = node_caps if isinstance(node_caps, Mapping) else {}
    nodes, _ = _graph_nodes_edges(graph)
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        node_id = str(node.get("id") or "")
        kind = str(node.get("kind") or "")
        requested: set[str] = set()
        entry = node_cap_map.get(node_id)
        if isinstance(entry, Mapping):
            side_effects = entry.get("sideEffects")
            if isinstance(side_effects, list):
                requested = {str(item) for item in side_effects}
        if kind in MUTATING_KINDS and not requested and not declared_set:
            findings.append(
                ConformanceFinding(
                    phase,
                    "undeclared-mutating-side-effect",
                    f"mutating node {node_id} must declare sideEffects via nodeCapabilities or declaredSideEffects",
                )
            )
        undeclared = requested - declared_set
        if undeclared:
            findings.append(
                ConformanceFinding(
                    phase,
                    "side-effect-not-declared",
                    f"node {node_id} requests undeclared side effects: {', '.join(sorted(undeclared))}",
                )
            )
    return findings


def validate_cycles(pack: Mapping[str, Any]) -> list[ConformanceFinding]:
    findings: list[ConformanceFinding] = []
    phase = "cycles"
    graph, graph_path = extract_graph(pack)
    if graph is None:
        return findings
    nodes, edges = _graph_nodes_edges(graph)
    node_ids = [str(node.get("id")) for node in nodes if isinstance(node, Mapping) and node.get("id")]
    known = set(node_ids)
    incoming = {node_id: 0 for node_id in known}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in known}
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if source not in known or target not in known:
            continue
        incoming[target] += 1
        outgoing[source].append(target)
    ready = [node_id for node_id, count in incoming.items() if count == 0]
    ordered = 0
    while ready:
        node_id = ready.pop()
        ordered += 1
        for successor in outgoing[node_id]:
            incoming[successor] -= 1
            if incoming[successor] == 0:
                ready.append(successor)
    if ordered != len(known) and edges:
        findings.append(
            ConformanceFinding(
                phase,
                "graph-cycle",
                f"{graph_path} contains a cycle or unreachable nodes in edge topology",
            )
        )
    return findings


def lint_instruction_artifacts(
    pack: Mapping[str, Any],
    *,
    pack_root: Path,
    repo_root: Path,
) -> tuple[list[ConformanceFinding], list[ConformanceFinding]]:
    critical: list[ConformanceFinding] = []
    advisory: list[ConformanceFinding] = []
    phase = "instructionLint"
    instructions = pack.get("instructions")
    if instructions is None:
        return critical, advisory
    if not isinstance(instructions, list):
        critical.append(
            ConformanceFinding(phase, "instructions-shape", "instructions must be an array when present")
        )
        return critical, advisory
    for index, rel in enumerate(instructions):
        if not isinstance(rel, str) or not rel.strip():
            critical.append(
                ConformanceFinding(phase, "instruction-path", f"instructions[{index}] must be a non-empty path")
            )
            continue
        skill_path = (pack_root / rel).resolve()
        try:
            skill_path.relative_to(pack_root.resolve())
        except ValueError:
            critical.append(
                ConformanceFinding(
                    phase,
                    "instruction-escape",
                    f"instructions[{index}] must stay within pack root: {rel!r}",
                )
            )
            continue
        if not skill_path.is_file():
            critical.append(
                ConformanceFinding(phase, "instruction-missing", f"instruction artifact missing: {rel}")
            )
            continue
        tree_prefix = "."
        skill_findings: list[Finding] = _scan_skill_md(repo_root, skill_path, tree_prefix)
        hard, soft = partition_findings(skill_findings)
        for finding in hard:
            critical.append(
                ConformanceFinding(
                    phase,
                    finding.code,
                    f"{rel}: {finding.message}",
                    severity="critical",
                )
            )
        for finding in soft:
            advisory.append(
                ConformanceFinding(
                    phase,
                    finding.code,
                    f"{rel}: {finding.message}",
                    severity="advisory",
                )
            )
    return critical, advisory


def build_conformance_report(
    pack: Mapping[str, Any],
    *,
    pack_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    pack_root = pack_path.parent
    phases: dict[str, Any] = {}
    all_findings: list[ConformanceFinding] = []

    schema_findings = validate_pack_schema(pack)
    phases["schema"] = {"verdict": "pass" if not schema_findings else "fail", "findings": [f.as_dict() for f in schema_findings]}
    all_findings.extend(schema_findings)

    node_findings = validate_node_kinds(pack, repo_root=repo_root)
    phases["nodeKinds"] = {"verdict": "pass" if not node_findings else "fail", "findings": [f.as_dict() for f in node_findings]}
    all_findings.extend(node_findings)

    cap_findings = validate_capabilities(pack)
    phases["capabilities"] = {"verdict": "pass" if not cap_findings else "fail", "findings": [f.as_dict() for f in cap_findings]}
    all_findings.extend(cap_findings)

    side_findings = validate_side_effects(pack)
    phases["sideEffects"] = {"verdict": "pass" if not side_findings else "fail", "findings": [f.as_dict() for f in side_findings]}
    all_findings.extend(side_findings)

    cycle_findings = validate_cycles(pack)
    phases["cycles"] = {"verdict": "pass" if not cycle_findings else "fail", "findings": [f.as_dict() for f in cycle_findings]}
    all_findings.extend(cycle_findings)

    lint_critical, lint_advisory = lint_instruction_artifacts(pack, pack_root=pack_root, repo_root=repo_root)
    phases["instructionLint"] = {
        "verdict": "pass" if not lint_critical else "fail",
        "findings": [f.as_dict() for f in lint_critical],
        "advisories": [f.as_dict() for f in lint_advisory],
    }
    all_findings.extend(lint_critical)

    critical = [finding for finding in all_findings if finding.severity == "critical"]
    digest = package_content_digest(pack)
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "WorkflowPackConformanceReport",
        "packPin": f"{pack.get('name')}@{pack.get('version')}",
        "packPath": str(pack_path),
        "verdict": "pass" if not critical else "fail",
        "criticalCount": len(critical),
        "findings": [finding.as_dict() for finding in critical],
        "phases": phases,
        "kernelCompatibility": {
            "tier": KERNEL_COMPAT_TIER,
            "baselineKernelVersion": KERNEL_VERSION,
            "statement": (
                f"Compatible with Shipwright workflow kernel {KERNEL_COMPAT_TIER} "
                f"(closed node kinds including human-action; baseline {KERNEL_VERSION})"
            ),
            "closedNodeKinds": sorted(CLOSED_NODE_KINDS),
            "nodeKindRegistry": [spec.as_dict() for spec in sorted(NODE_KIND_REGISTRY.values(), key=lambda item: item.id)],
        },
        "adoption": {
            "requiresDigestBoundConfirmation": True,
            "contentDigest": digest,
            "confirmationPrompt": (
                f"Confirm adoption of {pack.get('name')}@{pack.get('version')} at digest {digest} before enablement"
            ),
        },
        "orgExtensionMechanism": {
            "description": (
                "Third-party workflow packs are org extensions: semver artifacts under "
                ".sw/workflows/packages/, lock-pinned and trust-verified at compile time — "
                "discovery does not imply trust."
            ),
            "guideRef": "docs/guides/workflows.md#workflow-packages-trust-and-expansion-tuples",
        },
    }
    if lint_advisory:
        report["advisories"] = [finding.as_dict() for finding in lint_advisory]
    return report


def validate_pack(
    pack_path: Path,
    *,
    repo_root: Path | None = None,
    report_path: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    repo = (repo_root or Path.cwd()).resolve()
    path = pack_path.resolve()
    pack = _load_json(path)
    report = build_conformance_report(pack, pack_path=path, repo_root=repo)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return (0 if report["verdict"] == "pass" else 1, report)


def confirm_adoption(pack_path: Path, *, expected_digest: str, repo_root: Path | None = None) -> tuple[int, dict[str, Any]]:
    repo = (repo_root or Path.cwd()).resolve()
    path = pack_path.resolve()
    pack = _load_json(path)
    digest = package_content_digest(pack)
    if digest != expected_digest:
        payload = {
            "verdict": "fail",
            "cause": "digest-mismatch",
            "expectedDigest": expected_digest,
            "actualDigest": digest,
        }
        return 1, payload
    exit_code, report = validate_pack(path, repo_root=repo)
    if exit_code != 0:
        return exit_code, report
    payload = {
        "verdict": "pass",
        "contentDigest": digest,
        "confirmation": "digest-bound adoption confirmed",
        "packPin": f"{pack.get('name')}@{pack.get('version')}",
    }
    return 0, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Workflow package authoring SDK (gap-326)")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_cmd = sub.add_parser("validate", help="Run full conformance validation and emit report JSON")
    validate_cmd.add_argument("pack", type=Path, help="Path to WorkflowPackage JSON")
    validate_cmd.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    validate_cmd.add_argument("--report", type=Path, default=None, help="Optional report output path")

    confirm_cmd = sub.add_parser("confirm-adoption", help="Digest-bound adoption gate (R18)")
    confirm_cmd.add_argument("pack", type=Path, help="Path to WorkflowPackage JSON")
    confirm_cmd.add_argument("--digest", required=True, help="Expected content digest")
    confirm_cmd.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")

    args = parser.parse_args(argv)
    if args.command == "validate":
        exit_code, report = validate_pack(args.pack, repo_root=args.root, report_path=args.report)
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return exit_code
    if args.command == "confirm-adoption":
        exit_code, payload = confirm_adoption(args.pack, expected_digest=args.digest, repo_root=args.root)
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return exit_code
    return 2


if __name__ == "__main__":
    sys.exit(main())
