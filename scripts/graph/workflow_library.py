#!/usr/bin/env python3
"""Git-reviewable, approval-gated WorkflowGraph template library."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.absolute_floor import (  # noqa: E402
    AbsoluteFloorError,
    assert_anti_ratchet_ceiling,
    evaluate_after_profile_and_inject,
    required_capabilities_from_graph,
)
from graph.cutover import CutoverStage, DogfoodEvidence  # noqa: E402
from graph.dynamic_proposal import (
    ProposalBudget,
    ProposalDecision,
    assert_auth_capabilities_nonskippable,
    evaluate_dynamic_proposal,
    is_required_capability_node,
)  # noqa: E402
from graph.ir import (  # noqa: E402
    validate_fragment_use_entry,
    WorkflowGraphValidationError,
)  # noqa: E402
from graph.detectors.registry import CAPABILITY_AUTH  # noqa: E402
from graph.kernel_compiler import compile_workflow_graph  # noqa: E402
from graph.scheduling_modes import ALLOWED_EXTERNAL_AUTHORIZERS  # noqa: E402

LIBRARY_VERSION = 1
PLAN_POLICY_CANONICAL = "canonical"
PLAN_POLICY_PROPOSED = "proposed"
PROMOTION_SAMPLE_FLOOR = 3
PROMOTION_CONFIDENCE_FLOOR = 0.95
PROMOTION_READY_WITHOUT_REWORK_FLOOR = 1.0
PROMOTION_COVERAGE_REGRESSION_CEILING = 0.0
PROMOTION_SMALL_N_REFUSAL_THRESHOLD = PROMOTION_SAMPLE_FLOOR
DEFAULT_DEMOTION_EXPOSURE_WINDOW_SECONDS = 3600
DEFAULT_IN_FLIGHT_RUN_POLICY = "drain"
ALLOWED_IN_FLIGHT_RUN_POLICIES = frozenset({"drain", "cancel"})
MAX_PREDICTION_ERROR = 0.25
ALLOWED_PLAN_POLICY_AUTHORIZERS = ALLOWED_EXTERNAL_AUTHORIZERS | frozenset(
    {"workflow-library-promotion-gate"}
)
DIGEST_CONFIRMATION_COMMANDS = frozenset({"sw-deliver"})
REQUIRED_INPUT_STRATA = frozenset({"dogfood-deliver", "non-dogfood-deliver"})
DEFAULT_LIBRARY_ROOT = Path(".sw/workflows")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_PLACEHOLDER_RE = re.compile(r"\$\{([a-z][a-z0-9_-]{0,62})\}")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|credential|password|private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"\b(?:gh[opsu]_|github_pat_|sk-(?:live|test)-|AKIA)[A-Za-z0-9_-]{8,})"
)
_LOCAL_PATH_RE = re.compile(
    r"(?:^|[\s='\"])(?:/Users/|/home/|/tmp/|/var/folders/|[A-Za-z]:\\)"
)
_PARAM_TYPES = frozenset({"string", "integer", "boolean"})
_USE_PIN_RE = re.compile(r"^([a-z][a-z0-9-]{0,62})@(\d+)$")
FRAGMENT_KIND = "WorkflowFragment"
MAX_FRAGMENT_EXPANSION_DEPTH = 8
MAX_EXPANDED_NODES = 64
MAX_EXPANDED_EDGES = 128


class WorkflowLibraryError(ValueError):
    """Raised when a template is unsafe, invalid, or not approved."""


@dataclass(frozen=True)
class PromotionSample:
    """One run's evidence row for plan-policy promotion."""

    run_id: str
    stratum: str
    template_digest: str
    prediction_error: float
    required_capability_regression: bool
    ready_without_rework: bool
    command: str
    paired_canonical_run_id: str = ""
    confidence: float = 1.0
    coverage_score: float = 1.0
    perfect_score: bool = False


@dataclass(frozen=True)
class DigestConfirmation:
    """Digest-bound human confirmation on an existing operator command."""

    command: str
    digest: str
    confirmed_by: str
    confirmed_at: str


@dataclass(frozen=True)
class PlanPolicyPromotionEvidence:
    """Integrity-scoped promotion gate inputs."""

    samples: tuple[PromotionSample, ...]
    authorizer: str
    confirmation: DigestConfirmation
    receipts_digest: str | None = None
    calibration_digest: str | None = None


@dataclass(frozen=True)
class PlanPolicyPromotionVerdict:
    verdict: str
    target_policy: str
    reasons: tuple[str, ...]
    policy_digest: str | None = None

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"


@dataclass(frozen=True)
class PromotionPolicyDocument:
    """Approval-gated promotion policy; hard floors may be raised but never lowered."""

    min_sample_size: int
    confidence_level: float
    ready_without_rework_floor: float = PROMOTION_READY_WITHOUT_REWORK_FLOOR
    coverage_regression_ceiling: float = PROMOTION_COVERAGE_REGRESSION_CEILING
    pairing_required: bool = True
    demotion_exposure_window_seconds: int = DEFAULT_DEMOTION_EXPOSURE_WINDOW_SECONDS
    in_flight_run_policy: str = DEFAULT_IN_FLIGHT_RUN_POLICY
    latency_improvement_floor: float | None = None
    holdout_fraction: float | None = None
    multiplicity_correction: str = "bonferroni"
    evaluation_horizon: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "minSampleSize": self.min_sample_size,
            "confidenceLevel": self.confidence_level,
            "readyWithoutReworkFloor": self.ready_without_rework_floor,
            "coverageRegressionCeiling": self.coverage_regression_ceiling,
            "pairingRequired": self.pairing_required,
            "demotionExposureWindowSeconds": self.demotion_exposure_window_seconds,
            "inFlightRunPolicy": self.in_flight_run_policy,
            "latencyImprovementFloor": self.latency_improvement_floor,
            "holdoutFraction": self.holdout_fraction,
            "multiplicityCorrection": self.multiplicity_correction,
            "evaluationHorizon": self.evaluation_horizon,
        }


@dataclass(frozen=True)
class DemotionExposurePolicy:
    """Demotion exposure window and in-flight run handling."""

    exposure_window_seconds: int
    in_flight_run_policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "exposureWindowSeconds": self.exposure_window_seconds,
            "inFlightRunPolicy": self.in_flight_run_policy,
        }


