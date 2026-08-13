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

from graph.cutover import CutoverStage, DogfoodEvidence  # noqa: E402
from graph.dynamic_proposal import (
    ProposalBudget,
    ProposalDecision,
    evaluate_dynamic_proposal,
)  # noqa: E402
from graph.kernel_compiler import compile_workflow_graph  # noqa: E402

LIBRARY_VERSION = 1
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


class WorkflowLibraryError(ValueError):
    """Raised when a template is unsafe, invalid, or not approved."""


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
    document["approval"] = {
        "approved": True,
        "approvedBy": actor.strip(),
        "approvedAt": approved_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "templateHash": _template_digest(document),
    }
    path = _template_path(Path(root), name)
    _write_json_atomic(path, document)
    return path


def _assert_approved(document: Mapping[str, Any]) -> Mapping[str, Any]:
    approval = document.get("approval")
    if not isinstance(approval, Mapping) or approval.get("approved") is not True:
        raise WorkflowLibraryError("template reuse requires human approval")
    if approval.get("templateHash") != _template_digest(document):
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
    approval = _assert_approved(document)
    specs = document["parameters"]
    resolved = _resolve_values(specs, values)
    graph = _render(document["graph"], resolved)
    compiled = compile_workflow_graph(graph, **dict(kernel_options or {}))
    return PreparedWorkflow(
        name=name,
        graph=compiled["graph"],
        compiled=compiled,
        approval=dict(approval),
    )


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
