#!/usr/bin/env python3
"""Curated greenfield profile — single source for init write-draft and findings (PRD 324 R9–R10)."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from _sw.cli import run_module_main

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

OPERATOR_CHOICE = "operator choice"
Tier = Literal["curated", "advanced"]
Status = Literal["present", "defaulted", "unset", "deprecated"]

EXAMPLE_CONFIG_REL = Path("core/sw-reference/workflow.config.example.json")
SCHEMA_REL = Path("core/sw-reference/config.schema.json")
COMM_DEFAULTS_REL = Path("core/sw-reference/communication-routing.defaults.json")
LEAF_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "null"})


@dataclass(frozen=True, slots=True)
class ProfileEntry:
    path: tuple[str, ...]
    recommended: Any
    tier: Tier
    note: str = ""


# Ordered curated + advanced rows — sole authority for greenfield profile classification.
_PROFILE_ENTRIES: tuple[ProfileEntry, ...] = (
    ProfileEntry(("doc", "afterTasks"), "confirm", "curated"),
    ProfileEntry(("orchestration", "planPolicy"), "proposed", "curated"),
    ProfileEntry(("delegation", "mode"), "heuristic", "curated"),
    ProfileEntry(("planning", "autonomy"), "full-conductor", "curated"),
    ProfileEntry(("planning", "store", "backend"), "in-repo-public", "curated"),
    ProfileEntry(("deliver", "autonomy", "mode"), "autonomous", "curated"),
    ProfileEntry(("deliver", "autonomy", "maxRunMinutes"), 1440, "curated"),
    ProfileEntry(("deliver", "autonomy", "maxIterations"), 500, "curated"),
    ProfileEntry(("deliver", "loop", "drainMechanical"), True, "curated"),
    ProfileEntry(("inefficiency", "enabled"), True, "curated"),
    ProfileEntry(("execute", "enabled"), True, "curated"),
    ProfileEntry(("compound", "autonomy"), "supervised", "curated"),
    ProfileEntry(("memory", "guardrails", "enforceBeforeSubmit"), True, "curated"),
    ProfileEntry(("memory", "guardrails", "requireRuleClass"), False, "curated"),
    ProfileEntry(("review", "provider"), "none", "curated"),
    ProfileEntry(("memory", "provider"), "in-repo", "curated"),
    ProfileEntry(("memory", "sourceOfTruth"), "auto", "curated"),
    ProfileEntry(("communication", "defaultIntensity"), "bundled defaults", "curated", "communication-routing.defaults.json"),
    ProfileEntry(("projectId",), OPERATOR_CHOICE, "curated", "repo identity slug"),
    ProfileEntry(("host", "credentialRef"), OPERATOR_CHOICE, "curated", "broker selector ref"),
    ProfileEntry(("memory", "credentialRef"), OPERATOR_CHOICE, "curated", "broker selector ref"),
    ProfileEntry(("planning", "store", "issues", "credentialRef"), OPERATOR_CHOICE, "curated", "broker selector ref"),
    ProfileEntry(("graphExecution",), OPERATOR_CHOICE, "advanced", "graph runtime tuning"),
    ProfileEntry(("tournament", "enabled"), False, "advanced", "tournament routing — not seeded on greenfield"),
    ProfileEntry(("tournament", "n"), 3, "advanced"),
    ProfileEntry(("tournament", "cost_ceiling"), 0, "advanced"),
    ProfileEntry(("verifyE2e", "enabled"), False, "advanced"),
    ProfileEntry(("verifyMutation", "enabled"), False, "advanced"),
)


def profile_entries() -> tuple[ProfileEntry, ...]:
    return _PROFILE_ENTRIES


def curated_entries() -> tuple[ProfileEntry, ...]:
    return tuple(entry for entry in _PROFILE_ENTRIES if entry.tier == "curated")


def advanced_entries() -> tuple[ProfileEntry, ...]:
    return tuple(entry for entry in _PROFILE_ENTRIES if entry.tier == "advanced")


def curated_posture_leaf_keys() -> tuple[tuple[tuple[str, ...], Any], ...]:
    """Seedable curated leaf keys — sole derivation from curated profile (PRD 324 R9)."""
    out: list[tuple[tuple[str, ...], Any]] = []
    for entry in curated_entries():
        if entry.recommended in (OPERATOR_CHOICE, "bundled defaults"):
            continue
        out.append((entry.path, entry.recommended))
    return tuple(out)


def _set_nested(doc: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cur: dict[str, Any] = doc
    for key in path[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[path[-1]] = value


def patch_from_entries(entries: tuple[ProfileEntry, ...]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for entry in entries:
        if entry.recommended == OPERATOR_CHOICE or entry.recommended == "bundled defaults":
            continue
        _set_nested(patch, entry.path, entry.recommended)
    return patch


def greenfield_curated_patch() -> dict[str, Any]:
    """Nested dict patch for sw-configure write-draft — curated tier only."""
    return patch_from_entries(curated_entries())


def greenfield_posture_patch() -> dict[str, Any]:
    """Posture subset used by effective_config_gen and legacy callers."""
    posture_roots = frozenset({"orchestration", "delegation", "planning", "deliver", "inefficiency", "execute"})
    entries = tuple(
        entry
        for entry in curated_entries()
        if entry.path[0] in posture_roots and entry.recommended not in (OPERATOR_CHOICE, "bundled defaults")
    )
    return patch_from_entries(entries)


def leaf_get(doc: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = doc
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            raise KeyError(".".join(path))
        cur = cur[key]
    return cur


def leaf_get_optional(doc: dict[str, Any], path: tuple[str, ...]) -> Any | None:
    cur: Any = doc
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def dotted_path(path: tuple[str, ...]) -> str:
    return ".".join(path)


def repo_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return start


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected object at {path}")
    return data


def resolve_node(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        parts = ref[2:].split("/")
        cur: Any = schema
        for part in parts:
            if not isinstance(cur, dict):
                break
            cur = cur.get(part)
        if isinstance(cur, dict):
            merged = dict(cur)
            merged.update({k: v for k, v in node.items() if k != "$ref"})
            return merged
    return node


def schema_node_at(schema: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any] | None:
    node: dict[str, Any] = schema
    for key in path:
        node = resolve_node(schema, node)
        props = node.get("properties")
        if not isinstance(props, dict) or key not in props:
            return None
        child = props[key]
        if not isinstance(child, dict):
            return None
        node = child
    return resolve_node(schema, node)


def schema_default_at(schema: dict[str, Any], path: tuple[str, ...]) -> Any | None:
    node = schema_node_at(schema, path)
    if node is None:
        return None
    return node.get("default")


def schema_deprecated_replacement(schema: dict[str, Any], path: tuple[str, ...]) -> str | None:
    node = schema_node_at(schema, path)
    if node is None or node.get("deprecated") is not True:
        return None
    description = str(node.get("description") or "")
    for marker in ("Prefer ", "prefer "):
        if marker in description:
            segment = description.split(marker, 1)[1]
            for stop in (".", ";", ","):
                if stop in segment:
                    segment = segment.split(stop, 1)[0]
            return segment.strip()
    parent = path[0]
    if parent == "memory" and path[-1] == "tokenEnv":
        return "memory.credentialRef"
    if parent == "host" and path[-1] == "tokenEnv":
        return "host.credentialRef"
    return None


def path_exists_in_schema(schema: dict[str, Any], path: tuple[str, ...]) -> bool:
    if not path:
        return True
    node: dict[str, Any] = schema
    for index, key in enumerate(path):
        node = resolve_node(schema, node)
        props = node.get("properties")
        if isinstance(props, dict) and key in props:
            child = props[key]
            node = resolve_node(schema, child if isinstance(child, dict) else {})
            continue
        additional = node.get("additionalProperties")
        if index == len(path) - 1 and additional is not False:
            return True
        return False
    return True


def validate_profile_schema_paths(root: Path) -> list[str]:
    schema = load_json(root / SCHEMA_REL)
    missing = [dotted_path(entry.path) for entry in _PROFILE_ENTRIES if not path_exists_in_schema(schema, entry.path)]
    return missing


def load_workflow_config(root: Path) -> dict[str, Any]:
    from shipwright_paths import load_workflow_config as _load_workflow_config

    return _load_workflow_config(root)
def classify_entry(
    entry: ProfileEntry,
    config: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    path = entry.path
    dotted = dotted_path(path)
    schema_default = schema_default_at(schema, path)
    replacement = schema_deprecated_replacement(schema, path)
    actual = leaf_get_optional(config, path)

    if actual is not None and replacement is not None:
        return {
            "path": dotted,
            "tier": entry.tier,
            "status": "deprecated",
            "recommended": entry.recommended,
            "actual": actual,
            "schemaDefault": schema_default,
            "replacement": replacement,
            "note": entry.note,
        }

    if actual is not None:
        return {
            "path": dotted,
            "tier": entry.tier,
            "status": "present",
            "recommended": entry.recommended,
            "actual": actual,
            "schemaDefault": schema_default,
            "replacement": None,
            "note": entry.note,
        }

    if entry.recommended == OPERATOR_CHOICE:
        status: Status = "unset"
    elif schema_default is not None and entry.recommended != "bundled defaults" and schema_default == entry.recommended:
        status = "defaulted"
    elif schema_default is not None and entry.recommended == schema_default:
        status = "defaulted"
    else:
        status = "unset"

    return {
        "path": dotted,
        "tier": entry.tier,
        "status": status,
        "recommended": entry.recommended,
        "actual": None,
        "schemaDefault": schema_default,
        "replacement": replacement,
        "note": entry.note,
    }


def classify_profile(root: Path, config: dict[str, Any] | None = None) -> dict[str, Any]:
    schema_path = root / SCHEMA_REL
    schema = load_json(schema_path)
    cfg = config if config is not None else load_workflow_config(root)
    rows = [classify_entry(entry, cfg, schema) for entry in _PROFILE_ENTRIES]
    missing_paths = validate_profile_schema_paths(root)
    example_path = root / EXAMPLE_CONFIG_REL
    return {
        "verdict": "pass" if not missing_paths else "fail",
        "exampleConfigPath": EXAMPLE_CONFIG_REL.as_posix(),
        "exampleConfigExists": example_path.is_file(),
        "rows": rows,
        "missingSchemaPaths": missing_paths,
    }


# --- Interview priority tiers + consent reuse (PRD 342 R26/R27) -----------------

PRIORITY_ONE_SCHEMA_KEYS: tuple[str, ...] = (
    "host",
    "planning",
    "memory",
    "worktree",
    "review",
)
INTERVIEW_PRIORITY_DEFAULT = 2
_SCHEMA_PRIORITY_FIELD = "x-sw-interviewPriority"
_SCHEMA_PRIORITY_DEFAULT_FIELD = "x-sw-interviewPriorityDefault"
_SCHEMA_PRIORITY_ONE_FIELD = "x-sw-interviewPriorityOneKeys"


def load_config_schema(root: Path) -> dict[str, Any]:
    return load_json(root / SCHEMA_REL)


def interview_priority_default(schema: dict[str, Any] | None = None) -> int:
    """New schema keys default to priority two (R26)."""
    if isinstance(schema, dict):
        raw = schema.get(_SCHEMA_PRIORITY_DEFAULT_FIELD)
        if isinstance(raw, int):
            return raw
    return INTERVIEW_PRIORITY_DEFAULT


def priority_one_keys_from_schema(schema: dict[str, Any]) -> tuple[str, ...]:
    declared = schema.get(_SCHEMA_PRIORITY_ONE_FIELD)
    if isinstance(declared, list) and all(isinstance(item, str) for item in declared):
        return tuple(declared)
    return PRIORITY_ONE_SCHEMA_KEYS


def interview_priority_for_key(schema: dict[str, Any], key: str) -> int:
    """Derive a top-level key's interview priority from the schema key set (R26)."""
    props = schema.get("properties")
    if not isinstance(props, dict):
        return interview_priority_default(schema)
    node = props.get(key)
    if isinstance(node, dict):
        raw = node.get(_SCHEMA_PRIORITY_FIELD)
        if isinstance(raw, int):
            return raw
    if key in priority_one_keys_from_schema(schema):
        return 1
    return interview_priority_default(schema)


