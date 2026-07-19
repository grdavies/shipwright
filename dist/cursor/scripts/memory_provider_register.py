#!/usr/bin/env python3
"""Validate memory provider registration against catalog + adapter integrity (PRD 071 R1, R3)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from capability_index import extract_capability_block, parse_frontmatter
from memory_provider_catalog import CatalogError, get_provider, load_catalog
from sw_resolve_plugin_root import resolve_plugin_root

PROVIDER_ID_RE = re.compile(r"^[a-z0-9-]+$")
_TRAVERSAL_MARKERS = ("..", "/", "\\")


class RegistrationError(Exception):
    """Raised when a provider id fails registration validation."""

    def __init__(self, message: str, *, cause: str) -> None:
        super().__init__(message)
        self.cause = cause


def validate_provider_id(provider_id: str) -> str:
    """Charset + traversal guard for provider ids."""
    if not isinstance(provider_id, str):
        raise RegistrationError("provider id must be a string", cause="invalid")
    value = provider_id.strip()
    if not value:
        raise RegistrationError("provider id must be non-empty", cause="empty")
    if any(marker in value for marker in _TRAVERSAL_MARKERS):
        raise RegistrationError(f"provider id contains traversal markers: {value!r}", cause="traversal")
    if not PROVIDER_ID_RE.fullmatch(value):
        raise RegistrationError(
            f"provider id must match ^[a-z0-9-]+$: {value!r}",
            cause="invalid",
        )
    return value


def _resolve_under_root(root: Path, rel: str, *, label: str) -> Path:
    if not isinstance(rel, str) or not rel.strip():
        raise RegistrationError(f"{label} must be a non-empty path", cause="partial")
    rel_path = Path(rel.strip())
    if rel_path.is_absolute():
        raise RegistrationError(f"{label} must be repo-relative: {rel!r}", cause="traversal")
    if ".." in rel_path.parts:
        raise RegistrationError(f"{label} must not contain .. segments: {rel!r}", cause="traversal")
    resolved = (root / rel_path).resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise RegistrationError(f"{label} escapes repo root: {rel!r}", cause="traversal") from exc
    return resolved


def resolve_adapter_doc(root: Path, adapter_doc_rel: str) -> Path:
    """Resolve adapter markdown; accept plugin dist layout (providers/ vs core/providers/)."""
    primary = _resolve_under_root(root, adapter_doc_rel, label="adapterDoc")
    if primary.is_file():
        return primary
    rel = Path(str(adapter_doc_rel).strip())
    # Dist emitters copy core/providers → providers/ at the plugin root.
    if len(rel.parts) >= 2 and rel.parts[0] == "core":
        alt_rel = Path(*rel.parts[1:]).as_posix()
        alt = _resolve_under_root(root, alt_rel, label="adapterDoc")
        if alt.is_file():
            return alt
    return primary


def resolve_rules_script(root: Path, plugin_root: Path, rules_script_rel: str) -> Path:
    rel = rules_script_rel.strip()
    if rel.startswith("core/"):
        path = _resolve_under_root(root, rel, label="rulesScript")
        if path.is_file():
            return path
        # Same core/ → top-level remap used for adapter docs in plugin installs.
        alt_rel = Path(*Path(rel).parts[1:]).as_posix()
        alt = _resolve_under_root(plugin_root, alt_rel, label="rulesScript")
        if alt.is_file():
            return alt
        return path
    return _resolve_under_root(plugin_root, rel, label="rulesScript")


def _memory_trigger_matches(capability: dict[str, Any], provider_id: str) -> bool:
    triggers = capability.get("triggers")
    if not isinstance(triggers, list):
        return False
    for trigger in triggers:
        if not isinstance(trigger, dict):
            continue
        if trigger.get("type") != "config_flag":
            continue
        if trigger.get("key") != "memory.provider":
            continue
        if str(trigger.get("equals", "")).strip() == provider_id:
            return True
    return False


def validate_adapter_integrity(root: Path, provider_id: str, adapter_doc_rel: str) -> Path:
    """Adapter doc must exist and declare a matching memory capability block."""
    path = resolve_adapter_doc(root, adapter_doc_rel)
    if not path.is_file():
        raise RegistrationError(f"adapter doc missing: {adapter_doc_rel}", cause="missing")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistrationError(f"adapter doc unreadable: {adapter_doc_rel}", cause="missing") from exc

    capability = extract_capability_block(parse_frontmatter(text))
    if capability is None:
        raise RegistrationError(f"adapter doc missing shipwright-capability: {adapter_doc_rel}", cause="partial")

    metadata = capability.get("metadata")
    if not isinstance(metadata, dict):
        raise RegistrationError(f"adapter doc missing capability metadata: {adapter_doc_rel}", cause="partial")

    adapter_id = str(metadata.get("adapterId") or "").strip()
    if adapter_id != provider_id:
        raise RegistrationError(
            f"adapterId mismatch for {provider_id!r}: {adapter_id!r}",
            cause="integrity",
        )

    provider_family = str(metadata.get("providerFamily") or "").strip()
    if provider_family != "memory":
        raise RegistrationError(
            f"providerFamily must be memory for {provider_id!r}: {provider_family!r}",
            cause="integrity",
        )

    if not _memory_trigger_matches(capability, provider_id):
        raise RegistrationError(
            f"adapter doc missing memory.provider trigger for {provider_id!r}",
            cause="integrity",
        )

    return path


def validate_rules_script(root: Path, plugin_root: Path, rules_script_rel: str) -> Path:
    """Rules script must exist, stay in-bounds, and be executable Python."""
    path = resolve_rules_script(root, plugin_root, rules_script_rel)
    if not path.is_file():
        raise RegistrationError(f"rules script missing: {rules_script_rel}", cause="missing")

    if path.suffix != ".py":
        raise RegistrationError(f"rules script must be Python: {rules_script_rel}", cause="partial")

    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistrationError(f"rules script unreadable: {rules_script_rel}", cause="missing") from exc

    try:
        compile(source, str(path), "exec")
    except SyntaxError as exc:
        raise RegistrationError(
            f"rules script has invalid Python: {rules_script_rel}: {exc}",
            cause="partial",
        ) from exc

    return path


def validate_registration(
    root: Path,
    provider_id: str,
    *,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate provider id charset, catalog membership, adapter integrity, and rules script."""
    normalized = validate_provider_id(provider_id)
    try:
        catalog_doc = catalog if catalog is not None else load_catalog(root)
    except CatalogError as exc:
        raise RegistrationError(str(exc), cause=exc.cause) from exc

    try:
        row = get_provider(catalog_doc, normalized)
    except CatalogError as exc:
        raise RegistrationError(str(exc), cause="unknown") from exc

    adapter_doc = str(row.get("adapterDoc") or "").strip()
    rules_script = str(row.get("rulesScript") or "").strip()
    if not adapter_doc or not rules_script:
        raise RegistrationError(
            f"catalog row incomplete for {normalized!r}",
            cause="partial",
        )

    plugin_root = resolve_plugin_root(root / "scripts")
    adapter_path = validate_adapter_integrity(root, normalized, adapter_doc)
    rules_path = validate_rules_script(root, plugin_root, rules_script)

    return {
        "providerId": normalized,
        "adapterDoc": adapter_doc,
        "adapterPath": str(adapter_path.relative_to(root.resolve())),
        "rulesScript": rules_script,
        "rulesPath": str(rules_path.relative_to(root.resolve())),
    }


def _default_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    import os
    for key in ("SW_REPO_ROOT", "ROOT"):
        raw = os.environ.get(key, "").strip()
        if raw:
            candidate = Path(raw)
            if candidate.is_dir():
                return candidate.resolve()
    return Path.cwd().resolve()


def cmd_validate(args: argparse.Namespace) -> int:
    root = _default_root(args.root)
    try:
        result = validate_registration(root, args.provider_id)
    except RegistrationError as exc:
        payload = {"ok": False, "error": str(exc), "cause": exc.cause}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(str(exc), file=sys.stderr)
        return 1
    payload = {"ok": True, **result}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(result["providerId"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate memory provider registration (PRD 071 R1/R3).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate a provider id against catalog + adapters")
    validate.add_argument("provider_id", help="Catalog-registered memory provider id")
    validate.add_argument("--root", type=Path, default=None, help="Repository root")
    validate.add_argument("--json", action="store_true", help="Emit JSON result")
    validate.set_defaults(handler=cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
