#!/usr/bin/env python3
"""Author-time capability manifest lint — precedence conflicts and anti-spoof (R11, R25, R27)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from capability_index import build_index, collect_capability_files, derive_kind, parse_frontmatter
from capability_manifest_validate import validate_capability_block
from guidelines_validate import lint_guidelines
from capability_precedence import effective_priority, effective_tier, has_precedence_resolution
from capability_trust import KERNEL_HOOK_SLOTS, MANIFEST_HOOK_SLOTS, is_kernel_hook_source

MULTI_SELECT_TRIGGER_TYPES = frozenset(
    {
        "always_on",
        "text_token",
        "triage_tag",
        "heading",
        "link_pattern",
        "change_digest",
    }
)


def trigger_signature(trigger: dict[str, Any]) -> str:
    trigger_type = trigger.get("type")
    if not trigger_type:
        return "unknown"
    family = trigger.get("selectionFamily", "")
    if trigger_type == "phase_default":
        return f"phase_default:{family}:{trigger.get('command', '')}:{trigger.get('scope', '')}"
    if trigger_type == "always_on":
        return f"always_on:{family}:{trigger.get('scope', '')}"
    if trigger_type == "path_glob":
        globs = trigger.get("globs") or trigger.get("patterns") or []
        return f"path_glob:{family}:{','.join(sorted(str(g) for g in globs))}"
    if trigger_type == "config_flag":
        return (
            f"config_flag:{family}:{trigger.get('key', '')}:"
            f"{trigger.get('equals', '')}:{trigger.get('notEquals', '')}:"
            f"{trigger.get('absent', '')}:{trigger.get('configured', '')}"
        )
    if trigger_type == "text_token":
        tokens = trigger.get("tokens") or []
        source = str(trigger.get("source") or "body_snapshot")
        token_csv = ",".join(sorted(str(t) for t in tokens))
        return ":".join(["text_token", family, source, token_csv])
    if trigger_type == "triage_tag":
        tags = trigger.get("tags") or []
        return f"triage_tag:{family}:{trigger.get('match', 'any')}:{','.join(sorted(tags))}"
    if trigger_type == "heading":
        return f"heading:{family}:{trigger.get('pattern', '')}"
    if trigger_type == "link_pattern":
        return f"link_pattern:{family}:{trigger.get('pattern', '')}"
    if trigger_type in {"any_of", "all_of"}:
        children = trigger.get("triggers") or trigger.get("predicates") or []
        child_sigs = "|".join(sorted(trigger_signature(child) for child in children if isinstance(child, dict)))
        return f"{trigger_type}:{family}:{child_sigs}"
    return f"{trigger_type}:{family}:{json.dumps(trigger, sort_keys=True, separators=(',', ':'))}"


def load_index(index_path: Path) -> dict[str, Any]:
    return json.loads(index_path.read_text(encoding="utf-8"))


def check_duplicate_ids(entries: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, str] = {}
    errors: list[str] = []
    for entry in entries:
        cap_id = entry.get("id")
        if not isinstance(cap_id, str):
            continue
        if cap_id in seen:
            errors.append(f"duplicate capability id: {cap_id} ({seen[cap_id]} and {entry.get('sourcePath')})")
        else:
            seen[cap_id] = str(entry.get("sourcePath", ""))
    return errors


def check_kind_and_phantom(repo_root: Path, entries: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for entry in entries:
        source_path = entry.get("sourcePath")
        if not isinstance(source_path, str):
            errors.append(f"missing sourcePath on index row {entry.get('id')!r}")
            continue
        artifact = repo_root / source_path
        if not artifact.is_file():
            errors.append(f"phantom index entry: {entry.get('id')} references missing artifact {source_path}")
            continue
        try:
            expected_kind = derive_kind(source_path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        indexed_kind = entry.get("kind")
        if indexed_kind != expected_kind:
            errors.append(
                f"kind/path mismatch: {entry.get('id')} declares kind={indexed_kind!r} "
                f"but path {source_path} derives {expected_kind!r}"
            )
    return errors


def is_capabilities_contract(entry: dict[str, Any]) -> bool:
    source_path = str(entry.get("sourcePath") or "")
    return source_path.endswith("/CAPABILITIES.md") or source_path.endswith("CAPABILITIES.md")


def check_competing_defaults(entries: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    defaults: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        capability = entry.get("capability")
        if not isinstance(capability, dict):
            continue
        triggers = capability.get("triggers") or []
        for trigger in triggers:
            if not isinstance(trigger, dict) or trigger.get("type") != "phase_default":
                continue
            command = str(trigger.get("command") or "")
            scope = str(trigger.get("scope") or "")
            kind = str(entry.get("kind") or "")
            key = f"{trigger.get('selectionFamily', '')}:{command}:{scope}:{kind}"
            defaults.setdefault(key, []).append(entry)
    for key, group in defaults.items():
        if len(group) < 2:
            continue
        for i, left in enumerate(group):
            left_cap = left.get("capability") or {}
            for right in group[i + 1 :]:
                right_cap = right.get("capability") or {}
                if has_precedence_resolution(left_cap, right_cap):
                    continue
                errors.append(
                    "competing phase_default without precedence resolution: "
                    f"{left.get('id')} and {right.get('id')} for {key or '(unspecified command)'}"
                )
    return errors


def check_trigger_overlaps(entries: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    by_signature: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        capability = entry.get("capability")
        if not isinstance(capability, dict):
            continue
        for trigger in capability.get("triggers") or []:
            if not isinstance(trigger, dict):
                continue
            signature = trigger_signature(trigger)
            by_signature.setdefault(signature, []).append({"entry": entry, "trigger": trigger})
    for signature, group in by_signature.items():
        if len(group) < 2:
            continue
        trigger_type = group[0]["trigger"].get("type")
        if trigger_type in MULTI_SELECT_TRIGGER_TYPES:
            continue
        for i, left in enumerate(group):
            left_entry = left["entry"]
            left_cap = left_entry.get("capability") or {}
            for right in group[i + 1 :]:
                right_entry = right["entry"]
                right_cap = right_entry.get("capability") or {}
                if left_entry.get("kind") != right_entry.get("kind"):
                    continue
                if is_capabilities_contract(left_entry) or is_capabilities_contract(right_entry):
                    continue
                if has_precedence_resolution(left_cap, right_cap, trigger=left["trigger"]):
                    continue
                errors.append(
                    "overlapping trigger at equal precedence without resolution: "
                    f"{left_entry.get('id')} and {right_entry.get('id')} share {signature}"
                )
    return errors


def check_kernel_hook_manifests(repo_root: Path, core_root: Path) -> list[str]:
    errors: list[str] = []
    for path in collect_capability_files(core_root):
        rel = path.relative_to(core_root)
        source_path = f"core/{rel.as_posix()}"
        if not is_kernel_hook_source(source_path):
            continue
        text = path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
        if isinstance(frontmatter.get("capability"), dict):
            errors.append(
                "kernel hook manifest rejected: "
                f"{source_path} is non-selectable (beforeSubmitPrompt guardrails / memory-redaction kernel)"
            )
    return errors


def check_manifest_schema(core_root: Path) -> list[str]:
    errors: list[str] = []
    for path in collect_capability_files(core_root):
        rel = path.relative_to(core_root)
        source_path = f"core/{rel.as_posix()}"
        text = path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
        capability = frontmatter.get("capability")
        if not isinstance(capability, dict):
            continue
        errors.extend(validate_capability_block(capability, source=source_path))
        metadata = capability.get("metadata") or {}
        gate_ref = metadata.get("gateRef") if isinstance(metadata, dict) else None
        if gate_ref and str(gate_ref).startswith("hooks.json:"):
            slot = str(gate_ref)[len("hooks.json:") :]
            if slot in KERNEL_HOOK_SLOTS:
                errors.append(
                    f"{source_path}: hook gateRef targets kernel slot {slot!r} — manifest hooks may only augment "
                    f"{sorted(MANIFEST_HOOK_SLOTS)}"
                )
    return errors


def lint_index(repo_root: Path, index: dict[str, Any]) -> list[str]:
    entries = index.get("capabilities")
    if not isinstance(entries, list):
        return ["capability index missing capabilities array"]
    errors: list[str] = []
    errors.extend(check_duplicate_ids(entries))
    errors.extend(check_kind_and_phantom(repo_root, entries))
    errors.extend(check_competing_defaults(entries))
    errors.extend(check_trigger_overlaps(entries))
    return errors


def lint_repo(repo_root: Path, *, index_path: Path | None = None) -> tuple[bool, list[str]]:
    path = index_path or (repo_root / "core" / "sw-reference" / "capability-index.json")
    if not path.is_file():
        return False, [f"missing capability index: {path}"]
    index = load_index(path)
    errors = lint_index(repo_root, index)
    return (len(errors) == 0, errors)



def check_guidelines_artifact(repo_root: Path) -> list[str]:
    """Validate guidelines.json via the shared author-time harness (PRD 022 R30 / SC7)."""
    ok, errors = lint_guidelines(repo_root)
    return [] if ok else errors

def lint_core(repo_root: Path, core_root: Path, *, index_path: Path | None = None) -> tuple[bool, list[str]]:
    path = index_path or (core_root / "sw-reference" / "capability-index.json")
    if index_path and index_path.is_file():
        index = load_index(index_path)
    else:
        index = build_index(core_root)
    errors = lint_index(repo_root, index)
    errors.extend(check_kernel_hook_manifests(repo_root, core_root))
    if index_path is None:
        errors.extend(check_manifest_schema(core_root))
        errors.extend(check_guidelines_artifact(repo_root))
    return (len(errors) == 0, errors)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Capability manifest author-time lint")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--core", type=Path, default=None, help="Override core/ root (fixtures)")
    parser.add_argument("--index", type=Path, default=None, help="Override capability-index.json path")
    args = parser.parse_args()

    repo_root = args.root.resolve()
    core_root = (args.core or (repo_root / "core")).resolve()
    ok, errors = lint_core(repo_root, core_root, index_path=args.index.resolve() if args.index else None)
    if ok:
        print("capability-manifest-lint: pass")
        return 0
    for error in errors:
        print(f"capability-manifest-lint: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