def derive_interview_priorities(schema: dict[str, Any]) -> dict[str, Any]:
    """Partition schema top-level keys into priority-one (inline) and priority-two (disclosure)."""
    props = schema.get("properties")
    if not isinstance(props, dict):
        return {
            "priorityOne": [],
            "priorityTwo": [],
            "defaultPriority": interview_priority_default(schema),
            "progressiveDisclosure": True,
        }
    priority_one: list[str] = []
    priority_two: list[str] = []
    for key in props:
        if key.startswith("$"):
            continue
        tier = interview_priority_for_key(schema, key)
        if tier <= 1:
            priority_one.append(key)
        else:
            priority_two.append(key)
    return {
        "priorityOne": priority_one,
        "priorityTwo": priority_two,
        "defaultPriority": interview_priority_default(schema),
        "progressiveDisclosure": True,
        "inlinePriorityOne": True,
    }


def interview_plan_consent(*, confirmed: bool) -> dict[str, Any]:
    """Plan consent gate — reused by the priority-zero interview (R27)."""
    if not confirmed:
        return {
            "gate": "plan",
            "verdict": "confirm-required",
            "consented": False,
            "message": "Interview plan requires explicit consent before apply.",
        }
    return {"gate": "plan", "verdict": "pass", "consented": True}


