"""Stdlib-only HandoffBundle validation (PRD 349 R7, R8, R10).

Digest is checked before schema. Never imports jsonschema. Schema is loaded via
importlib.resources from ``core.schemas`` when available, else repo filesystem.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping

_PACKAGE = "core.schemas"
_SCHEMA_NAME = "handoff_bundle.json"
_REPO_SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "handoff_bundle.json"
_LEGACY_SCHEMA = (
    Path(__file__).resolve().parents[1] / "sw-reference" / "handoff-bundle.schema.json"
)
_CURRENT_NODE = "current_node"
_REQUIRED = (
    "schemaVersion",
    "goal",
    "currentState",
    "resolvedDecisions",
    "unresolvedDecisions",
    "activeNode",
    "blockers",
    "evidence",
    "changedFiles",
    "relevantRules",
    "nextAction",
    "workflowDigest",
    "exportedAt",
    "expiresAt",
    "bundleDigest",
)


def load_schema() -> dict[str, Any]:
    try:
        from importlib import resources

        traversable = resources.files(_PACKAGE).joinpath(_SCHEMA_NAME)
        with traversable.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (ModuleNotFoundError, FileNotFoundError, AttributeError, TypeError, OSError, json.JSONDecodeError):
        pass
    for path in (_REPO_SCHEMA, _LEGACY_SCHEMA):
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    raise FileNotFoundError("HandoffBundle schema asset not found")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_payload(payload: Mapping[str, Any]) -> str:
    material = {
        k: v
        for k, v in payload.items()
        if k not in {"bundleDigest", "destination_ack"}
    }
    transition = material.get("transitionProvenance")
    if isinstance(transition, dict):
        copy = dict(transition)
        copy.pop("integrity", None)
        material["transitionProvenance"] = copy
    return f"sha256:{hashlib.sha256(canonical_json(material).encode('utf-8')).hexdigest()}"


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _types_ok(expected: Any, actual: str) -> bool:
    if isinstance(expected, list):
        return actual in expected or ("number" in expected and actual == "integer")
    if expected == "number":
        return actual in {"number", "integer"}
    return actual == expected


def _resolve_ref(ref: str, root: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, Mapping) else None


def _validate(
    document: Any,
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any],
    *,
    path: str,
    errors: list[dict[str, str]],
) -> None:
    if "$ref" in schema:
        target = _resolve_ref(str(schema["$ref"]), root_schema)
        if target is None:
            errors.append({"field": path or "$", "error": f"unresolved-ref:{schema['$ref']}"})
            return
        _validate(document, target, root_schema, path=path, errors=errors)
        return

    expected_type = schema.get("type")
    if expected_type is not None:
        actual = _type_name(document)
        if not _types_ok(expected_type, actual):
            errors.append(
                {
                    "field": path or "$",
                    "error": "type-mismatch",
                    "expected": str(expected_type),
                    "actual": actual,
                }
            )
            return

    if "const" in schema and document != schema["const"]:
        errors.append({"field": path or "$", "error": "const-mismatch"})
        return
    if "enum" in schema and document not in schema["enum"]:
        errors.append({"field": path or "$", "error": "enum-mismatch"})
        return

    if isinstance(document, str):
        if "minLength" in schema and len(document) < int(schema["minLength"]):
            errors.append({"field": path or "$", "error": "minLength"})
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, document) is None:
            errors.append({"field": path or "$", "error": "pattern"})

    if isinstance(document, list) and isinstance(schema.get("items"), Mapping):
        for idx, item in enumerate(document):
            child = f"{path}[{idx}]" if path else f"[{idx}]"
            _validate(item, schema["items"], root_schema, path=child, errors=errors)

    if isinstance(document, dict):
        required = schema.get("required") or []
        if isinstance(required, list):
            for key in required:
                if key not in document:
                    errors.append({"field": f"{path}.{key}" if path else key, "error": "required"})
        props = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
        additional = schema.get("additionalProperties")
        for key, value in document.items():
            child = f"{path}.{key}" if path else key
            if key in props and isinstance(props[key], Mapping):
                _validate(value, props[key], root_schema, path=child, errors=errors)
            elif additional is False:
                errors.append({"field": child, "error": "additionalProperties"})
            elif isinstance(additional, Mapping):
                _validate(value, additional, root_schema, path=child, errors=errors)


def validate_bundle(document: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Validate bundle: digest_failure before schema_failure; never weakens without schema lib."""
    del root  # call-site compatibility with scripts.handoff_bundle
    if not isinstance(document, Mapping):
        return {"verdict": "schema_failure", "error": "handoff:not-object", "fields": ["$"]}

    missing = [key for key in _REQUIRED if key not in document]
    if missing:
        return {
            "verdict": "schema_failure",
            "error": "handoff:missing-keys",
            "missing": missing,
            "fields": missing,
        }

    expected = digest_payload(document)
    if str(document.get("bundleDigest") or "") != expected:
        return {
            "verdict": "digest_failure",
            "error": "handoff:digest-mismatch",
            "expected": expected,
        }

    schema = load_schema()
    errors: list[dict[str, str]] = []
    _validate(dict(document), schema, schema, path="", errors=errors)

    # Fail-closed AS2: integer current_node must never coerce to pass.
    if _CURRENT_NODE in document and not isinstance(document[_CURRENT_NODE], str):
        errors.append(
            {
                "field": _CURRENT_NODE,
                "error": "type-mismatch",
                "expected": "string",
                "actual": _type_name(document[_CURRENT_NODE]),
            }
        )

    if errors:
        fields: list[str] = []
        seen: set[str] = set()
        for err in errors:
            field = str(err.get("field") or "")
            if field.startswith("."):
                field = field[1:]
            if field and field not in seen:
                seen.add(field)
                fields.append(field)
        return {
            "verdict": "schema_failure",
            "error": "handoff:schema-invalid",
            "fields": fields,
            "details": errors,
        }
    return {"verdict": "pass"}


