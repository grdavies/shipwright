#!/usr/bin/env python3
"""Closed, deterministic transform operators for WorkflowGraph nodes."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class TransformError(ValueError):
    """Raised when a transform request is malformed or non-deterministic."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TransformError(f"transform values must be JSON-compatible: {exc}") from exc


def _stable_key(value: Any) -> bytes:
    return _canonical(value)


def _path(value: Any, selector: str) -> Any:
    if selector in {"", "."}:
        return value
    current = value
    parts = selector.split("/")[1:] if selector.startswith("/") else selector.split(".")
    for raw_part in parts:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(part)] if isinstance(current, list) else current[part]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise TransformError(f"selector {selector!r} did not match input") from exc
    return current


def _items(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise TransformError("operator requires a JSON array input")
    return list(value)


def _map(value: Any, options: Mapping[str, Any]) -> Any:
    selector = str(options.get("selector", ""))
    return [_path(item, selector) for item in _items(value)]


def _filter(value: Any, options: Mapping[str, Any]) -> Any:
    selector = str(options.get("selector", ""))
    expected = options.get("equals", True)
    return [item for item in _items(value) if _path(item, selector) == expected]


def _dedupe(value: Any, options: Mapping[str, Any]) -> Any:
    selector = str(options.get("selector", ""))
    seen: set[bytes] = set()
    result = []
    for item in _items(value):
        key = _stable_key(_path(item, selector))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _sort(value: Any, options: Mapping[str, Any]) -> Any:
    selector = str(options.get("selector", ""))
    reverse = options.get("descending", False)
    if not isinstance(reverse, bool):
        raise TransformError("sort descending must be a boolean")
    return sorted(
        _items(value),
        key=lambda item: _stable_key(_path(item, selector)),
        reverse=reverse,
    )


def _join(value: Any, options: Mapping[str, Any]) -> Any:
    if not isinstance(value, Mapping):
        raise TransformError("join requires an object with left and right arrays")
    left = _items(value.get("left"))
    right = _items(value.get("right"))
    left_key = str(options.get("leftKey", "id"))
    right_key = str(options.get("rightKey", left_key))
    right_index: dict[bytes, list[Any]] = {}
    for item in right:
        right_index.setdefault(_stable_key(_path(item, right_key)), []).append(item)
    result = []
    for left_item in left:
        for right_item in right_index.get(
            _stable_key(_path(left_item, left_key)), []
        ):
            result.append({"left": left_item, "right": right_item})
    return result


def _reduce(value: Any, options: Mapping[str, Any]) -> Any:
    mode = options.get("mode")
    items = _items(value)
    if mode == "count":
        return len(items)
    if mode == "sum":
        selector = str(options.get("selector", ""))
        selected = [_path(item, selector) for item in items]
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in selected):
            raise TransformError("sum requires numeric selected values")
        return sum(selected)
    if mode == "concat":
        return [nested for item in items for nested in _items(item)]
    raise TransformError("reduce mode must be count, sum, or concat")


def _quorum(value: Any, options: Mapping[str, Any]) -> Any:
    items = _items(value)
    minimum = options.get("minimum")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise TransformError("quorum minimum must be a positive integer")
    selector = str(options.get("selector", ""))
    counts: dict[bytes, tuple[Any, int]] = {}
    for item in items:
        selected = _path(item, selector)
        key = _stable_key(selected)
        current = counts.get(key, (selected, 0))
        counts[key] = (current[0], current[1] + 1)
    winners = [
        {"value": selected, "count": count}
        for selected, count in counts.values()
        if count >= minimum
    ]
    return sorted(winners, key=lambda item: _stable_key(item["value"]))


def _select(value: Any, options: Mapping[str, Any]) -> Any:
    selector = options.get("selector")
    if not isinstance(selector, str) or not selector:
        raise TransformError("select requires a non-empty selector")
    return _path(value, selector)


def _project(value: Any, options: Mapping[str, Any]) -> Any:
    fields = options.get("fields")
    if not isinstance(fields, Mapping) or not fields:
        raise TransformError("project requires a non-empty fields object")

    def project_one(item: Any) -> dict[str, Any]:
        return {
            str(name): _path(item, str(selector))
            for name, selector in sorted(fields.items(), key=lambda pair: str(pair[0]))
        }

    return [project_one(item) for item in value] if isinstance(value, list) else project_one(value)


def _validate_schema(value: Any, options: Mapping[str, Any]) -> Any:
    expected = options.get("type")
    types: dict[str, type[Any] | tuple[type[Any], ...]] = {
        "array": list,
        "object": dict,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    if expected not in types:
        raise TransformError("validate-schema requires a supported type")
    if expected in {"number", "integer"} and isinstance(value, bool):
        raise TransformError(f"input does not match schema type {expected}")
    if not isinstance(value, types[str(expected)]):
        raise TransformError(f"input does not match schema type {expected}")
    required = options.get("required", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise TransformError("schema required must be an array of strings")
    if isinstance(value, dict):
        missing = sorted(set(required) - set(value))
        if missing:
            raise TransformError("input is missing required fields: " + ", ".join(missing))
    return value


def _verify_artifact(value: Any, options: Mapping[str, Any]) -> Any:
    expected = options.get("contentHash")
    if not isinstance(expected, str) or len(expected) != 64:
        raise TransformError("verify-artifact requires a SHA-256 contentHash")
    actual = hashlib.sha256(_canonical(value)).hexdigest()
    if actual != expected:
        raise TransformError(f"artifact hash mismatch: expected {expected}, got {actual}")
    return value


@dataclass(frozen=True)
class TransformOperator:
    name: str
    apply: Callable[[Any, Mapping[str, Any]], Any]


TRANSFORM_OPERATORS: Mapping[str, TransformOperator] = {
    "map": TransformOperator("map", _map),
    "filter": TransformOperator("filter", _filter),
    "dedupe": TransformOperator("dedupe", _dedupe),
    "sort": TransformOperator("sort", _sort),
    "join": TransformOperator("join", _join),
    "reduce": TransformOperator("reduce", _reduce),
    "quorum": TransformOperator("quorum", _quorum),
    "select": TransformOperator("select", _select),
    "project": TransformOperator("project", _project),
    "validate-schema": TransformOperator("validate-schema", _validate_schema),
    "verify-artifact": TransformOperator("verify-artifact", _verify_artifact),
}
TRANSFORM_OPERATOR_NAMES = frozenset(TRANSFORM_OPERATORS)


def apply_transform(
    operator: str,
    value: Any,
    options: Mapping[str, Any] | None = None,
) -> Any:
    """Apply a closed-catalog transform and verify its result is replayable JSON."""
    try:
        implementation = TRANSFORM_OPERATORS[operator]
    except KeyError:
        raise TransformError(f"unknown transform operator: {operator}") from None
    result = implementation.apply(value, dict(options or {}))
    _canonical(result)
    return result
