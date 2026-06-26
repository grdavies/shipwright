#!/usr/bin/env python3
"""Provider-conditional source-of-truth resolver for the decision doc class (PRD 015 R1–R7)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_CONFIG_PATHS = (".cursor/workflow.config.json", "workflow.config.json")
_MARKER_PATHS = (".cursor/sw-memory.provider", "sw-memory.provider")
_KNOWN_PROVIDERS = frozenset({"recallium", "in-repo"})
_EXTERNAL_PROVIDERS = frozenset({"recallium"})
_SOT_KNOB_VALUES = frozenset({"repo", "memory", "auto"})
_DECISION_CLASS = "decision"


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


def read_memory_provider_marker(root: Path) -> str | None:
    for rel in _MARKER_PATHS:
        path = root / rel
        if not path.is_file():
            continue
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if value in _KNOWN_PROVIDERS:
            return value
        return None
    return None


def resolve_memory_provider(root: Path, config: dict | None = None) -> str | None:
    if config is None:
        config = load_config(root)
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    if isinstance(memory, dict) and memory.get("provider"):
        provider = str(memory["provider"])
        if provider in _KNOWN_PROVIDERS:
            return provider
        return None
    return read_memory_provider_marker(root)


def read_source_of_truth_knob(config: dict) -> str:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    if not isinstance(memory, dict):
        return "auto"
    raw = memory.get("sourceOfTruth", "auto")
    if isinstance(raw, str) and raw in _SOT_KNOB_VALUES:
        return raw
    return "auto"


def resolve_effective_sot(knob: str, provider: str | None, doc_class: str) -> str:
    if doc_class != _DECISION_CLASS:
        return "distillation"
    if knob == "repo":
        return "repo"
    if knob == "memory":
        return "memory"
    if provider in _EXTERNAL_PROVIDERS:
        return "memory"
    return "repo"


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
    effective = resolve_effective_sot(knob, provider, doc_class)
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
        if not scoped:
            payload["note"] = "SoT applies to decision class only; other classes are distillation-only"
        emit(payload)

    print(effective)


def build_pointer_recipe(
    effective: str,
    decision_path: str | None,
    memory_id: str | None,
) -> dict:
    if effective not in ("repo", "memory"):
        fail(f"pointer-recipe requires decision effective SoT repo|memory, got {effective!r}")

    norm_path = decision_path.strip() if decision_path else None
    if norm_path and not norm_path.startswith("docs/decisions/"):
        fail("decision path must be under docs/decisions/")

    if effective == "repo":
        return {
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

    return {
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
    recipe = build_pointer_recipe(effective, decision_path or "", memory_id)

    if as_json:
        recipe["sourceOfTruth"] = knob
        recipe["provider"] = provider
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