def _fixtures_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "bundle_self_test"


def _read_fixture_text(name: str) -> str | None:
    """Load a self-test fixture from the filesystem or the enclosing zipapp."""
    path = _fixtures_dir() / name
    if path.is_file():
        return path.read_text(encoding="utf-8")
    # Zipapp: Path(__file__) looks like ``…/shipwright.pyz/core/handoff/validate_bundle.py``
    # but sibling zip members are not visible via pathlib — read them via ZipFile.
    file_s = str(Path(__file__).resolve())
    marker = ".pyz/"
    if marker not in file_s:
        return None
    pyz_path = Path(file_s.split(marker, 1)[0] + ".pyz")
    member = f"core/tests/fixtures/bundle_self_test/{name}"
    if not pyz_path.is_file():
        return None

    try:
        with zipfile.ZipFile(pyz_path, "r") as zf:
            return zf.read(member).decode("utf-8")
    except KeyError:
        return None


def run_self_test() -> dict[str, Any]:
    cases = (
        ("digest_failure.json", "digest_failure"),
        ("schema_failure.json", "schema_failure"),
        ("field_type_mismatch.json", "schema_failure"),
        ("missing_required.json", "schema_failure"),
        ("pass.json", "pass"),
    )
    results: list[dict[str, Any]] = []
    unexpected = 0
    for name, expected in cases:
        raw = _read_fixture_text(name)
        if raw is None:
            results.append(
                {"fixture": name, "expected": expected, "actual": "missing-fixture", "ok": False}
            )
            unexpected += 1
            continue
        document = json.loads(raw)
        actual = str(validate_bundle(document).get("verdict") or "")
        ok = actual == expected
        if not ok:
            unexpected += 1
        results.append({"fixture": name, "expected": expected, "actual": actual, "ok": ok})
    return {
        "verdict": "pass" if unexpected == 0 else "fail",
        "unexpected": unexpected,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stdlib HandoffBundle validator (PRD 349)")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("path", nargs="?")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.self_test:
        payload = run_self_test()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload.get("verdict") == "pass" else 1
    if not args.path:
        parser.error("path is required unless --self-test")
    document = json.loads(Path(args.path).read_text(encoding="utf-8"))
    result = validate_bundle(document)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
