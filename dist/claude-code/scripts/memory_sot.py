#!/usr/bin/env python3
"""Provider-conditional source-of-truth resolver for the decision doc class (PRD 015 R1–R7)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from memory_provider_catalog import CatalogError, get_provider, load_catalog
from memory_provider_register import RegistrationError, validate_registration

_CONFIG_PATHS = (".cursor/workflow.config.json", "workflow.config.json")
_MARKER_PATHS = (".cursor/sw-memory.provider", "sw-memory.provider")
_SOT_KNOB_VALUES = frozenset({"repo", "memory", "auto"})
_DECISION_CLASS = "decision"
_DECISION_VIRTUAL_PREFIX = "docs/decisions/"
DECISION_STUB_ALLOWLIST = frozenset(
    {
        "docs/decisions/INDEX.md",
        "docs/decisions/SUPERSEDED.log",
    }
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def emit(obj: dict, exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2) -> None:
    emit({"verdict": "fail", "error": error}, exit_code)


def load_config(root: Path) -> dict:
    for rel in _CONFIG_PATHS:
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                return {}
    return {}


def _validated_provider(root: Path, provider_id: str) -> str | None:
    value = str(provider_id or "").strip()
    if not value:
        return None
    try:
        validate_registration(root, value)
        return value
    except RegistrationError:
        return None


def read_memory_provider_marker(root: Path) -> str | None:
    for rel in _MARKER_PATHS:
        path = root / rel
        if not path.is_file():
            continue
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return _validated_provider(root, value)
    return None


def resolve_memory_provider(root: Path, config: dict | None = None) -> str | None:
    if config is None:
        config = load_config(root)
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    if isinstance(memory, dict) and memory.get("provider"):
        return _validated_provider(root, str(memory["provider"]))
    return read_memory_provider_marker(root)


def read_source_of_truth_knob(config: dict) -> str:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    if not isinstance(memory, dict):
        return "auto"
    raw = memory.get("sourceOfTruth", "auto")
    if isinstance(raw, str) and raw in _SOT_KNOB_VALUES:
        return raw
    return "auto"


def provider_source_of_truth_class(root: Path, provider: str | None) -> str | None:
    if not provider:
        return None
    try:
        catalog = load_catalog(root)
        entry = get_provider(catalog, provider)
    except CatalogError:
        return None
    source_class = entry.get("sourceOfTruthClass")
    return str(source_class).strip() if isinstance(source_class, str) and source_class.strip() else None


def resolve_effective_sot(
    knob: str,
    provider: str | None,
    doc_class: str,
    *,
    root: Path,
) -> str:
    if doc_class != _DECISION_CLASS:
        return "distillation"
    if knob == "repo":
        return "repo"
    if knob == "memory":
        return "memory"
    if provider_source_of_truth_class(root, provider) == "memory-authoritative":
        return "memory"
    return "repo"


def slugify(text: str) -> str:
    lowered = text.lower().strip()
    slug = _SLUG_RE.sub("-", lowered).strip("-")
    return slug or "unit"


def is_decision_body_path(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    if not norm.startswith(_DECISION_VIRTUAL_PREFIX):
        return False
    if norm in DECISION_STUB_ALLOWLIST:
        return False
    return norm.endswith(".md")


def planning_store_effective(root: Path, config: dict | None = None) -> bool:
    if config is None:
        config = load_config(root)
    from planning_store import resolve_effective_backend

    return resolve_effective_backend(root, config).get("effective") == "issue-store"


def decision_unit_id_from_path(rel_path: str, content: str | None = None) -> str:
    if content and content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            for line in content[4:end].splitlines():
                if line.startswith("id:"):
                    unit = line.partition(":")[2].strip()
                    if unit:
                        return unit
    stem = Path(rel_path).stem
    return f"decision-{slugify(stem)[:48]}"


def resolve_decision_home(root: Path, config: dict | None = None) -> dict:
    """Authoritative decision body home (PRD 072 R6)."""
    if config is None:
        config = load_config(root)
    if planning_store_effective(root, config):
        from planning_store import resolve_store_location

        loc = resolve_store_location(root, config)
        owner = loc.get("owner")
        repo = loc.get("repo")
        store_ref = f"{owner}/{repo}" if owner and repo else None
        return {
            "home": "planning-store",
            "virtualPathPrefix": _DECISION_VIRTUAL_PREFIX,
            "storeRef": store_ref,
            "storeLocation": loc,
            "codeRepoBodies": False,
            "stubsOnly": sorted(DECISION_STUB_ALLOWLIST),
            "alwaysCommittedTarget": "planning-store",
        }
    return {
        "home": "repo",
        "virtualPathPrefix": _DECISION_VIRTUAL_PREFIX,
        "storeRef": None,
        "codeRepoBodies": True,
        "stubsOnly": [],
        "alwaysCommittedTarget": "repo",
    }


def git_root(start: Path) -> Path:
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("not a git repository")
    return Path(proc.stdout.strip())


def cmd_resolve(root: Path, doc_class: str, as_json: bool) -> None:
    config = load_config(root)
    knob = read_source_of_truth_knob(config)
    provider = resolve_memory_provider(root, config)
    effective = resolve_effective_sot(knob, provider, doc_class, root=root)
    scoped = doc_class == _DECISION_CLASS

    if as_json:
        payload: dict = {
            "verdict": "pass",
            "action": "resolve",
            "class": doc_class,
            "sourceOfTruth": knob,
            "provider": provider,
            "effective": effective,
            "scoped": scoped,
        }
        if scoped:
            payload["decisionHome"] = resolve_decision_home(root, config)
        else:
            payload["note"] = "SoT applies to decision class only; other classes are distillation-only"
        emit(payload)

    print(effective)


def build_pointer_recipe(
    effective: str,
    decision_path: str | None,
    memory_id: str | None,
    *,
    decision_home: dict | None = None,
) -> dict:
    if effective not in ("repo", "memory"):
        fail(f"pointer-recipe requires decision effective SoT repo|memory, got {effective!r}")

    norm_path = decision_path.strip() if decision_path else None
    if norm_path and not norm_path.startswith("docs/decisions/"):
        fail("decision path must be under docs/decisions/")

    home = decision_home or {}
    planning_store_home = home.get("home") == "planning-store"

    if effective == "repo":
        recipe = {
            "verdict": "pass",
            "action": "pointer-recipe",
            "effective": "repo",
            "authoritative": "git",
            "nonAuthoritative": "provider",
            "git": {
                "role": "authoritative",
                "snapshotRole": "authoritative",
                "path": norm_path,
            },
            "provider": {
                "role": "pointer",
                "category": "decision",
                "contentBearing": False,
                "relatedFiles": [norm_path] if norm_path else [],
            },
        }
        if planning_store_home:
            recipe["authoritative"] = "planning-store"
            recipe["nonAuthoritative"] = "git"
            recipe["git"] = {
                "role": "pointer",
                "snapshotRole": "stub-only",
                "path": norm_path,
                "stubsOnly": home.get("stubsOnly", []),
            }
            recipe["planningStore"] = {
                "role": "authoritative",
                "virtualPath": norm_path,
                "storeRef": home.get("storeRef"),
            }
        return recipe

    recipe = {
        "verdict": "pass",
        "action": "pointer-recipe",
        "effective": "memory",
        "authoritative": "provider",
        "nonAuthoritative": "git",
        "git": {
            "role": "pointer",
            "snapshotRole": "pointer",
            "path": norm_path,
            "memoryPointer": memory_id,
        },
        "provider": {
            "role": "authoritative",
            "category": "decision",
            "contentBearing": True,
            "memoryId": memory_id,
        },
    }
    if planning_store_home:
        recipe["planningStore"] = {
            "role": "authoritative-body",
            "virtualPath": norm_path,
            "storeRef": home.get("storeRef"),
        }
        recipe["git"]["snapshotRole"] = "stub-only"
        recipe["git"]["stubsOnly"] = home.get("stubsOnly", [])
    return recipe


def cmd_pointer_recipe(
    root: Path,
    decision_path: str | None,
    memory_id: str | None,
    as_json: bool,
) -> None:
    config = load_config(root)
    knob = read_source_of_truth_knob(config)
    provider = resolve_memory_provider(root, config)
    effective = resolve_effective_sot(knob, provider, _DECISION_CLASS)
    decision_home = resolve_decision_home(root, config)
    recipe = build_pointer_recipe(
        effective,
        decision_path or "",
        memory_id,
        decision_home=decision_home,
    )

    if as_json:
        recipe["sourceOfTruth"] = knob
        recipe["provider"] = provider
        recipe["decisionHome"] = decision_home
        emit(recipe)

    side = recipe["authoritative"]
    print(side)


def main() -> None:
    parser = argparse.ArgumentParser(description="Memory source-of-truth resolver")
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser("resolve", help="Resolve authoritative side for a doc class")
    resolve.add_argument("--class", dest="doc_class", default=_DECISION_CLASS)
    resolve.add_argument("--json", action="store_true")
    resolve.add_argument("--root", type=Path, default=None)

    pointer = sub.add_parser(
        "pointer-recipe",
        help="Return inverted pointer roles for decision git vs provider (R6)",
    )
    pointer.add_argument("--path", default=None, help="Repo-relative docs/decisions/<n>-<slug>.md")
    pointer.add_argument("--memory-id", default=None, help="Provider record id when memory-SoT")
    pointer.add_argument("--json", action="store_true")
    pointer.add_argument("--root", type=Path, default=None)

    args = parser.parse_args()
    start = args.root or Path.cwd()
    root = git_root(start)

    if args.command == "resolve":
        cmd_resolve(root, str(args.doc_class), args.json)
    elif args.command == "pointer-recipe":
        cmd_pointer_recipe(root, args.path, args.memory_id, args.json)


if __name__ == "__main__":
    main()
