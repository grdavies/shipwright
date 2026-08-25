#!/usr/bin/env python3
"""Effective-config + upgrade manifest generator (PRD 279 R13–R15 / gap-329)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from init_posture_defaults import greenfield_posture_patch

EFFECTIVE_CONFIG_REL = Path("core/sw-reference/generated/effective-config.json")
GENERATED_DIR_REL = Path("core/sw-reference/generated")
CONFIG_GUIDE_REL = Path("docs/guides/configuration.md")
SCHEMA_REL = Path("core/sw-reference/config.schema.json")
VERSION_REL = Path("version.txt")
MARKER_BEGIN = "<!-- effective-config:begin generated (scripts/effective_config_gen.py) -->"
MARKER_END = "<!-- effective-config:end generated -->"
X_EFFECTIVE = "x-effectiveConfig"
LEAF_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "null"})


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


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))
    sys.exit(code)


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected object at {path}")
    return data


def shipwright_version(root: Path) -> str:
    path = root / VERSION_REL
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return "0.0.0"


def schema_version(schema: dict[str, Any]) -> str:
    schema_id = str(schema.get("$id") or "")
    match = re.search(r"/([^/]+)$", schema_id)
    return match.group(1) if match else "config.schema.json"


def flatten_patch(doc: dict[str, Any], prefix: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in doc.items():
        path = (*prefix, key)
        dotted = ".".join(path)
        if isinstance(value, dict) and value and not any(k in value for k in ("type", "default", "$ref")):
            out.update(flatten_patch(value, path))
        else:
            out[dotted] = value
    return out


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


def effective_meta(node: dict[str, Any]) -> dict[str, Any]:
    raw = node.get(X_EFFECTIVE)
    return raw if isinstance(raw, dict) else {}


def build_setting_record(
    node: dict[str, Any],
    *,
    schema_default: Any,
    greenfield_overrides: dict[str, Any],
    dotted: str,
) -> dict[str, Any]:
    meta = effective_meta(node)
    greenfield = meta.get("greenfieldDefault")
    if greenfield is None and dotted in greenfield_overrides:
        greenfield = greenfield_overrides[dotted]
    if greenfield is None:
        greenfield = schema_default

    migration = meta.get("migrationDefault")
    if migration is None:
        migration = greenfield

    runtime_fallback = meta.get("runtimeFallback")
    if runtime_fallback is None:
        runtime_fallback = schema_default if schema_default is not None else greenfield

    deprecated_since = meta.get("deprecatedSince")
    if deprecated_since is None and node.get("deprecated") is True:
        deprecated_since = "legacy"

    removed_in = meta.get("removedIn")

    return {
        "schemaDefault": schema_default,
        "greenfieldDefault": greenfield,
        "migrationDefault": migration,
        "runtimeFallback": runtime_fallback,
        "deprecatedSince": deprecated_since,
        "removedIn": removed_in,
    }


def walk_properties(
    schema: dict[str, Any],
    node: dict[str, Any],
    *,
    prefix: tuple[str, ...],
    settings: dict[str, dict[str, Any]],
    greenfield_overrides: dict[str, Any],
) -> None:
    node = resolve_node(schema, node)
    props = node.get("properties")
    if not isinstance(props, dict):
        return

    for key, raw_child in props.items():
        child = resolve_node(schema, raw_child if isinstance(raw_child, dict) else {})
        path = (*prefix, key)
        dotted = ".".join(path)
        child_type = child.get("type")
        types = child_type if isinstance(child_type, list) else [child_type]
        types = [t for t in types if t != "null"]

        if "object" in types and isinstance(child.get("properties"), dict):
            walk_properties(schema, child, prefix=path, settings=settings, greenfield_overrides=greenfield_overrides)
            continue

        if not types or not any(t in LEAF_TYPES for t in types):
            continue

        schema_default = child.get("default")
        if schema_default is None and dotted not in greenfield_overrides and X_EFFECTIVE not in child:
            if child.get("deprecated") is not True:
                continue

        settings[dotted] = build_setting_record(
            child,
            schema_default=schema_default,
            greenfield_overrides=greenfield_overrides,
            dotted=dotted,
        )


def _load_existing_effective_config(root: Path) -> dict[str, Any] | None:
    path = root / EFFECTIVE_CONFIG_REL
    if not path.is_file():
        return None
    try:
        return load_json(path)
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def stabilize_generated_at(doc: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """Reuse prior generatedAt when payload is unchanged (PR #1008 regen storm).

    ``check_drift`` already ignores ``generatedAt``; writes must too — otherwise
    release-dist-regen commits a timestamp-only diff, pushes, and re-triggers forever.
    """
    if not previous:
        return doc
    prior_stamp = previous.get("generatedAt")
    if not isinstance(prior_stamp, str) or not prior_stamp.strip():
        return doc
    if (
        previous.get("settings") == doc.get("settings")
        and previous.get("schemaVersion") == doc.get("schemaVersion")
        and previous.get("shipwrightVersion") == doc.get("shipwrightVersion")
    ):
        stabilized = dict(doc)
        stabilized["generatedAt"] = prior_stamp
        return stabilized
    return doc


def build_effective_config(root: Path) -> dict[str, Any]:
    schema_path = root / SCHEMA_REL
    schema = load_json(schema_path)
    greenfield_overrides = flatten_patch(greenfield_posture_patch())
    settings: dict[str, dict[str, Any]] = {}
    walk_properties(schema, schema, prefix=(), settings=settings, greenfield_overrides=greenfield_overrides)
    doc = {
        "schemaVersion": schema_version(schema),
        "shipwrightVersion": shipwright_version(root),
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "generator": "scripts/effective_config_gen.py",
        "settings": dict(sorted(settings.items())),
    }
    return stabilize_generated_at(doc, _load_existing_effective_config(root))


def render_markdown_fragment(doc: dict[str, Any]) -> str:
    lines = [
        "## Effective configuration (generated)",
        "",
        "Machine-readable defaults for workflow settings. Regenerate with:",
        "",
        "```bash",
        "python3 scripts/effective_config_gen.py generate --write",
        "python3 scripts/effective_config_gen.py project-docs --write",
        "```",
        "",
        f"Shipwright `{doc.get('shipwrightVersion')}` · schema `{doc.get('schemaVersion')}`",
        "",
        "| Setting | Schema default | Greenfield | Migration | Runtime fallback | Deprecated | Removed |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, row in doc.get("settings", {}).items():
        lines.append(
            "| `{key}` | `{schema}` | `{green}` | `{mig}` | `{rt}` | `{dep}` | `{rem}` |".format(
                key=key,
                schema=_md_cell(row.get("schemaDefault")),
                green=_md_cell(row.get("greenfieldDefault")),
                mig=_md_cell(row.get("migrationDefault")),
                rt=_md_cell(row.get("runtimeFallback")),
                dep=_md_cell(row.get("deprecatedSince")),
                rem=_md_cell(row.get("removedIn")),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _md_cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.replace("|", "\\|").replace("`", "\\`")
    return json.dumps(value, ensure_ascii=False).replace("|", "\\|")


def patch_marked_region(text: str, generated: str) -> str:
    pattern = re.compile(re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END), re.DOTALL)
    block = f"{MARKER_BEGIN}\n{generated.rstrip()}\n{MARKER_END}"
    if pattern.search(text):
        return pattern.sub(block, text, count=1)
    anchor = "## Configuration reference index"
    if anchor in text:
        return text.replace(anchor, f"{block}\n\n{anchor}", 1)
    return text.rstrip() + "\n\n" + block + "\n"


def diff_settings(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, Any]:
    prev_settings = (previous or {}).get("settings") or {}
    cur_settings = current.get("settings") or {}
    new_settings = sorted(set(cur_settings) - set(prev_settings))
    removed_settings = sorted(set(prev_settings) - set(cur_settings))
    changed_defaults: list[dict[str, Any]] = []
    deprecated: list[dict[str, Any]] = []
    for key, row in cur_settings.items():
        prev_row = prev_settings.get(key)
        if prev_row is None:
            continue
        for field in ("schemaDefault", "greenfieldDefault", "migrationDefault", "runtimeFallback"):
            if prev_row.get(field) != row.get(field):
                changed_defaults.append(
                    {
                        "setting": key,
                        "field": field,
                        "from": prev_row.get(field),
                        "to": row.get(field),
                    }
                )
                break
        if row.get("deprecatedSince") and not prev_row.get("deprecatedSince"):
            deprecated.append({"setting": key, "since": row.get("deprecatedSince"), "removedIn": row.get("removedIn")})
    return {
        "newSettings": new_settings,
        "removedSettings": removed_settings,
        "changedDefaults": changed_defaults,
        "deprecated": deprecated,
        "schemaMigrations": [],
        "newDurableStateShapes": [],
        "packageCompatibility": {"shipwright": current.get("shipwrightVersion")},
        "kernelGraphVersionChanges": [],
        "requiredManualActions": [],
        "rollbackConcerns": [],
    }


def _load_existing_upgrade_manifest(root: Path, version: str) -> dict[str, Any] | None:
    path = root / GENERATED_DIR_REL / f"upgrade-manifest-{version}.json"
    if not path.is_file():
        return None
    try:
        return load_json(path)
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def stabilize_manifest_generated_at(
    manifest: dict[str, Any], previous_manifest: dict[str, Any] | None
) -> dict[str, Any]:
    """Preserve upgrade-manifest generatedAt when only the stamp would change."""
    if not previous_manifest:
        return manifest
    prior_stamp = previous_manifest.get("generatedAt")
    if not isinstance(prior_stamp, str) or not prior_stamp.strip():
        return manifest
    comparable_keys = (
        "version",
        "previousVersion",
        "generator",
        "newSettings",
        "removedSettings",
        "changedDefaults",
        "deprecated",
        "schemaMigrations",
        "newDurableStateShapes",
        "packageCompatibility",
        "kernelGraphVersionChanges",
        "requiredManualActions",
        "rollbackConcerns",
    )
    if all(previous_manifest.get(k) == manifest.get(k) for k in comparable_keys):
        stabilized = dict(manifest)
        stabilized["generatedAt"] = prior_stamp
        return stabilized
    return manifest


def build_upgrade_manifest(root: Path, *, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    current = build_effective_config(root)
    if previous is None:
        previous = _load_existing_effective_config(root)
    diff = diff_settings(previous, current)
    version = str(current.get("shipwrightVersion") or "0.0.0")
    manifest = {
        "version": current.get("shipwrightVersion"),
        "previousVersion": (previous or {}).get("shipwrightVersion"),
        "generatedAt": current.get("generatedAt"),
        "generator": "scripts/effective_config_gen.py",
        **diff,
    }
    return stabilize_manifest_generated_at(manifest, _load_existing_upgrade_manifest(root, version))


def check_drift(root: Path) -> list[str]:
    errors: list[str] = []
    expected = build_effective_config(root)
    config_path = root / EFFECTIVE_CONFIG_REL
    if not config_path.is_file():
        errors.append("missing-effective-config")
        return errors

    committed = load_json(config_path)
    if committed.get("settings") != expected.get("settings"):
        errors.append("effective-config-settings-drift")
    if committed.get("schemaVersion") != expected.get("schemaVersion"):
        errors.append("effective-config-schema-version-drift")

    guide_path = root / CONFIG_GUIDE_REL
    if guide_path.is_file():
        expected_fragment = render_markdown_fragment(expected)
        text = guide_path.read_text(encoding="utf-8")
        if MARKER_BEGIN not in text or MARKER_END not in text:
            errors.append("configuration-guide-missing-markers")
        else:
            pattern = re.compile(re.escape(MARKER_BEGIN) + r"(.*?)" + re.escape(MARKER_END), re.DOTALL)
            match = pattern.search(text)
            actual = match.group(1).strip() if match else ""
            if actual != expected_fragment.strip():
                errors.append("configuration-guide-projection-drift")
    else:
        errors.append("configuration-guide-missing")

    return errors


def _run_generate(root: Path, *, write: bool) -> dict[str, Any]:
    doc = build_effective_config(root)
    if write:
        out_path = root / EFFECTIVE_CONFIG_REL
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "verdict": "ok",
        "command": "generate",
        "write": write,
        "settingCount": len(doc.get("settings") or {}),
    }


def cmd_generate(root: Path, *, write: bool) -> int:
    emit(_run_generate(root, write=write))


def _run_manifest(root: Path, *, write: bool) -> dict[str, Any]:
    manifest = build_upgrade_manifest(root)
    if write:
        version = str(manifest.get("version") or "0.0.0")
        out_path = root / GENERATED_DIR_REL / f"upgrade-manifest-{version}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"verdict": "ok", "command": "manifest", "write": write, "manifest": manifest}


def cmd_manifest(root: Path, *, write: bool) -> int:
    emit(_run_manifest(root, write=write))


def _run_project_docs(root: Path, *, write: bool) -> dict[str, Any]:
    doc = build_effective_config(root)
    fragment = render_markdown_fragment(doc)
    guide_path = root / CONFIG_GUIDE_REL
    if not guide_path.is_file():
        return {"verdict": "fail", "error": "configuration-guide-missing"}
    updated = patch_marked_region(guide_path.read_text(encoding="utf-8"), fragment)
    if write:
        guide_path.write_text(updated, encoding="utf-8")
    return {"verdict": "ok", "command": "project-docs", "write": write, "bytes": len(fragment)}


def cmd_project_docs(root: Path, *, write: bool) -> int:
    result = _run_project_docs(root, write=write)
    emit(result, 0 if result.get("verdict") == "ok" else 2)


def cmd_check(root: Path) -> int:
    errors = check_drift(root)
    if errors:
        emit({"verdict": "fail", "errors": errors}, 1)
    emit({"verdict": "ok", "command": "check"})


def cmd_all(root: Path, *, write: bool) -> int:
    for runner in (_run_generate, _run_manifest, _run_project_docs):
        result = runner(root, write=write)
        if result.get("verdict") != "ok":
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 2
    print(json.dumps({"verdict": "ok", "command": "all", "write": write}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate effective-config and upgrade manifests.")
    parser.add_argument("--root", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("generate", "manifest", "project-docs"):
        p = sub.add_parser(name)
        p.add_argument("--write", action="store_true")

    sub.add_parser("check")
    all_p = sub.add_parser("all")
    all_p.add_argument("--write", action="store_true")

    args = parser.parse_args(argv)
    root = repo_root(args.root)

    if args.command == "generate":
        return cmd_generate(root, write=bool(getattr(args, "write", False)))
    if args.command == "manifest":
        return cmd_manifest(root, write=bool(getattr(args, "write", False)))
    if args.command == "project-docs":
        return cmd_project_docs(root, write=bool(getattr(args, "write", False)))
    if args.command == "check":
        return cmd_check(root)
    if args.command == "all":
        return cmd_all(root, write=bool(getattr(args, "write", False)))
    emit({"verdict": "fail", "error": f"unknown command {args.command}"}, 2)
    return 2


if __name__ == "__main__":
    run_module_main(main)