def interview_apply_consent(*, confirmed: bool) -> dict[str, Any]:
    """Apply consent gate — reused by the priority-zero interview (R27)."""
    if not confirmed:
        return {
            "gate": "apply",
            "verdict": "confirm-required",
            "consented": False,
            "message": "Interview apply requires --confirm; nothing written.",
        }
    return {"gate": "apply", "verdict": "pass", "consented": True}


def interview_reuse_bundle(
    root: Path,
    *,
    config: dict[str, Any] | None = None,
    plan_confirmed: bool = False,
    apply_confirmed: bool = False,
) -> dict[str, Any]:
    """Reuse findings-report inputs, curated-profile classification, and consent gates (R27)."""
    cfg = config if config is not None else load_workflow_config(root)
    profile = classify_profile(root, config=cfg)
    schema = load_config_schema(root)
    return {
        "engine": "existing-init-infrastructure",
        "profileClassification": profile,
        "curatedProfileChoice": {
            "source": "init_profile_report.classify_profile",
            "verdict": profile.get("verdict"),
            "rowCount": len(profile.get("rows") or []),
        },
        "priorities": derive_interview_priorities(schema),
        "planConsent": interview_plan_consent(confirmed=plan_confirmed),
        "applyConsent": interview_apply_consent(confirmed=apply_confirmed),
    }


