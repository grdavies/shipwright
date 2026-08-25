#!/usr/bin/env python3
"""Detect and repair Shipwright-self doctrine leakage in consumer artifacts (PRD 330 R3, R8, R13).

Consumer ProjectDoctrine must not embed bundled Shipwright-self law. Valid references use an
explicit pointer (``shipwrightSelfRef`` with ``kind: pointer``) without copying bundled statements
into consumer-owned fields.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _sw.cli import run_module_main

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

DOCTRINE_SOT_REL = Path(".cursor/project-doctrine.json")
SHIPWRIGHT_SELF_REF_KEY = "shipwrightSelfRef"
POINTER_KIND = "pointer"
BUNDLED_AD_IDS = frozenset({"AD-1", "AD-2", "AD-3", "AD-4", "AD-5", "AD-6"})
BUNDLED_LAW_SNIPPETS: tuple[str, ...] = (
    "Python-first workflow logic",
    "Broker-only credential access",
    "CI readiness gate authority",
    "Worktree-isolated delivery",
    "Mechanical docs reconciliation",
    "sw- command namespace",
)
FORBIDDEN_EMBED_KEYS = frozenset(
    {"shipwrightSelf", "bundledShipwright", "bundledShipwrightLaw", "shipwrightSelfLaw"}
)
BUNDLED_URI_MARKERS: tuple[str, ...] = (
    "architecture-doctrine.md",
    "shipwright-self:",
    "shipwright:core/sw-reference/architecture-doctrine",
)


@dataclass(frozen=True)
class LeakageFinding:
    rule: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "path": self.path, "message": self.message}


def _is_non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _pointer_path(path: str) -> str:
    return f"{path}.{SHIPWRIGHT_SELF_REF_KEY}" if path else SHIPWRIGHT_SELF_REF_KEY


def is_valid_shipwright_self_pointer(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("kind") != POINTER_KIND:
        return False
    uri = value.get("uri")
    if not _is_non_empty_str(uri):
        return False
    uri_text = str(uri)
    return any(marker in uri_text for marker in BUNDLED_URI_MARKERS)


def _string_has_bundled_law(text: str) -> str | None:
    for snippet in BUNDLED_LAW_SNIPPETS:
        if snippet in text:
            return snippet
    if "shipwright-self" in text.lower() and "kind" not in text:
        return "shipwright-self"
    return None


def _scan_strings(
    value: Any,
    *,
    path: str,
    skip_paths: frozenset[str],
    findings: list[LeakageFinding],
) -> None:
    if path in skip_paths:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if child_path in skip_paths:
                continue
            if key in FORBIDDEN_EMBED_KEYS:
                findings.append(
                    LeakageFinding(
                        rule="forbidden-embed-key",
                        path=child_path,
                        message=f"consumer doctrine must not embed bundled key {key!r}",
                    )
                )
            _scan_strings(child, path=child_path, skip_paths=skip_paths, findings=findings)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _scan_strings(
                child,
                path=f"{path}[{index}]",
                skip_paths=skip_paths,
                findings=findings,
            )
        return
    if isinstance(value, str):
        snippet = _string_has_bundled_law(value)
        if snippet is not None:
            findings.append(
                LeakageFinding(
                    rule="bundled-law-snippet",
                    path=path,
                    message=f"copied Shipwright-self law snippet: {snippet!r}",
                )
            )


def _scan_architecture_entries(document: dict[str, Any], findings: list[LeakageFinding]) -> None:
    architecture = document.get("architecture")
    if not isinstance(architecture, dict):
        return
    for bucket in ("modules", "interfaces", "seams", "adapters", "locality"):
        items = architecture.get(bucket)
        if not isinstance(items, list):
            continue
        for index, entry in enumerate(items):
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            base = f"architecture.{bucket}[{index}]"
            if entry_id in BUNDLED_AD_IDS:
                findings.append(
                    LeakageFinding(
                        rule="bundled-ad-id",
                        path=base,
                        message=f"architecture entry reuses bundled Shipwright-self id {entry_id!r}",
                    )
                )
            for field in ("name", "description", "rationale"):
                text = entry.get(field)
                if isinstance(text, str):
                    snippet = _string_has_bundled_law(text)
                    if snippet is not None:
                        findings.append(
                            LeakageFinding(
                                rule="bundled-architecture-field",
                                path=f"{base}.{field}",
                                message=f"copied bundled rationale in {field}: {snippet!r}",
                            )
                        )


def _scan_source_refs(document: dict[str, Any], findings: list[LeakageFinding]) -> None:
    source_refs = document.get("sourceRefs")
    if not isinstance(source_refs, list):
        return
    for index, ref in enumerate(source_refs):
        if not isinstance(ref, dict):
            continue
        uri = ref.get("uri")
        label = ref.get("label")
        uri_text = uri if isinstance(uri, str) else ""
        if any(marker in uri_text for marker in BUNDLED_URI_MARKERS):
            label_text = label if isinstance(label, str) else ""
            snippet = _string_has_bundled_law(label_text) if label_text else None
            if snippet is not None or any(
                field in ref for field in ("rationale", "law", "statements")
            ):
                findings.append(
                    LeakageFinding(
                        rule="bundled-source-ref-law",
                        path=f"sourceRefs[{index}]",
                        message="sourceRef copies bundled Shipwright-self law instead of a consumer pointer",
                    )
                )


def scan_doctrine(document: dict[str, Any]) -> list[LeakageFinding]:
    """Return deterministic leakage findings for a consumer doctrine document."""
    findings: list[LeakageFinding] = []
    pointer = document.get(SHIPWRIGHT_SELF_REF_KEY)
    skip_paths = (
        frozenset({_pointer_path("")})
        if is_valid_shipwright_self_pointer(pointer)
        else frozenset()
    )
    if pointer is not None and not is_valid_shipwright_self_pointer(pointer):
        findings.append(
            LeakageFinding(
                rule="invalid-shipwright-self-ref",
                path=_pointer_path(""),
                message="shipwrightSelfRef must be kind:pointer to bundled architecture doctrine",
            )
        )
    _scan_strings(document, path="", skip_paths=skip_paths, findings=findings)
    _scan_architecture_entries(document, findings=findings)
    _scan_source_refs(document, findings=findings)
    return findings


def evaluate_doctrine(document: dict[str, Any]) -> dict[str, Any]:
    findings = scan_doctrine(document)
    return {
        "verdict": "pass" if not findings else "fail",
        "findingCount": len(findings),
        "findings": [finding.as_dict() for finding in findings],
    }


def _default_pointer() -> dict[str, str]:
    return {
        "uri": "shipwright-self:core/sw-reference/architecture-doctrine.md",
        "kind": POINTER_KIND,
        "label": "Bundled Shipwright-self reference (pointer only)",
    }


def _strip_leaked_strings(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            if key in FORBIDDEN_EMBED_KEYS:
                continue
            cleaned[key] = _strip_leaked_strings(child)
        return cleaned
    if isinstance(value, list):
        return [_strip_leaked_strings(child) for child in value]
    if isinstance(value, str):
        snippet = _string_has_bundled_law(value)
        return "" if snippet is not None else value
    return value


def _strip_leaked_architecture(document: dict[str, Any]) -> None:
    architecture = document.get("architecture")
    if not isinstance(architecture, dict):
        return
    for bucket in ("modules", "interfaces", "seams", "adapters", "locality"):
        items = architecture.get(bucket)
        if not isinstance(items, list):
            continue
        kept: list[dict[str, Any]] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            if entry_id in BUNDLED_AD_IDS:
                continue
            leaked = False
            for field in ("name", "description", "rationale"):
                text = entry.get(field)
                if isinstance(text, str) and _string_has_bundled_law(text):
                    leaked = True
                    break
            if not leaked:
                kept.append(entry)
        architecture[bucket] = kept


def _strip_leaked_source_refs(document: dict[str, Any]) -> None:
    source_refs = document.get("sourceRefs")
    if not isinstance(source_refs, list):
        return
    kept: list[dict[str, Any]] = []
    for ref in source_refs:
        if not isinstance(ref, dict):
            continue
        uri = ref.get("uri")
        uri_text = uri if isinstance(uri, str) else ""
        label = ref.get("label")
        label_text = label if isinstance(label, str) else ""
        if any(marker in uri_text for marker in BUNDLED_URI_MARKERS):
            if _string_has_bundled_law(label_text) or any(
                field in ref for field in ("rationale", "law", "statements")
            ):
                continue
        kept.append(ref)
    document["sourceRefs"] = kept


def migrate_doctrine(
    document: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    """Repair leakage via pointer (add bundled ref) or replace (strip only)."""
    if mode not in {"pointer", "replace"}:
        raise ValueError(f"unsupported migration mode: {mode}")
    migrated = copy.deepcopy(document)
    for key in FORBIDDEN_EMBED_KEYS:
        migrated.pop(key, None)
    migrated = _strip_leaked_strings(migrated)
    if not isinstance(migrated, dict):
        raise ValueError("doctrine document must be a JSON object")
    _strip_leaked_architecture(migrated)
    _strip_leaked_source_refs(migrated)
    if mode == "pointer":
        migrated[SHIPWRIGHT_SELF_REF_KEY] = _default_pointer()
    else:
        migrated.pop(SHIPWRIGHT_SELF_REF_KEY, None)
    return migrated


def load_doctrine(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("doctrine document must be a JSON object")
    return document


def run_scan(root: Path, *, doctrine_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    path = doctrine_path or (root / DOCTRINE_SOT_REL)
    if not path.is_file():
        return {
            "verdict": "fail",
            "path": str(path.relative_to(root) if path.is_relative_to(root) else path),
            "findingCount": 1,
            "findings": [
                {
                    "rule": "doctrine-missing",
                    "path": str(DOCTRINE_SOT_REL),
                    "message": "consumer doctrine artifact missing",
                }
            ],
        }
    document = load_doctrine(path)
    result = evaluate_doctrine(document)
    result["path"] = str(path.relative_to(root) if path.is_relative_to(root) else path)
    return result


def validate_leakage_green(root: Path) -> str | None:
    """Fail-closed hook — first failure message or None when green."""
    result = run_scan(root)
    if result.get("verdict") == "pass":
        return None
    findings = result.get("findings") or []
    if findings:
        first = findings[0]
        return f"{first.get('rule')}: {first.get('message')}"
    return "project-doctrine-leakage-failed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="project_doctrine_leakage.py")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan_parser = sub.add_parser("scan", help="Scan consumer doctrine for Shipwright-self leakage")
    scan_parser.add_argument(
        "--doctrine",
        help="Doctrine JSON path (default: .cursor/project-doctrine.json)",
    )

    migrate_parser = sub.add_parser("migrate", help="Repair leakage in a doctrine document")
    migrate_parser.add_argument("--doctrine", required=True, help="Doctrine JSON path")
    migrate_parser.add_argument(
        "--mode",
        choices=("pointer", "replace"),
        required=True,
        help="pointer adds shipwrightSelfRef; replace strips leaked law only",
    )
    migrate_parser.add_argument(
        "--out",
        help="Output path (default: overwrite --doctrine)",
    )

    ns = parser.parse_args(argv)
    root = Path(ns.root).resolve()

    if ns.cmd == "scan":
        doctrine_path = Path(ns.doctrine).resolve() if ns.doctrine else None
        payload = run_scan(root, doctrine_path=doctrine_path)
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("verdict") == "pass" else 1

    if ns.cmd == "migrate":
        doctrine_path = Path(ns.doctrine).resolve()
        document = load_doctrine(doctrine_path)
        migrated = migrate_doctrine(document, mode=ns.mode)
        out_path = Path(ns.out).resolve() if ns.out else doctrine_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(migrated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        after = evaluate_doctrine(migrated)
        payload = {
            "mode": ns.mode,
            "path": str(out_path),
            "before": evaluate_doctrine(document),
            "after": after,
            "verdict": after.get("verdict"),
        }
        print(json.dumps(payload, indent=2))
        return 0 if after.get("verdict") == "pass" else 1

    return 2


if __name__ == "__main__":
    run_module_main(main)
