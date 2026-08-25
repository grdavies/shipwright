#!/usr/bin/env python3
"""Repo-local ProjectDoctrine lifecycle primitives (PRD 330 R3, R8, R9, R11, R12, R14).

Treats ``.sw/project-doctrine.json`` as the sole consumer ProjectDoctrine source of truth.
Issue-store copies under ``.cursor/sw-planning-projections/`` are projection-only and MUST NOT
be read as authority. Baseline synthesis remains draft until an explicit operator promote.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _sw.cli import build_parser, main_entry, run_module_main

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

DOCTRINE_SCHEMA_REL = Path("core/sw-reference/project-doctrine.schema.json")
BASELINE_SCHEMA_REL = Path("core/sw-reference/project-baseline.schema.json")

DOCTRINE_SOT_REL = Path(".sw/project-doctrine.json")
BASELINE_DRAFT_REL = Path(".sw/project-baseline.draft.json")
PROJECTION_REL = Path(".cursor/sw-planning-projections/project-doctrine.json")

DOCTRINE_FORBIDDEN_ROOT = frozenset({"productRoadmap", "orgChart", "runtimeRunbook"})
BASELINE_FORBIDDEN_ROOT = frozenset(
    {"doctrineAuthority", "productAuthority", "autonomousPromotion", "promoted"}
)
CONFIDENCE_VALUES = frozenset({"high", "medium", "low", "unknown"})


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    verdict: str
    cause: str | None = None
    path: str | None = None
    projectionPath: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"verdict": self.verdict}
        if self.cause is not None:
            out["cause"] = self.cause
        if self.path is not None:
            out["path"] = self.path
        if self.projectionPath is not None:
            out["projectionPath"] = self.projectionPath
        return out


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def doctrine_sot_path(root: Path) -> Path:
    return root / DOCTRINE_SOT_REL


def baseline_draft_path(root: Path) -> Path:
    return root / BASELINE_DRAFT_REL


def projection_path(root: Path) -> Path:
    return root / PROJECTION_REL


def is_authoritative_path(path: Path, root: Path) -> bool:
    try:
        return path.resolve() == doctrine_sot_path(root).resolve()
    except OSError:
        return False


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"expected object JSON at {path}")
    return doc


def load_doctrine(root: Path) -> dict[str, Any] | None:
    return load_json(doctrine_sot_path(root))


def load_baseline_draft(root: Path) -> dict[str, Any] | None:
    return load_json(baseline_draft_path(root))


def _resolve_schema_root(root: Path) -> Path:
    if (root / DOCTRINE_SCHEMA_REL).is_file():
        return root
    plugin_root = SCRIPT_DIR.parent
    if (plugin_root / DOCTRINE_SCHEMA_REL).is_file():
        return plugin_root
    return root


def _load_schema(root: Path, rel: Path) -> dict[str, Any]:
    schema_root = _resolve_schema_root(root)
    path = schema_root / rel
    if not path.is_file():
        raise FileNotFoundError(rel)
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_doctrine_structural(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "id",
        "version",
        "provenance",
        "confidence",
        "expiresAt",
        "sourceRefs",
        "architecture",
        "assessment",
    }
    for key in document:
        if key not in allowed:
            errors.append(f"unknown:{key}")
    for key in DOCTRINE_FORBIDDEN_ROOT:
        if key in document:
            errors.append(f"forbidden:{key}")
    if not _is_non_empty_str(document.get("id")):
        errors.append("missing:id")
    if document.get("version") != "ProjectDoctrine@v1":
        errors.append("invalid:version")
    provenance = document.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("missing:provenance")
    else:
        if not _is_non_empty_str(provenance.get("createdAt")):
            errors.append("missing:provenance.createdAt")
        if not _is_non_empty_str(provenance.get("source")):
            errors.append("missing:provenance.source")
    has_confidence = document.get("confidence") in CONFIDENCE_VALUES
    has_expiry = _is_non_empty_str(document.get("expiresAt"))
    if not has_confidence and not has_expiry:
        errors.append("missing:confidence-or-expiresAt")
    source_refs = document.get("sourceRefs")
    if not isinstance(source_refs, list) or not source_refs:
        errors.append("missing:sourceRefs")
    elif not all(
        isinstance(ref, dict) and _is_non_empty_str(ref.get("uri")) for ref in source_refs
    ):
        errors.append("invalid:sourceRefs")
    architecture = document.get("architecture")
    if architecture is not None and not isinstance(architecture, dict):
        errors.append("invalid:architecture")
    assessment = document.get("assessment")
    if assessment is not None and not isinstance(assessment, dict):
        errors.append("invalid:assessment")
    return errors


def _validate_baseline_structural(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "id",
        "version",
        "provenance",
        "status",
        "confidence",
        "expiresAt",
        "facts",
        "conflicts",
    }
    for key in document:
        if key not in allowed:
            errors.append(f"unknown:{key}")
    for key in BASELINE_FORBIDDEN_ROOT:
        if key in document:
            errors.append(f"forbidden:{key}")
    if not _is_non_empty_str(document.get("id")):
        errors.append("missing:id")
    if document.get("version") != "ProjectBaseline@v1":
        errors.append("invalid:version")
    if document.get("status") != "draft":
        errors.append("invalid:status")
    provenance = document.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("missing:provenance")
    else:
        if not _is_non_empty_str(provenance.get("createdAt")):
            errors.append("missing:provenance.createdAt")
        if not _is_non_empty_str(provenance.get("source")):
            errors.append("missing:provenance.source")
    has_confidence = document.get("confidence") in CONFIDENCE_VALUES
    has_expiry = _is_non_empty_str(document.get("expiresAt"))
    if not has_confidence and not has_expiry:
        errors.append("missing:confidence-or-expiresAt")
    facts = document.get("facts")
    if not isinstance(facts, list):
        errors.append("missing:facts")
    else:
        for fact in facts:
            if not isinstance(fact, dict):
                errors.append("invalid:facts.entry")
                continue
            if not _is_non_empty_str(fact.get("id")) or not _is_non_empty_str(fact.get("claim")):
                errors.append("invalid:facts.entry")
            evidence = fact.get("sourceEvidence")
            if not isinstance(evidence, dict) or not _is_non_empty_str(evidence.get("uri")):
                errors.append("invalid:facts.sourceEvidence")
    conflicts = document.get("conflicts")
    if conflicts is not None and not isinstance(conflicts, list):
        errors.append("invalid:conflicts")
    return errors


def _validate_with_jsonschema(document: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return []
    try:
        jsonschema.validate(document, schema, cls=jsonschema.Draft202012Validator)
    except jsonschema.ValidationError as exc:
        return [f"schema:{exc.message}"]
    return []


def validate_doctrine(document: dict[str, Any], root: Path) -> dict[str, Any]:
    structural = _validate_doctrine_structural(document)
    if structural:
        return {"verdict": "fail", "errors": structural}
    try:
        schema = _load_schema(root, DOCTRINE_SCHEMA_REL)
    except FileNotFoundError as exc:
        return {"verdict": "fail", "errors": [f"missing-schema:{exc}"]}
    schema_errors = _validate_with_jsonschema(document, schema)
    if schema_errors:
        return {"verdict": "fail", "errors": schema_errors}
    return {"verdict": "pass", "errors": []}


def validate_baseline(document: dict[str, Any], root: Path) -> dict[str, Any]:
    structural = _validate_baseline_structural(document)
    if structural:
        return {"verdict": "fail", "errors": structural}
    try:
        schema = _load_schema(root, BASELINE_SCHEMA_REL)
    except FileNotFoundError as exc:
        return {"verdict": "fail", "errors": [f"missing-schema:{exc}"]}
    schema_errors = _validate_with_jsonschema(document, schema)
    if schema_errors:
        return {"verdict": "fail", "errors": schema_errors}
    return {"verdict": "pass", "errors": []}


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def _empty_greenfield_doctrine(*, actor: str) -> dict[str, Any]:
    now = _utc_now()
    return {
        "id": "project-doctrine",
        "version": "ProjectDoctrine@v1",
        "provenance": {
            "createdAt": now,
            "updatedAt": now,
            "source": "greenfield-scaffold",
            "actor": actor,
        },
        "confidence": "unknown",
        "sourceRefs": [{"uri": "file://repo/README.md", "label": "greenfield-scaffold"}],
        "architecture": {
            "modules": [],
            "interfaces": [],
            "seams": [],
            "adapters": [],
            "locality": [],
        },
    }


def scaffold_greenfield(root: Path, *, actor: str, confirm: bool = False) -> LifecycleResult:
    if not confirm:
        return LifecycleResult("refused", "greenfield-scaffold-requires-opt-in")
    doctrine = _empty_greenfield_doctrine(actor=actor)
    verdict = validate_doctrine(doctrine, root)
    if verdict["verdict"] != "pass":
        return LifecycleResult("fail", "invalid-scaffold")
    path = doctrine_sot_path(root)
    _write_json_atomic(path, doctrine)
    return LifecycleResult("pass", path=str(path.relative_to(root)))


def write_baseline_draft(
    root: Path, baseline: dict[str, Any], *, actor: str
) -> LifecycleResult:
    doc = dict(baseline)
    doc["status"] = "draft"
    doc.setdefault("version", "ProjectBaseline@v1")
    provenance = doc.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        doc["provenance"] = provenance
    provenance.setdefault("createdAt", _utc_now())
    provenance["updatedAt"] = _utc_now()
    provenance.setdefault("source", "baseline-synthesis")
    provenance["actor"] = actor
    verdict = validate_baseline(doc, root)
    if verdict["verdict"] != "pass":
        return LifecycleResult("fail", "invalid-baseline-draft")
    path = baseline_draft_path(root)
    _write_json_atomic(path, doc)
    return LifecycleResult("pass", path=str(path.relative_to(root)))


def _baseline_to_doctrine(baseline: dict[str, Any], *, actor: str) -> dict[str, Any]:
    now = _utc_now()
    source_refs: list[dict[str, str]] = []
    for fact in baseline.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        evidence = fact.get("sourceEvidence")
        if isinstance(evidence, dict) and _is_non_empty_str(evidence.get("uri")):
            ref = {"uri": str(evidence["uri"])}
            if _is_non_empty_str(evidence.get("quote")):
                ref["label"] = str(evidence["quote"])[:120]
            source_refs.append(ref)
    if not source_refs:
        source_refs = [{"uri": f"file://repo/{BASELINE_DRAFT_REL.as_posix()}"}]
    return {
        "id": str(baseline.get("id") or "project-doctrine"),
        "version": "ProjectDoctrine@v1",
        "provenance": {
            "createdAt": now,
            "updatedAt": now,
            "source": "baseline-promote",
            "actor": actor,
        },
        "confidence": baseline.get("confidence") or "medium",
        "sourceRefs": source_refs,
    }


def promote_baseline(root: Path, *, actor: str, confirm: bool = False) -> LifecycleResult:
    if not confirm:
        return LifecycleResult("refused", "promote-requires-explicit-confirmation")
    baseline = load_baseline_draft(root)
    if baseline is None:
        return LifecycleResult("fail", "missing-baseline-draft")
    if baseline.get("status") != "draft":
        return LifecycleResult("fail", "baseline-not-draft")
    baseline_verdict = validate_baseline(baseline, root)
    if baseline_verdict["verdict"] != "pass":
        return LifecycleResult("fail", "invalid-baseline-draft")
    doctrine = _baseline_to_doctrine(baseline, actor=actor)
    doctrine_verdict = validate_doctrine(doctrine, root)
    if doctrine_verdict["verdict"] != "pass":
        return LifecycleResult("fail", "invalid-promoted-doctrine")
    sot = doctrine_sot_path(root)
    _write_json_atomic(sot, doctrine)
    return LifecycleResult("pass", path=str(sot.relative_to(root)))


def accept_doctrine(root: Path, doctrine: dict[str, Any], *, actor: str) -> LifecycleResult:
    doc = dict(doctrine)
    provenance = doc.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
        doc["provenance"] = provenance
    provenance.setdefault("createdAt", _utc_now())
    provenance["updatedAt"] = _utc_now()
    provenance.setdefault("source", "operator-accept")
    provenance["actor"] = actor
    verdict = validate_doctrine(doc, root)
    if verdict["verdict"] != "pass":
        return LifecycleResult("fail", "invalid-doctrine")
    path = doctrine_sot_path(root)
    _write_json_atomic(path, doc)
    return LifecycleResult("pass", path=str(path.relative_to(root)))


def reject_adoption(root: Path) -> LifecycleResult:
    path = doctrine_sot_path(root)
    if path.is_file():
        path.unlink()
    if path.exists():
        return LifecycleResult("fail", "reject-incomplete")
    return LifecycleResult("pass")


def write_projection(root: Path, doctrine: dict[str, Any] | None = None) -> LifecycleResult:
    """Mirror repo-local doctrine for issue-store visibility — never authoritative."""
    source = doctrine if doctrine is not None else load_doctrine(root)
    if source is None:
        return LifecycleResult("fail", "missing-doctrine-sot")
    verdict = validate_doctrine(source, root)
    if verdict["verdict"] != "pass":
        return LifecycleResult("fail", "invalid-doctrine-sot")
    envelope = {
        "projection": {
            "authority": "repo-local",
            "sourceOfTruth": DOCTRINE_SOT_REL.as_posix(),
            "projectedAt": _utc_now(),
            "note": "projection-only; never read as ProjectDoctrine authority",
        },
        "doctrine": source,
    }
    path = projection_path(root)
    _write_json_atomic(path, envelope)
    return LifecycleResult(
        "pass",
        path=str(path.relative_to(root)),
        projectionPath=str(path.relative_to(root)),
    )


def load_projection_doctrine(root: Path) -> dict[str, Any] | None:
    envelope = load_json(projection_path(root))
    if envelope is None:
        return None
    doctrine = envelope.get("doctrine")
    return doctrine if isinstance(doctrine, dict) else None


def status_report(root: Path) -> dict[str, Any]:
    sot = load_doctrine(root)
    draft = load_baseline_draft(root)
    projection = load_projection_doctrine(root)
    return {
        "authority": DOCTRINE_SOT_REL.as_posix(),
        "hasDoctrine": sot is not None,
        "hasBaselineDraft": draft is not None,
        "baselineStatus": draft.get("status") if isinstance(draft, dict) else None,
        "hasProjection": projection is not None,
        "projectionIsAuthority": False,
    }


def _cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if args.kind == "doctrine":
        if args.file:
            doc = load_json(Path(args.file))
        else:
            doc = load_doctrine(root)
        if doc is None:
            print(json.dumps({"verdict": "fail", "errors": ["missing:doctrine"]}))
            return 1
        result = validate_doctrine(doc, root)
    else:
        if args.file:
            doc = load_json(Path(args.file))
        else:
            doc = load_baseline_draft(root)
        if doc is None:
            print(json.dumps({"verdict": "fail", "errors": ["missing:baseline"]}))
            return 1
        result = validate_baseline(doc, root)
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "pass" else 1


def _cmd_scaffold(args: argparse.Namespace) -> int:
    result = scaffold_greenfield(
        Path(args.root).resolve(), actor=args.actor, confirm=args.confirm
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.verdict == "pass" else 1


def _cmd_write_baseline(args: argparse.Namespace) -> int:
    doc = load_json(Path(args.file))
    if doc is None:
        print(json.dumps({"verdict": "fail", "cause": "missing-input"}))
        return 1
    result = write_baseline_draft(Path(args.root).resolve(), doc, actor=args.actor)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.verdict == "pass" else 1


def _cmd_promote(args: argparse.Namespace) -> int:
    result = promote_baseline(
        Path(args.root).resolve(), actor=args.actor, confirm=args.confirm
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.verdict == "pass" else 1


def _cmd_accept(args: argparse.Namespace) -> int:
    doc = load_json(Path(args.file)) if args.file else load_doctrine(Path(args.root).resolve())
    if doc is None:
        print(json.dumps({"verdict": "fail", "cause": "missing-input"}))
        return 1
    result = accept_doctrine(Path(args.root).resolve(), doc, actor=args.actor)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.verdict == "pass" else 1


def _cmd_reject(args: argparse.Namespace) -> int:
    result = reject_adoption(Path(args.root).resolve())
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.verdict == "pass" else 1


def _cmd_project(args: argparse.Namespace) -> int:
    result = write_projection(Path(args.root).resolve())
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.verdict == "pass" else 1


def _cmd_status(args: argparse.Namespace) -> int:
    report = status_report(Path(args.root).resolve())
    print(json.dumps(report, indent=2))
    return 0


def build_subparsers(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="Validate doctrine or baseline draft JSON")
    validate.add_argument("root")
    validate.add_argument("--kind", choices=("doctrine", "baseline"), default="doctrine")
    validate.add_argument("--file")
    validate.set_defaults(handler=_cmd_validate)
    scaffold = sub.add_parser("scaffold", help="Opt-in greenfield doctrine scaffold")
    scaffold.add_argument("root")
    scaffold.add_argument("--actor", default="operator")
    scaffold.add_argument("--confirm", action="store_true")
    scaffold.set_defaults(handler=_cmd_scaffold)
    write_baseline = sub.add_parser("write-baseline-draft", help="Persist brownfield draft baseline")
    write_baseline.add_argument("root")
    write_baseline.add_argument("--file", required=True)
    write_baseline.add_argument("--actor", default="operator")
    write_baseline.set_defaults(handler=_cmd_write_baseline)
    promote = sub.add_parser("promote", help="Explicit baseline→doctrine promote")
    promote.add_argument("root")
    promote.add_argument("--actor", default="operator")
    promote.add_argument("--confirm", action="store_true")
    promote.set_defaults(handler=_cmd_promote)
    accept = sub.add_parser("accept", help="Accept reviewed doctrine into repo-local SoT")
    accept.add_argument("root")
    accept.add_argument("--file")
    accept.add_argument("--actor", default="operator")
    accept.set_defaults(handler=_cmd_accept)
    reject = sub.add_parser("reject", help="Reject adoption and remove repo-local doctrine")
    reject.add_argument("root")
    reject.set_defaults(handler=_cmd_reject)
    project = sub.add_parser("project", help="Write issue-store projection from repo-local SoT")
    project.add_argument("root")
    project.set_defaults(handler=_cmd_project)
    status = sub.add_parser("status", help="Report lifecycle state")
    status.add_argument("root")
    status.set_defaults(handler=_cmd_status)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(prog="project_doctrine.py")
    build_subparsers(parser)
    return main_entry(parser, lambda args: args.handler(args), argv)


if __name__ == "__main__":
    run_module_main(main)