def render_classification_markdown(report: dict[str, Any]) -> str:
    lines = [
        "### Curated greenfield profile",
        "",
        f"Annotated reference: `{report.get('exampleConfigPath')}`",
        "",
        "| Path | Tier | Status | Recommended | Actual | Replacement |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in report.get("rows", []):
        actual = row.get("actual")
        actual_cell = "—" if actual is None else json.dumps(actual)
        replacement = row.get("replacement") or "—"
        recommended = row.get("recommended")
        if recommended == OPERATOR_CHOICE:
            rec_cell = "operator choice"
        elif recommended == "bundled defaults":
            rec_cell = "bundled defaults"
        else:
            rec_cell = json.dumps(recommended)
        lines.append(
            f"| `{row['path']}` | {row['tier']} | {row['status']} | {rec_cell} | {actual_cell} | {replacement} |"
        )
    lines.append("")
    return "\n".join(lines)


def cmd_list(_: argparse.Namespace) -> int:
    payload = {
        "verdict": "pass",
        "curated": [
            {"path": dotted_path(e.path), "recommended": e.recommended, "tier": e.tier, "note": e.note}
            for e in curated_entries()
        ],
        "advanced": [
            {"path": dotted_path(e.path), "recommended": e.recommended, "tier": e.tier, "note": e.note}
            for e in advanced_entries()
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    root = repo_root(Path(args.root))
    config: dict[str, Any] | None = None
    if args.config:
        config = load_json(Path(args.config))
    report = classify_profile(root, config=config)
    if args.markdown:
        print(render_classification_markdown(report))
    else:
        print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "pass" else 1


def cmd_validate_schema(args: argparse.Namespace) -> int:
    root = repo_root(Path(args.root))
    missing = validate_profile_schema_paths(root)
    payload = {"verdict": "pass" if not missing else "fail", "missingSchemaPaths": missing}
    print(json.dumps(payload, indent=2))
    return 0 if not missing else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Curated greenfield profile report")
    parser.add_argument("command", choices=["list", "classify", "validate-schema"])
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "classify":
        return cmd_classify(args)
    if args.command == "validate-schema":
        return cmd_validate_schema(args)
    return 2


if __name__ == "__main__":
    run_module_main(main)