@dataclass(frozen=True)
class FragmentExpansionRecord:
    """One pinned fragment digest recorded during deterministic expansion."""

    use: str
    digest: str


@dataclass(frozen=True)
class PreparedWorkflow:
    """A rendered, kernel-compiled template ready for scheduler submission."""

    name: str
    graph: Mapping[str, Any]
    compiled: Mapping[str, Any]
    approval: Mapping[str, Any]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _template_digest(document: Mapping[str, Any]) -> str:
    bound = {
        "libraryVersion": document.get("libraryVersion"),
        "name": document.get("name"),
        "parameters": document.get("parameters"),
        "graph": document.get("graph"),
    }
    return hashlib.sha256(_canonical_bytes(bound)).hexdigest()


def parse_use_pin(pin: str) -> tuple[str, int]:
    match = _USE_PIN_RE.fullmatch(pin.strip())
    if not match:
        raise WorkflowLibraryError(
            "use pin must match <name>@<version> with a lowercase name"
        )
    return match.group(1), int(match.group(2))


def _fragment_path(root: Path, name: str, version: int) -> Path:
    safe_name = _validate_name(name)
    fragments_root = root / "fragments"
    if fragments_root.exists() and fragments_root.is_symlink():
        raise WorkflowLibraryError("workflow fragment root must not be a symlink")
    return fragments_root / f"{safe_name}@{version}.json"


def _fragment_digest(document: Mapping[str, Any]) -> str:
    bound = {
        "libraryVersion": document.get("libraryVersion"),
        "name": document.get("name"),
        "version": document.get("version"),
        "parameters": document.get("parameters"),
        "inputs": document.get("inputs"),
        "outputs": document.get("outputs"),
        "requiredCapability": document.get("requiredCapability"),
        "graph": document.get("graph"),
    }
    return hashlib.sha256(_canonical_bytes(bound)).hexdigest()


def load_fragment(
    name: str,
    version: int,
    *,
    root: str | Path = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    """Load one versioned workflow fragment from the git-reviewable library."""
    path = _fragment_path(Path(root), name, version)
    if not path.is_file() or path.is_symlink():
        raise WorkflowLibraryError(f"fragment not found in workflow library: {name}@{version}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowLibraryError(
            f"cannot load fragment {name}@{version}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise WorkflowLibraryError("fragment document must be an object")
    if document.get("libraryVersion") != LIBRARY_VERSION:
        raise WorkflowLibraryError("unsupported workflow fragment version")
    if document.get("kind") != FRAGMENT_KIND:
        raise WorkflowLibraryError("fragment document kind must be WorkflowFragment")
    if document.get("name") != name or int(document.get("version") or 0) != version:
        raise WorkflowLibraryError("fragment identity does not match its filename")
    graph = document.get("graph") or {}
    _assert_redacted(graph)
    if document.get("parameters"):
        _normalize_parameters(graph, document.get("parameters") or {})
    return document


def save_fragment(
    subgraph: Mapping[str, Any],
    *,
    name: str,
    version: int,
    root: str | Path = DEFAULT_LIBRARY_ROOT,
    parameters: Mapping[str, Mapping[str, Any]] | None = None,
    inputs: Mapping[str, Mapping[str, Any]] | None = None,
    outputs: Mapping[str, Mapping[str, Any]] | None = None,
    required_capability: bool = False,
    replace: bool = False,
) -> Path:
    """Save a versioned subgraph fragment for typed composition."""
    _validate_name(name)
    if version <= 0:
        raise WorkflowLibraryError("fragment version must be a positive integer")
    if not isinstance(subgraph, Mapping):
        raise WorkflowLibraryError("fragment graph must be an object")
    detached = json.loads(json.dumps(subgraph))
    _assert_redacted(detached)
    normalized_parameters = (
        _normalize_parameters(detached, parameters) if parameters else {}
    )
    path = _fragment_path(Path(root), name, version)
    if path.exists() and not replace:
        raise WorkflowLibraryError(f"fragment already exists: {name}@{version}")
    document = {
        "libraryVersion": LIBRARY_VERSION,
        "kind": FRAGMENT_KIND,
        "name": name,
        "version": version,
        "parameters": normalized_parameters,
        "inputs": dict(inputs or {}),
        "outputs": dict(outputs or {}),
        "requiredCapability": bool(required_capability),
        "graph": detached,
    }
    _write_json_atomic(path, document)
    return path


def _subgraph_section(graph: Mapping[str, Any]) -> dict[str, Any]:
    if "spec" in graph:
        spec = graph["spec"]
        if not isinstance(spec, Mapping):
            raise WorkflowLibraryError("workflow spec must be an object")
        return dict(spec)
    return dict(graph)


def _prefix_node_id(prefix: str, node_id: str) -> str:
    safe_prefix = _validate_name(prefix)
    return f"{safe_prefix}-{node_id}"


def _prefix_node(node: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    detached = json.loads(json.dumps(node))
    detached["id"] = _prefix_node_id(prefix, str(detached["id"]))
    return detached


def _prefix_edge(edge: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    detached = json.loads(json.dumps(edge))
    detached["from"] = _prefix_node_id(prefix, str(detached["from"]))
    detached["to"] = _prefix_node_id(prefix, str(detached["to"]))
    return detached


def _resolve_fragment_inputs(
    fragment: Mapping[str, Any],
    rendered_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    specs = fragment.get("parameters") or {}
    if not specs:
        return dict(rendered_inputs)
    return _resolve_values(specs, rendered_inputs)


def _check_expansion_limits(
    *,
    node_count: int,
    edge_count: int,
    fragment_pin: str,
) -> None:
    if node_count > MAX_EXPANDED_NODES:
        raise WorkflowLibraryError(
            f"fragment {fragment_pin}: expanded node ceiling exceeded "
            f"({node_count}>{MAX_EXPANDED_NODES})"
        )
    if edge_count > MAX_EXPANDED_EDGES:
        raise WorkflowLibraryError(
            f"fragment {fragment_pin}: expanded edge ceiling exceeded "
            f"({edge_count}>{MAX_EXPANDED_EDGES})"
        )


def expand_workflow_fragments(
    graph: Mapping[str, Any],
    *,
    root: str | Path = DEFAULT_LIBRARY_ROOT,
    resolved_values: Mapping[str, Any],
    depth: int = 0,
    stack: tuple[tuple[str, int], ...] = (),
    digest_mode: bool = False,
) -> tuple[dict[str, Any], tuple[FragmentExpansionRecord, ...]]:
    """Expand pinned `use:` fragments into one WorkflowGraph before kernel compile."""
    if depth > MAX_FRAGMENT_EXPANSION_DEPTH:
        raise WorkflowLibraryError("fragment expansion depth ceiling exceeded")
    detached = json.loads(json.dumps(graph))
    section = _subgraph_section(detached)
    uses = section.get("uses") or []
    if not uses:
        return detached, ()

    if not isinstance(uses, list):
        raise WorkflowLibraryError("spec.uses must be an array")

    expanded_nodes = list(section.get("nodes") or [])
    expanded_edges = list(section.get("edges") or [])
    records: list[FragmentExpansionRecord] = []

    for index, raw_entry in enumerate(uses):
        if not isinstance(raw_entry, Mapping):
            raise WorkflowLibraryError(f"spec.uses[{index}] must be an object")
        use_pin = str(raw_entry.get("use") or "")
        name, version = parse_use_pin(use_pin)
        identity = (name, version)
        if identity in stack:
            raise WorkflowLibraryError(
                f"fragment {use_pin}: expansion cycle detected"
            )

        fragment = load_fragment(name, version, root=root)
        required_capability = bool(fragment.get("requiredCapability"))
        location = f"spec.uses[{index}] ({use_pin})"
        try:
            validate_fragment_use_entry(
                raw_entry,
                location=location,
                required_capability=required_capability,
            )
        except WorkflowGraphValidationError as exc:
            raise WorkflowLibraryError(str(exc)) from exc

        rendered_inputs = (
            dict(raw_entry.get("inputs") or {})
            if digest_mode
            else _render(raw_entry.get("inputs") or {}, resolved_values)
        )
        if digest_mode:
            fragment_values = {
                key: str(value)
                for key, value in rendered_inputs.items()
            }
        else:
            fragment_values = _resolve_fragment_inputs(fragment, rendered_inputs)
        fragment_graph = (
            fragment.get("graph") or {}
            if digest_mode
            else _render(fragment.get("graph") or {}, fragment_values)
        )
        nested_graph = expand_workflow_fragments(
            fragment_graph,
            root=root,
            resolved_values={**dict(resolved_values), **fragment_values},
            depth=depth + 1,
            stack=stack + (identity,),
            digest_mode=digest_mode,
        )
        nested_body, nested_records = nested_graph
        nested_section = _subgraph_section(nested_body)
        nested_uses = nested_section.get("uses") or []
        if nested_uses:
            raise WorkflowLibraryError(
                f"fragment {use_pin}: nested uses must be expanded before merge"
            )

        prefix = str(raw_entry.get("prefix") or name)
        _validate_name(prefix)
        prefixed_nodes = [
            _prefix_node(node, prefix)
            for node in nested_section.get("nodes") or []
        ]
        prefixed_edges = [
            _prefix_edge(edge, prefix)
            for edge in nested_section.get("edges") or []
        ]

        candidate_nodes = len(expanded_nodes) + len(prefixed_nodes)
        candidate_edges = len(expanded_edges) + len(prefixed_edges)
        _check_expansion_limits(
            node_count=candidate_nodes,
            edge_count=candidate_edges,
            fragment_pin=use_pin,
        )

        expanded_nodes.extend(prefixed_nodes)
        expanded_edges.extend(prefixed_edges)
        records.append(
            FragmentExpansionRecord(use=use_pin, digest=_fragment_digest(fragment))
        )
        records.extend(nested_records)

    section["nodes"] = expanded_nodes
    section["edges"] = expanded_edges
    section.pop("uses", None)
    if "spec" in detached:
        detached["spec"] = section
    else:
        detached.update(section)
        for key in ("nodes", "edges"):
            if key in detached and key not in section:
                detached.pop(key, None)
        detached.pop("uses", None)

    if digest_mode:
        metadata = detached.setdefault("metadata", {})
        if isinstance(metadata, Mapping):
            metadata["fragmentDigests"] = [
                {"use": record.use, "digest": record.digest} for record in records
            ]
    return detached, tuple(records)


def _template_has_uses(document: Mapping[str, Any]) -> bool:
    graph = document.get("graph") or {}
    if not isinstance(graph, Mapping):
        return False
    section = _subgraph_section(graph)
    return bool(section.get("uses"))


def _approval_digest(
    document: Mapping[str, Any],
    *,
    root: str | Path,
    resolved_values: Mapping[str, Any],
) -> str:
    if _template_has_uses(document):
        return _expanded_template_digest(
            document,
            root=root,
            resolved_values=resolved_values,
        )
    return _template_digest(document)


def _expanded_template_digest(
    document: Mapping[str, Any],
    *,
    root: str | Path,
    resolved_values: Mapping[str, Any],
) -> str:
    graph = document.get("graph") or {}
    expanded, records = expand_workflow_fragments(
        graph,
        root=root,
        resolved_values=resolved_values,
        digest_mode=True,
    )
    bound = {
        "libraryVersion": document.get("libraryVersion"),
        "name": document.get("name"),
        "parameters": document.get("parameters"),
        "graph": expanded,
        "fragmentDigests": [
            {"use": record.use, "digest": record.digest} for record in records
        ],
    }
    return hashlib.sha256(_canonical_bytes(bound)).hexdigest()


def _validate_name(name: str) -> str:
    if not _NAME_RE.fullmatch(name):
        raise WorkflowLibraryError(
            "template name must match ^[a-z][a-z0-9-]{0,62}$"
        )
    return name


def _template_path(root: Path, name: str) -> Path:
    safe_name = _validate_name(name)
    if root.exists() and root.is_symlink():
        raise WorkflowLibraryError("workflow library root must not be a symlink")
    return root / f"{safe_name}.json"


def _write_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or (path.exists() and path.is_symlink()):
        raise WorkflowLibraryError("workflow template path must not be a symlink")
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _placeholders(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, str):
        names.update(_PLACEHOLDER_RE.findall(value))
    elif isinstance(value, Mapping):
        for child in value.values():
            names.update(_placeholders(child))
    elif isinstance(value, list):
        for child in value:
            names.update(_placeholders(child))
    return names


def _contains_placeholder(value: str) -> bool:
    return _PLACEHOLDER_RE.search(value) is not None


def _assert_redacted(value: Any, *, key: str = "", location: str = "graph") -> None:
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            _assert_redacted(
                child,
                key=str(child_key),
                location=f"{location}.{child_key}",
            )
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_redacted(child, key=key, location=f"{location}.{index}")
        return
    if not isinstance(value, str):
        return
    if _SECRET_VALUE_RE.search(value):
        raise WorkflowLibraryError(f"{location}: unredacted secret-like value")
    if _LOCAL_PATH_RE.search(value):
        raise WorkflowLibraryError(
            f"{location}: run-specific local path must be parameterized"
        )
    if _SENSITIVE_KEY_RE.search(key) and value and not _contains_placeholder(value):
        raise WorkflowLibraryError(
            f"{location}: sensitive value must be replaced by a parameter"
        )


def _normalize_parameters(
    graph: Mapping[str, Any],
    parameters: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    referenced = _placeholders(graph)
    supplied = dict(parameters or {})
    if not parameters:
        supplied = {
            name: {"type": "string", "required": True}
            for name in sorted(referenced)
        }
    unknown = set(supplied) - referenced
    missing = referenced - set(supplied)
    if unknown:
        raise WorkflowLibraryError(
            "unused parameter declaration(s): " + ", ".join(sorted(unknown))
        )
    if missing:
        raise WorkflowLibraryError(
            "missing parameter declaration(s): " + ", ".join(sorted(missing))
        )

    normalized: dict[str, dict[str, Any]] = {}
    for name in sorted(supplied):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", name):
            raise WorkflowLibraryError(f"invalid parameter name: {name}")
        raw = supplied[name]
        if not isinstance(raw, Mapping):
            raise WorkflowLibraryError(f"parameter {name} must be an object")
        allowed = {"type", "required", "default", "minimum", "maximum", "pattern"}
        extras = set(raw) - allowed
        if extras:
            raise WorkflowLibraryError(
                f"parameter {name} has unknown fields: {', '.join(sorted(extras))}"
            )
        kind = str(raw.get("type") or "string")
        if kind not in _PARAM_TYPES:
            raise WorkflowLibraryError(f"parameter {name} has unsupported type {kind}")
        item: dict[str, Any] = {
            "type": kind,
            "required": bool(raw.get("required", "default" not in raw)),
        }
        for field in ("default", "minimum", "maximum", "pattern"):
            if field in raw:
                item[field] = raw[field]
        _validate_parameter_value(name, item, item.get("default"), allow_missing=True)
        normalized[name] = item
    return normalized


def _validate_parameter_value(
    name: str,
    spec: Mapping[str, Any],
    value: Any,
    *,
    allow_missing: bool = False,
) -> Any:
    if value is None and allow_missing:
        return value
    kind = spec["type"]
    if kind == "string":
        if not isinstance(value, str):
            raise WorkflowLibraryError(f"parameter {name} must be a string")
        pattern = spec.get("pattern")
        if pattern is not None and re.fullmatch(str(pattern), value) is None:
            raise WorkflowLibraryError(f"parameter {name} does not match its pattern")
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise WorkflowLibraryError(f"parameter {name} must be an integer")
        if "minimum" in spec and value < int(spec["minimum"]):
            raise WorkflowLibraryError(f"parameter {name} is below its minimum")
        if "maximum" in spec and value > int(spec["maximum"]):
            raise WorkflowLibraryError(f"parameter {name} is above its maximum")
    elif kind == "boolean" and not isinstance(value, bool):
        raise WorkflowLibraryError(f"parameter {name} must be a boolean")
    return value


def save_template(
    graph: Mapping[str, Any],
    *,
    name: str,
    root: str | Path = DEFAULT_LIBRARY_ROOT,
    parameters: Mapping[str, Mapping[str, Any]] | None = None,
    replace: bool = False,
) -> Path:
    """Save a redacted parameterized graph with approval reset."""
    _validate_name(name)
    if not isinstance(graph, Mapping):
        raise WorkflowLibraryError("graph must be an object")
    detached = json.loads(json.dumps(graph))
    if detached.get("kind") != "WorkflowGraph":
        raise WorkflowLibraryError("template graph must be a WorkflowGraph")
    _assert_redacted(detached)
    normalized_parameters = _normalize_parameters(detached, parameters)
    path = _template_path(Path(root), name)
    if path.exists() and not replace:
        raise WorkflowLibraryError(f"template already exists: {name}")
    document = {
        "libraryVersion": LIBRARY_VERSION,
        "name": name,
        "parameters": normalized_parameters,
        "graph": detached,
        "approval": None,
    }
    _write_json_atomic(path, document)
    return path


def load_template(
    name: str,
    *,
    root: str | Path = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    """Load one template exclusively from the git-reviewable library."""
    path = _template_path(Path(root), name)
    if not path.is_file() or path.is_symlink():
        raise WorkflowLibraryError(f"template not found in workflow library: {name}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowLibraryError(f"cannot load template {name}: {exc}") from exc
    if not isinstance(document, dict):
        raise WorkflowLibraryError("template document must be an object")
    if document.get("libraryVersion") != LIBRARY_VERSION:
        raise WorkflowLibraryError("unsupported workflow template version")
    if document.get("name") != name:
        raise WorkflowLibraryError("template name does not match its filename")
    _assert_redacted(document.get("graph"))
    _normalize_parameters(document.get("graph") or {}, document.get("parameters") or {})
    return document


def _approval_resolution(specs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Resolve parameters for approval-time expanded digest binding."""
    resolved: dict[str, Any] = {}
    for name, spec in specs.items():
        if "default" in spec:
            value = spec["default"]
        elif spec["type"] == "string":
            pattern = spec.get("pattern")
            if pattern == "^[a-z][a-z0-9-]+$":
                value = "fixture-workspace"
            else:
                value = "fixture"
        elif spec["type"] == "integer":
            value = int(spec.get("minimum", 1))
        elif spec["type"] == "boolean":
            value = False
        else:
            value = ""
        resolved[name] = _validate_parameter_value(name, spec, value)
    return resolved


def approve_template(
    name: str,
    *,
    actor: str,
    root: str | Path = DEFAULT_LIBRARY_ROOT,
    approved_at: str | None = None,
) -> Path:
    """Bind a human approval record to the exact saved template digest."""
    if not actor.strip():
        raise WorkflowLibraryError("approval actor is required")
    document = load_template(name, root=root)
    resolved = _approval_resolution(document["parameters"])
    document["approval"] = {
        "approved": True,
        "approvedBy": actor.strip(),
        "approvedAt": approved_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "templateHash": _approval_digest(
            document,
            root=root,
            resolved_values=resolved,
        ),
    }
    path = _template_path(Path(root), name)
    _write_json_atomic(path, document)
    return path


def _assert_approved(
    document: Mapping[str, Any],
    *,
    root: str | Path = DEFAULT_LIBRARY_ROOT,
    resolved_values: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    approval = document.get("approval")
    if not isinstance(approval, Mapping) or approval.get("approved") is not True:
        raise WorkflowLibraryError("template reuse requires human approval")
    specs = document.get("parameters") or {}
    approval_resolved = _approval_resolution(specs)
    expected = _approval_digest(
        document,
        root=root,
        resolved_values=approval_resolved,
    )
    if approval.get("templateHash") != expected:
        raise WorkflowLibraryError("template changed after approval; re-approval required")
    if not approval.get("approvedBy") or not approval.get("approvedAt"):
        raise WorkflowLibraryError("template approval record is incomplete")
    return approval


def _coerce_cli_value(raw: str, spec: Mapping[str, Any]) -> Any:
    kind = spec["type"]
    if kind == "integer":
        try:
            return int(raw)
        except ValueError as exc:
            raise WorkflowLibraryError("integer parameter has a non-integer value") from exc
    if kind == "boolean":
        if raw.lower() in {"true", "1", "yes"}:
            return True
        if raw.lower() in {"false", "0", "no"}:
            return False
        raise WorkflowLibraryError("boolean parameter must be true or false")
    return raw


def _resolve_values(
    specs: Mapping[str, Mapping[str, Any]],
    values: Mapping[str, Any],
) -> dict[str, Any]:
    unknown = set(values) - set(specs)
    if unknown:
        raise WorkflowLibraryError(
            "unknown parameter(s): " + ", ".join(sorted(unknown))
        )
    resolved: dict[str, Any] = {}
    for name, spec in specs.items():
        if name in values:
            value = values[name]
        elif "default" in spec:
            value = spec["default"]
        elif spec.get("required", True):
            raise WorkflowLibraryError(f"required parameter is missing: {name}")
        else:
            value = ""
        resolved[name] = _validate_parameter_value(name, spec, value)
    return resolved


def _render(value: Any, parameters: Mapping[str, Any]) -> Any:
    if isinstance(value, Mapping):
        return {key: _render(child, parameters) for key, child in value.items()}
    if isinstance(value, list):
        return [_render(child, parameters) for child in value]
    if not isinstance(value, str):
        return value
    full = _PLACEHOLDER_RE.fullmatch(value)
    if full:
        return deepcopy(parameters[full.group(1)])

    def replace(match: re.Match[str]) -> str:
        replacement = parameters[match.group(1)]
        if not isinstance(replacement, str):
            raise WorkflowLibraryError(
                f"embedded parameter {match.group(1)} must be a string"
            )
        return replacement

    return _PLACEHOLDER_RE.sub(replace, value)


def prepare_run(
    name: str,
    *,
    values: Mapping[str, Any],
    root: str | Path = DEFAULT_LIBRARY_ROOT,
    kernel_options: Mapping[str, Any] | None = None,
) -> PreparedWorkflow:
    """Render an approved template and compile it through the safety kernel."""
    document = load_template(name, root=root)
    specs = document["parameters"]
    resolved = _resolve_values(specs, values)
    approval = _assert_approved(
        document,
        root=root,
    )
    graph = _render(document["graph"], resolved)
    expanded, _records = expand_workflow_fragments(
        graph,
        root=root,
        resolved_values=resolved,
    )
    compiled = compile_workflow_graph(expanded, **dict(kernel_options or {}))
    return PreparedWorkflow(
        name=name,
        graph=compiled["graph"],
        compiled=compiled,
        approval=dict(approval),
    )


def promotion_policy_hard_floors() -> dict[str, int | float]:
    """Non-configurable lower bounds; configuration may raise but never lower."""
    return {
        "minSampleSize": PROMOTION_SAMPLE_FLOOR,
        "confidenceLevel": PROMOTION_CONFIDENCE_FLOOR,
        "readyWithoutReworkFloor": PROMOTION_READY_WITHOUT_REWORK_FLOOR,
        "coverageRegressionCeiling": PROMOTION_COVERAGE_REGRESSION_CEILING,
        "smallNRefusalThreshold": PROMOTION_SMALL_N_REFUSAL_THRESHOLD,
    }


def validate_promotion_policy_config(policy: PromotionPolicyDocument) -> list[str]:
    """Refuse policy documents that regress below hard floors."""
    reasons: list[str] = []
    floors = promotion_policy_hard_floors()
    if policy.min_sample_size < int(floors["minSampleSize"]):
        reasons.append(
            "min sample size "
            f"{policy.min_sample_size} below hard floor {floors['minSampleSize']}"
        )
    if policy.confidence_level < float(floors["confidenceLevel"]):
        reasons.append(
            "confidence level "
            f"{policy.confidence_level} below hard floor {floors['confidenceLevel']}"
        )
    if policy.ready_without_rework_floor < float(floors["readyWithoutReworkFloor"]):
        reasons.append(
            "ready-without-rework floor "
            f"{policy.ready_without_rework_floor} below hard floor "
            f"{floors['readyWithoutReworkFloor']}"
        )
    if policy.coverage_regression_ceiling > float(floors["coverageRegressionCeiling"]):
        reasons.append(
            "coverage regression ceiling "
            f"{policy.coverage_regression_ceiling} above hard floor "
            f"{floors['coverageRegressionCeiling']}"
        )
    if policy.in_flight_run_policy not in ALLOWED_IN_FLIGHT_RUN_POLICIES:
        reasons.append(
            "in-flight run policy must be one of: "
            + ", ".join(sorted(ALLOWED_IN_FLIGHT_RUN_POLICIES))
        )
    if policy.demotion_exposure_window_seconds < 0:
        reasons.append("demotion exposure window must be non-negative")
    return reasons


def promotion_policy_digest(policy: PromotionPolicyDocument) -> str:
    """Stable digest for an approval-gated promotion policy document."""
    return hashlib.sha256(_canonical_bytes(policy.to_dict())).hexdigest()


def default_promotion_policy() -> PromotionPolicyDocument:
    """Return the default approval-gated promotion policy at hard floors."""
    return PromotionPolicyDocument(
        min_sample_size=PROMOTION_SAMPLE_FLOOR,
        confidence_level=PROMOTION_CONFIDENCE_FLOOR,
    )


def auto_promote_allowed(sample_count: int) -> bool:
    """Small-N samples never auto-promote below the hard refusal threshold."""
    return sample_count >= PROMOTION_SMALL_N_REFUSAL_THRESHOLD


def demotion_exposure_policy(
    policy: PromotionPolicyDocument,
) -> DemotionExposurePolicy:
    """Surface demotion exposure window and in-flight handling from policy."""
    return DemotionExposurePolicy(
        exposure_window_seconds=policy.demotion_exposure_window_seconds,
        in_flight_run_policy=policy.in_flight_run_policy,
    )


def _promotion_evidence_digest(evidence: PlanPolicyPromotionEvidence) -> str:
    payload = {
        "samples": [
            {
                "runId": sample.run_id,
                "stratum": sample.stratum,
                "templateDigest": sample.template_digest,
                "predictionError": sample.prediction_error,
                "requiredCapabilityRegression": sample.required_capability_regression,
                "readyWithoutRework": sample.ready_without_rework,
                "command": sample.command,
                "pairedCanonicalRunId": sample.paired_canonical_run_id,
                "confidence": sample.confidence,
                "coverageScore": sample.coverage_score,
                "perfectScore": sample.perfect_score,
            }
            for sample in evidence.samples
        ],
        "authorizer": evidence.authorizer,
        "confirmation": {
            "command": evidence.confirmation.command,
            "digest": evidence.confirmation.digest,
            "confirmedBy": evidence.confirmation.confirmed_by,
            "confirmedAt": evidence.confirmation.confirmed_at,
        },
        "receiptsDigest": evidence.receipts_digest,
        "calibrationDigest": evidence.calibration_digest,
    }
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def gate_plan_policy_promotion(
    evidence: PlanPolicyPromotionEvidence,
    *,
    target_policy: str,
    template_digest: str,
    policy: PromotionPolicyDocument | None = None,
) -> PlanPolicyPromotionVerdict:
    """Fail-closed gate for orchestration.planPolicy proposed then canonical."""
    reasons: list[str] = []
    active_policy = policy or PromotionPolicyDocument(
        min_sample_size=PROMOTION_SAMPLE_FLOOR,
        confidence_level=PROMOTION_CONFIDENCE_FLOOR,
    )
    policy_digest = promotion_policy_digest(active_policy)
    reasons.extend(validate_promotion_policy_config(active_policy))
    effective_sample_floor = max(
        PROMOTION_SAMPLE_FLOOR,
        active_policy.min_sample_size,
    )
    effective_confidence_floor = max(
        PROMOTION_CONFIDENCE_FLOOR,
        active_policy.confidence_level,
    )
    if target_policy not in {PLAN_POLICY_PROPOSED, PLAN_POLICY_CANONICAL}:
        reasons.append(f"unsupported target policy: {target_policy}")

    sample_count = len(evidence.samples)
    if sample_count < effective_sample_floor:
        reasons.append(
            f"sample floor not met: need {effective_sample_floor}, have {sample_count}"
        )

    strata = {sample.stratum for sample in evidence.samples}
    missing_strata = sorted(REQUIRED_INPUT_STRATA - strata)
    if missing_strata:
        reasons.append(
            "missing input strata: " + ", ".join(missing_strata)
        )

    for sample in evidence.samples:
        if sample.prediction_error > MAX_PREDICTION_ERROR:
            reasons.append(
                f"prediction error {sample.prediction_error} exceeds "
                f"bound {MAX_PREDICTION_ERROR} for run {sample.run_id}"
            )
        if sample.required_capability_regression:
            reasons.append(
                f"required-capability regression on run {sample.run_id}"
            )
        if not sample.ready_without_rework:
            reasons.append(
                f"run {sample.run_id} did not reach ready without human rework"
            )
        if sample.template_digest != template_digest:
            reasons.append(
                f"sample digest mismatch on run {sample.run_id}"
            )
        if sample.confidence < effective_confidence_floor:
            reasons.append(
                f"confidence {sample.confidence} below floor "
                f"{effective_confidence_floor} for run {sample.run_id}"
            )
        if active_policy.pairing_required and not sample.paired_canonical_run_id.strip():
            reasons.append(
                f"run {sample.run_id} missing mandatory canonical pairing"
            )
        if (
            sample_count < PROMOTION_SMALL_N_REFUSAL_THRESHOLD
            and sample.perfect_score
        ):
            reasons.append(
                f"small-N perfect score on run {sample.run_id} refused auto-promotion"
            )
        if sample.coverage_score < (
            1.0 - active_policy.coverage_regression_ceiling
        ):
            reasons.append(
                f"coverage regression on run {sample.run_id}: "
                f"{sample.coverage_score} below ceiling "
                f"{1.0 - active_policy.coverage_regression_ceiling}"
            )

    authorizer = evidence.authorizer.strip()
    if not authorizer:
        reasons.append("named authorizer is required")
    elif authorizer not in ALLOWED_PLAN_POLICY_AUTHORIZERS:
        reasons.append(f"unrecognized promotion authorizer: {authorizer}")

    confirmation = evidence.confirmation
    command = confirmation.command.strip().removeprefix("/")
    if command not in DIGEST_CONFIRMATION_COMMANDS:
        reasons.append(
            "digest confirmation must bind an existing command: "
            + ", ".join(sorted(DIGEST_CONFIRMATION_COMMANDS))
        )
    if not confirmation.digest.strip():
        reasons.append("digest confirmation is required")
    elif confirmation.digest != template_digest:
        reasons.append("digest confirmation does not match template digest")
    if not confirmation.confirmed_by.strip():
        reasons.append("digest confirmation actor is required")

    if target_policy == PLAN_POLICY_CANONICAL:
        proposed_samples = [
            sample
            for sample in evidence.samples
            if sample.stratum == "non-dogfood-deliver"
        ]
        if not proposed_samples:
            reasons.append(
                "canonical promotion requires non-dogfood deliver evidence"
            )

    verdict = "pass" if not reasons else "fail"
    return PlanPolicyPromotionVerdict(
        verdict=verdict,
        target_policy=target_policy,
        reasons=tuple(reasons),
        policy_digest=policy_digest,
    )


def _template_graph(document: Mapping[str, Any]) -> Mapping[str, Any]:
    graph = document.get("graph")
    if not isinstance(graph, Mapping):
        raise WorkflowLibraryError("template graph is missing or invalid")
    return graph


def _pinned_reference_capabilities(
    document: Mapping[str, Any],
) -> frozenset[str] | None:
    if not document.get("canonicalAdoptedDigest"):
        return None
    return required_capabilities_from_graph(_template_graph(document))


def _template_plan_policy(document: Mapping[str, Any]) -> str:
    promotion = document.get("planPolicyPromotion")
    if isinstance(promotion, Mapping):
        stage = str(promotion.get("stage") or PLAN_POLICY_CANONICAL)
        if stage in {PLAN_POLICY_CANONICAL, PLAN_POLICY_PROPOSED}:
            return stage
    return PLAN_POLICY_CANONICAL


def promote_template_plan_policy(
    name: str,
    evidence: PlanPolicyPromotionEvidence,
    *,
    target_policy: str,
    root: str | Path = DEFAULT_LIBRARY_ROOT,
    promoted_at: str | None = None,
    policy: PromotionPolicyDocument | None = None,
) -> Path:
    """Promote a saved template through proposed then canonical plan policy."""
    if target_policy not in {PLAN_POLICY_PROPOSED, PLAN_POLICY_CANONICAL}:
        raise WorkflowLibraryError(f"unsupported plan policy target: {target_policy}")
    document = load_template(name, root=root)
    _assert_approved(document)
    template_digest = _template_digest(document)
    active_policy = policy or PromotionPolicyDocument(
        min_sample_size=PROMOTION_SAMPLE_FLOOR,
        confidence_level=PROMOTION_CONFIDENCE_FLOOR,
    )
    gate = gate_plan_policy_promotion(
        evidence,
        target_policy=target_policy,
        template_digest=template_digest,
        policy=active_policy,
    )
    if not gate.passed:
        raise WorkflowLibraryError(
            "plan policy promotion gate failed: " + "; ".join(gate.reasons)
        )

    pinned_ids = document.get("planPolicyPromotion", {}).get("pinnedRequiredCapabilityIds")
    if isinstance(pinned_ids, list) and pinned_ids:
        assert_promotion_anti_ratchet(
            pinned_reference_graph={
                "spec": {"nodes": []},
                "metadata": {"requiredCapabilityIds": pinned_ids},
            },
            candidate_graph=_template_graph(document),
            root=root,
        )

    current = _template_plan_policy(document)
    if target_policy == PLAN_POLICY_PROPOSED and current == PLAN_POLICY_PROPOSED:
        raise WorkflowLibraryError("template already promoted to proposed")
    if target_policy == PLAN_POLICY_CANONICAL and current != PLAN_POLICY_PROPOSED:
        raise WorkflowLibraryError(
            "canonical promotion requires an active proposed stage"
        )

    document["planPolicyPromotion"] = {
        "stage": target_policy,
        "promotedAt": promoted_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "authorizer": evidence.authorizer.strip(),
        "evidenceDigest": _promotion_evidence_digest(evidence),
        "policyDigest": gate.policy_digest,
        "templateDigest": template_digest,
        "demotionExposure": demotion_exposure_policy(active_policy).to_dict(),
        "confirmation": {
            "command": evidence.confirmation.command.strip().removeprefix("/"),
            "digest": evidence.confirmation.digest,
            "confirmedBy": evidence.confirmation.confirmed_by.strip(),
            "confirmedAt": evidence.confirmation.confirmed_at,
        },
        "receiptsDigest": evidence.receipts_digest,
        "calibrationDigest": evidence.calibration_digest,
    }
    if target_policy == PLAN_POLICY_CANONICAL:
        document["canonicalAdoptedDigest"] = template_digest
        document["planPolicyPromotion"]["pinnedRequiredCapabilityIds"] = sorted(
            required_capabilities_from_graph(_template_graph(document))
        )
    path = _template_path(Path(root), name)
    _write_json_atomic(path, document)
    return path


def demote_template_plan_policy(
    name: str,
    *,
    reason: str,
    actor: str,
    root: str | Path = DEFAULT_LIBRARY_ROOT,
    demoted_at: str | None = None,
    in_flight_runs: int = 0,
) -> Path:
    """Drop proposed plan policy and revert the template to canonical."""
    if not reason.strip():
        raise WorkflowLibraryError("demotion reason is required")
    if not actor.strip():
        raise WorkflowLibraryError("demotion actor is required")
    document = load_template(name, root=root)
    promotion = document.get("planPolicyPromotion")
    if isinstance(promotion, Mapping):
        exposure = promotion.get("demotionExposure") or {}
        if not isinstance(exposure, Mapping):
            exposure = {}
        window_seconds = int(
            exposure.get(
                "exposureWindowSeconds",
                DEFAULT_DEMOTION_EXPOSURE_WINDOW_SECONDS,
            )
        )
        in_flight_policy = str(
            exposure.get("inFlightRunPolicy", DEFAULT_IN_FLIGHT_RUN_POLICY)
        )
        if in_flight_runs > 0:
            if in_flight_policy == "drain":
                raise WorkflowLibraryError(
                    "demotion blocked: in-flight runs must drain before demotion"
                )
            raise WorkflowLibraryError(
                "demotion blocked: in-flight runs still active"
            )
        promoted_at = str(promotion.get("promotedAt") or "")
        if promoted_at and window_seconds > 0:
            promoted = datetime.fromisoformat(promoted_at.replace("Z", "+00:00"))
            demote_time = datetime.fromisoformat(
                (demoted_at or datetime.now(timezone.utc).isoformat()).replace(
                    "Z", "+00:00"
                )
            )
            elapsed = (demote_time - promoted).total_seconds()
            if elapsed < window_seconds:
                raise WorkflowLibraryError(
                    "demotion blocked: latency window "
                    f"{window_seconds}s not elapsed"
                )
    document["planPolicyPromotion"] = {
        "stage": PLAN_POLICY_CANONICAL,
        "demotedAt": demoted_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "demotedBy": actor.strip(),
        "reason": reason.strip(),
    }
    document.pop("canonicalAdoptedDigest", None)
    path = _template_path(Path(root), name)
    _write_json_atomic(path, document)
    return path


def apply_profile_to_required_capabilities(
    *,
    injected_capability_ids: frozenset[str],
    profile: str,
    root: str | Path = ".",
) -> frozenset[str]:
    """Apply optimization profile after detector injection and enforce absolute floor."""
    try:
        return evaluate_after_profile_and_inject(
            injected_capability_ids=injected_capability_ids,
            profile=profile,
            repo_root=Path(root),
        )
    except AbsoluteFloorError as exc:
        raise WorkflowLibraryError(str(exc)) from exc


def assert_promotion_anti_ratchet(
    *,
    pinned_reference_graph: Mapping[str, Any],
    candidate_graph: Mapping[str, Any],
    root: str | Path = ".",
) -> None:
    """Promotion cannot ratchet below pinned reference capability set (R9)."""
    pinned = required_capabilities_from_graph(pinned_reference_graph)
    candidate = required_capabilities_from_graph(candidate_graph)
    try:
        assert_anti_ratchet_ceiling(
            pinned_reference=pinned,
            candidate=candidate,
            repo_root=Path(root),
        )
    except AbsoluteFloorError as exc:
        raise WorkflowLibraryError(str(exc)) from exc


def assert_control_path_preserves_auth(
    *,
    baseline_graph: Mapping[str, Any],
    adjusted_graph: Mapping[str, Any],
    control_path: str,
) -> None:
    """Profile/budget/cache/demotion/package paths cannot skip auth caps (R10)."""
    baseline = required_capabilities_from_graph(baseline_graph)
    proposed = required_capabilities_from_graph(adjusted_graph)
    try:
        assert_auth_capabilities_nonskippable(
            baseline=baseline,
            proposed=proposed,
            control_path=control_path,
        )
    except ValueError as exc:
        raise WorkflowLibraryError(str(exc)) from exc


def evaluate_saved_template(
    name: str,
    *,
    values: Mapping[str, Any],
    canonical_graph: Mapping[str, Any],
    plan_policy: str,
    cutover_stage: CutoverStage,
    cutover_evidence: DogfoodEvidence | None,
    budget: ProposalBudget,
    root: str | Path = DEFAULT_LIBRARY_ROOT,
    kernel_options: Mapping[str, Any] | None = None,
) -> ProposalDecision:
    """Feed an approved saved graph through the guarded proposal boundary."""
    prepared = prepare_run(
        name,
        values=values,
        root=root,
        kernel_options=kernel_options,
    )
    assert_control_path_preserves_auth(
        baseline_graph=canonical_graph,
        adjusted_graph=prepared.graph,
        control_path="optimizer-proposal",
    )
    return evaluate_dynamic_proposal(
        prepared.graph,
        canonical_graph=canonical_graph,
        plan_policy=plan_policy,
        cutover_stage=cutover_stage,
        cutover_evidence=cutover_evidence,
        budget=budget,
        kernel_options=kernel_options,
    )


def _load_json_object(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowLibraryError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowLibraryError(f"JSON value must be an object: {path}")
    return value


def _parse_set_args(
    items: Sequence[str],
    specs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise WorkflowLibraryError("--set values must use NAME=VALUE")
        name, raw = item.split("=", 1)
        if name in values:
            raise WorkflowLibraryError(f"duplicate --set parameter: {name}")
        if name not in specs:
            raise WorkflowLibraryError(f"unknown parameter: {name}")
        values[name] = _coerce_cli_value(raw, specs[name])
    return values


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_LIBRARY_ROOT))
    subparsers = parser.add_subparsers(dest="command", required=True)

    save = subparsers.add_parser("save", help="Save a parameterized graph")
    save.add_argument("--name", required=True)
    save.add_argument("--graph", required=True)
    save.add_argument("--parameters")
    save.add_argument("--replace", action="store_true")

    approve = subparsers.add_parser("approve", help="Approve an exact saved template")
    approve.add_argument("--name", required=True)
    approve.add_argument("--actor", required=True)

    run = subparsers.add_parser("run", help="Prepare an approved template for execution")
    run.add_argument("--name", required=True)
    run.add_argument("--set", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "save":
            graph = _load_json_object(args.graph)
            parameters = (
                _load_json_object(args.parameters) if args.parameters else None
            )
            path = save_template(
                graph,
                name=args.name,
                root=args.root,
                parameters=parameters,
                replace=args.replace,
            )
            payload = {"verdict": "pass", "action": "saved", "path": str(path)}
        elif args.command == "approve":
            path = approve_template(args.name, actor=args.actor, root=args.root)
            payload = {"verdict": "pass", "action": "approved", "path": str(path)}
        else:
            document = load_template(args.name, root=args.root)
            values = _parse_set_args(args.set, document["parameters"])
            prepared = prepare_run(args.name, values=values, root=args.root)
            payload = {
                "verdict": "pass",
                "action": "prepared",
                "name": prepared.name,
                "graphHash": prepared.compiled["graphHash"],
                "graph": prepared.graph,
                "approval": prepared.approval,
            }
    except WorkflowLibraryError as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}), file=sys.stderr)
        return 20
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
