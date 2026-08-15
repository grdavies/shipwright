#!/usr/bin/env python3
"""PRD 270 R8 — registry-sourced capability documentation for planning/issue providers."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from planning.provider_conformance import load_conformance_record

REGISTRY_REL = Path("core/sw-reference/capability-registry.json")
KERNEL_CLASSIFICATION_REL = Path("core/sw-reference/kernel-classification.json")
MODEL_ROUTING_REL = Path("core/sw-reference/model-routing.defaults.json")
MATRICES_JSON_REL = Path("core/sw-reference/capability-family-matrices.json")
MATRICES_MD_REL = Path("core/sw-reference/capability-family-matrices.md")
ROOT_CAPABILITIES_REL = Path("CAPABILITIES.md")
ISSUES_CAPABILITIES_REL = Path("core/providers/issues/CAPABILITIES.md")
GENERATED_PATHS = (
    ROOT_CAPABILITIES_REL,
    ISSUES_CAPABILITIES_REL,
    MATRICES_JSON_REL,
    MATRICES_MD_REL,
)
GENERATOR_BANNER = (
    "Generated from `core/sw-reference/capability-registry.json` via "
    "`scripts/capability_docs.py` — do not edit by hand."
)
MATRICES_BANNER = (
    "Generated from `core/sw-reference/kernel-classification.json` and "
    "`core/sw-reference/capability-registry.json` via `scripts/capability_docs.py` "
    "— do not edit by hand."
)
MARKER_BEGIN = "<!-- capability-docs:begin registry-derived -->"
MARKER_END = "<!-- capability-docs:end registry-derived -->"

GITLAB_DEFERRED_NOTICE = """> **Deferred / fail-closed — `gitlab-issues` (PRD 057 R7 / D1, gap-039).**
> The GitLab Issues provider is **not shipped**: no live `planning_gitlab_client.py`
> adapter is wired into `issues_lib._live_backend` for the standard write path.
> Selecting it for a live issue-store backend **fails closed** with the operator
> message:
>
> > issue provider `gitlab-issues` is deferred (fail-closed): no live adapter is
> > shipped in this release. Select a shipped provider (`github-issues` or `jira`),
> > or use the file-store fallback. A follow-up unit will implement the live
> > `planning_gitlab_client.py` adapter and re-add it to the shipped set
> > (PRD 057 R7 / D1; gap-039).
>
> **Follow-up unit:** a dedicated unit will implement the live GitLab Issues
> adapter at parity and re-add `gitlab-issues` to the shipped issues set.
> Until then, config that names `gitlab-issues` is *recognized* (kept in
> `ISSUES_PROVIDERS` for validation) but resolves to the
> `issues-provider-not-shipped` fallback rather than an advertised round-trip."""


def repo_root(start: Path | None = None) -> Path:
    start = start or SCRIPT_DIR
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return cur.parent


def load_registry(root: Path) -> dict[str, Any]:
    path = root / REGISTRY_REL
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "families" not in payload:
        raise ValueError(f"invalid capability registry: {path}")
    return payload


def load_kernel_classification(root: Path) -> dict[str, Any]:
    path = root / KERNEL_CLASSIFICATION_REL
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid kernel classification: {path}")
    return payload


def _family_sources(classification: dict[str, Any]) -> dict[str, Any]:
    sources = classification.get("capabilityFamilySources")
    if not isinstance(sources, dict):
        raise ValueError("kernel-classification.json missing capabilityFamilySources")
    return sources


def _load_model_routing(root: Path, sources: dict[str, Any]) -> dict[str, Any]:
    rel = Path(str(sources.get("modelTiers", {}).get("routingDefaultsPath") or MODEL_ROUTING_REL))
    path = root / rel
    payload = json.loads(path.read_text(encoding="utf-8"))
    routing = payload.get("routing")
    return routing if isinstance(routing, dict) else {}


def _tier_routing_counts(routing: dict[str, Any], tier_order: list[str]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {
        tier: {"commands": 0, "agents": 0, "skills": 0} for tier in tier_order
    }
    for surface, key in (("commands", "commands"), ("agents", "agents"), ("skills", "skills")):
        block = routing.get(surface)
        if not isinstance(block, dict):
            continue
        for _name, tier in block.items():
            tier_name = str(tier)
            if tier_name == "inherit":
                continue
            if tier_name not in counts:
                counts[tier_name] = {"commands": 0, "agents": 0, "skills": 0}
            counts[tier_name][key] += 1
    return counts


def _command_catalog_rows(classification: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in classification.get("planPolicySteps") or []:
        if not isinstance(item, dict):
            continue
        step_id = item.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            continue
        rows.append(
            {
                "id": step_id,
                "phaseType": str(item.get("phaseType") or ""),
                "required": bool(item.get("required")),
            }
        )
    rows.sort(key=lambda row: (row["phaseType"], row["id"]))
    return rows


def _workflow_template_rows(root: Path, sources: dict[str, Any]) -> list[dict[str, Any]]:
    block = sources.get("workflowTemplateVersions") or {}
    library_version = int(block.get("libraryVersion") or 1)
    library_root = Path(str(block.get("libraryRoot") or ".sw/workflows"))
    templates: list[dict[str, Any]] = []
    root_path = root / library_root
    if root_path.is_dir():
        for path in sorted(root_path.glob("*.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(document, dict):
                continue
            templates.append(
                {
                    "name": str(document.get("name") or path.stem),
                    "libraryVersion": int(document.get("libraryVersion") or library_version),
                    "path": str(path.relative_to(root)),
                }
            )
    return templates


def collect_family_matrices(root: Path) -> dict[str, Any]:
    classification = load_kernel_classification(root)
    registry = load_registry(root)
    sources = _family_sources(classification)
    tier_block = sources.get("modelTiers") or {}
    tier_order = [str(t) for t in (tier_block.get("tierOrder") or [])]
    routing = _load_model_routing(root, sources)
    tier_counts = _tier_routing_counts(routing, tier_order)
    node_kinds = [
        {
            "id": str(row.get("id") or ""),
            "shadowPolicy": str(row.get("shadowPolicy") or ""),
        }
        for row in (sources.get("graphNodeKinds") or {}).get("kinds") or []
        if isinstance(row, dict) and row.get("id")
    ]
    artifact_schemas = [
        {
            "id": str(row.get("id") or ""),
            "title": str(row.get("title") or ""),
            "schemaPath": str(row.get("schemaPath") or ""),
            "apiVersion": str(row.get("apiVersion") or ""),
        }
        for row in (sources.get("artifactSchemas") or {}).get("schemas") or []
        if isinstance(row, dict) and row.get("id")
    ]
    registry_families = {
        family_id: [str(row.get("id") or "") for row in _family_rows(registry, family_id)]
        for family_id in sorted((registry.get("families") or {}).keys())
    }
    return {
        "version": 1,
        "generator": "scripts/capability_docs.py",
        "families": {
            "modelTiers": {
                "tierOrder": tier_order,
                "routingCounts": tier_counts,
            },
            "graphNodeKinds": node_kinds,
            "artifactSchemas": artifact_schemas,
            "commandCatalog": _command_catalog_rows(classification),
            "workflowTemplateVersions": {
                "libraryVersion": int(
                    (sources.get("workflowTemplateVersions") or {}).get("libraryVersion") or 1
                ),
                "libraryRoot": str(
                    (sources.get("workflowTemplateVersions") or {}).get("libraryRoot")
                    or ".sw/workflows"
                ),
                "templates": _workflow_template_rows(root, sources),
            },
            "registryFamilies": registry_families,
        },
    }


def render_family_matrices_md(matrices: dict[str, Any]) -> str:
    families = matrices.get("families") or {}
    lines = [
        "# Capability family matrices",
        "",
        "Documentation-only projection of kernel and registry capability families (PRD 270 R8).",
        MATRICES_BANNER,
        "",
        "## Model tiers",
        "",
        "| Tier | Commands | Agents | Skills |",
        "| --- | ---: | ---: | ---: |",
    ]
    tier_block = families.get("modelTiers") or {}
    counts = tier_block.get("routingCounts") or {}
    for tier in tier_block.get("tierOrder") or []:
        row = counts.get(tier) or {}
        lines.append(
            f"| `{tier}` | {int(row.get('commands') or 0)} | "
            f"{int(row.get('agents') or 0)} | {int(row.get('skills') or 0)} |"
        )
    lines.extend(
        [
            "",
            "## Graph node kinds",
            "",
            "| Kind | Shadow policy |",
            "| --- | --- |",
        ]
    )
    for row in families.get("graphNodeKinds") or []:
        lines.append(f"| `{row['id']}` | {row.get('shadowPolicy') or '—'} |")
    lines.extend(
        [
            "",
            "## Artifact schemas",
            "",
            "| Schema | API version | Path |",
            "| --- | --- | --- |",
        ]
    )
    for row in families.get("artifactSchemas") or []:
        lines.append(
            f"| `{row['id']}` | `{row.get('apiVersion') or '—'}` | `{row.get('schemaPath')}` |"
        )
    lines.extend(
        [
            "",
            "## Command catalog",
            "",
            "| Step | Phase type | Required |",
            "| --- | --- | --- |",
        ]
    )
    for row in families.get("commandCatalog") or []:
        required = "yes" if row.get("required") else "no"
        lines.append(f"| `{row['id']}` | `{row.get('phaseType')}` | {required} |")
    template_block = families.get("workflowTemplateVersions") or {}
    lines.extend(
        [
            "",
            "## Workflow template versions",
            "",
            f"Library version: **{int(template_block.get('libraryVersion') or 1)}**",
            f" (`{template_block.get('libraryRoot')}`).",
            "",
            "| Template | Library version | Path |",
            "| --- | ---: | --- |",
        ]
    )
    templates = template_block.get("templates") or []
    if templates:
        for row in templates:
            lines.append(
                f"| `{row.get('name')}` | {int(row.get('libraryVersion') or 1)} | `{row.get('path')}` |"
            )
    else:
        lines.append("| — | — | no checked-in templates |")
    lines.extend(
        [
            "",
            "## Registry families (planning + issues)",
            "",
            "See `CAPABILITIES.md` for shipped/deferred rows derived from `capability-registry.json`.",
            "",
        ]
    )
    for family_id, row_ids in sorted((families.get("registryFamilies") or {}).items()):
        joined = ", ".join(f"`{row_id}`" for row_id in row_ids)
        lines.append(f"- `{family_id}`: {joined}")
    lines.append("")
    return "\n".join(lines)


def validate_matrix_sources(root: Path, classification: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    sources = _family_sources(classification)
    routing_path = root / str(
        (sources.get("modelTiers") or {}).get("routingDefaultsPath") or MODEL_ROUTING_REL
    )
    if not routing_path.is_file():
        errors.append(f"missing model tier routing defaults: {routing_path.relative_to(root)}")
    for row in (sources.get("artifactSchemas") or {}).get("schemas") or []:
        if not isinstance(row, dict):
            continue
        schema_path = root / str(row.get("schemaPath") or "")
        if not schema_path.is_file():
            errors.append(f"missing artifact schema file: {schema_path.relative_to(root)}")
    catalog_source = str((sources.get("commandCatalog") or {}).get("source") or "")
    if catalog_source != "planPolicySteps":
        errors.append(
            f"commandCatalog.source must be planPolicySteps (got {catalog_source!r})"
        )
    if not _command_catalog_rows(classification):
        errors.append("command catalog is empty — planPolicySteps missing")
    return errors


def _family_rows(registry: dict[str, Any], family: str) -> list[dict[str, Any]]:
    families = registry.get("families") or {}
    block = families.get(family) or {}
    rows = block.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


def _conformance_green(root: Path, provider: str) -> bool:
    record = load_conformance_record(root, provider)
    return record.get("verdict") == "ok"


def _linear_recognized(root: Path) -> bool:
    import planning_store_facade as ps

    return "linear" in ps.ISSUES_PROVIDERS


def effective_issues_status(root: Path, row: dict[str, Any]) -> str:
    """Return shipped | deferred | recognized-not-shipped."""
    declared = str(row.get("status") or "")
    provider_id = str(row.get("id") or "")
    if declared == "deferred":
        return "deferred"
    if row.get("recognition") == "live-client-wired" and not _linear_recognized(root):
        return "deferred"
    if row.get("conformanceGated"):
        if not _conformance_green(root, provider_id):
            if provider_id == "linear" and _linear_recognized(root):
                return "recognized-not-shipped"
            return "deferred" if declared != "shipped" else "recognized-not-shipped"
        return "shipped"
    if declared == "shipped":
        return "shipped"
    return "deferred"


def derive_shipped_backends(registry: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        str(row["id"])
        for row in _family_rows(registry, "planning-store.backends")
        if str(row.get("status")) == "shipped"
    )


def derive_deferred_backends(registry: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        str(row["id"])
        for row in _family_rows(registry, "planning-store.backends")
        if str(row.get("status")) == "deferred"
    )


def derive_shipped_issues_providers(root: Path, registry: dict[str, Any]) -> frozenset[str]:
    shipped: set[str] = set()
    for row in _family_rows(registry, "issues.providers"):
        if effective_issues_status(root, row) == "shipped":
            shipped.add(str(row["id"]))
    return frozenset(shipped)


def derive_deferred_issues_providers(root: Path, registry: dict[str, Any]) -> frozenset[str]:
    deferred: set[str] = set()
    for row in _family_rows(registry, "issues.providers"):
        status = effective_issues_status(root, row)
        if status in {"deferred", "recognized-not-shipped"} and str(row.get("status")) != "shipped":
            deferred.add(str(row["id"]))
        elif status == "deferred":
            deferred.add(str(row["id"]))
    for row in _family_rows(registry, "issues.providers"):
        if str(row.get("status")) == "deferred":
            deferred.add(str(row["id"]))
    return frozenset(deferred)


def _backend_status_label(status: str) -> str:
    return status


def _issues_status_label(root: Path, row: dict[str, Any]) -> str:
    status = effective_issues_status(root, row)
    provider_id = str(row.get("id") or "")
    if status == "shipped":
        if provider_id == "none":
            return "shipped (file-store fallback)"
        return "**shipped**"
    if status == "recognized-not-shipped":
        return "recognized (not shipped)"
    deferral = row.get("deferralRef")
    if deferral:
        return f"**deferred / fail-closed** ({deferral})"
    return "**deferred / fail-closed**"


def _issues_adapter_cell(row: dict[str, Any]) -> str:
    adapter = row.get("liveAdapter")
    if adapter:
        return f"`{adapter}`"
    notes = row.get("notes")
    if notes:
        return str(notes)
    return "—"


def render_root_capabilities_md(root: Path, registry: dict[str, Any]) -> str:
    backend_lines = [
        "# Shipwright shipped capability matrix",
        "",
        "Authoritative summary of which storage backends and issue-store providers are",
        "**shipped** (wired to a live adapter) versus **deferred** (recognized but",
        "fail-closed until a follow-up unit lands the adapter).",
        GENERATOR_BANNER,
        "",
        GITLAB_DEFERRED_NOTICE,
        "",
        "## Planning-store backends",
        "",
        "| Backend | Status |",
        "| --- | --- |",
    ]
    for row in _family_rows(registry, "planning-store.backends"):
        backend_lines.append(f"| `{row['id']}` | {_backend_status_label(str(row.get('status')))} |")

    backend_lines.extend(
        [
            "",
            "## Issue-store providers",
            "",
            "| Provider | Status | Live adapter |",
            "| --- | --- | --- |",
        ]
    )
    for row in _family_rows(registry, "issues.providers"):
        if row.get("recognition") == "live-client-wired" and not _linear_recognized(root):
            continue
        backend_lines.append(
            f"| `{row['id']}` | {_issues_status_label(root, row)} | {_issues_adapter_cell(row)} |"
        )

    backend_lines.extend(
        [
            "",
            "Provider adapter specs live under `core/providers/issues/`. The neutral verb",
            "contract and per-provider degradation matrix are documented in",
            "`core/providers/issues/CAPABILITIES.md`; the deferred GitLab adapter is noted in",
            "`core/providers/issues/gitlab-issues.md`.",
            "",
        ]
    )
    return "\n".join(backend_lines)


def render_issues_registry_derived(root: Path, registry: dict[str, Any]) -> str:
    lines = [
        "### Linear recognition vs shipped (R9, R20)",
        "",
        "| State | `linear` in `ISSUES_PROVIDERS` | `linear` in derived shipped set | Behavior |",
        "| --- | --- | --- | --- |",
        "| Stub (no live client) | no | no | Config may name `linear`; doctor **refuses** enum-only stub |",
    ]
    recognized = _linear_recognized(root)
    linear_shipped = "linear" in derive_shipped_issues_providers(root, registry)
    if recognized and not linear_shipped:
        lines.append(
            "| Recognized (live client wired) | yes | no | Config validates; issue-store **falls back** to file-store |"
        )
    elif linear_shipped:
        lines.append(
            "| Shipped (post-conformance) | yes | yes | Full live round-trip after conformance + OAuth docs gate |"
        )
    else:
        lines.append(
            "| Recognized (live client wired) | no | no | Config may name `linear`; doctor **refuses** enum-only stub |"
        )
    lines.append(
        "`linear` promotion to the derived shipped set requires LCD conformance harness green **and**"
    )
    lines.append("OAuth operator-local storage documented (`core/providers/issues/linear.md` R23).")
    lines.append("")
    lines.append("### Rate-limit map (R16)")
    lines.append("")
    lines.append("| `issuesProvider` | `issues_http` profile key |")
    lines.append("| --- | --- |")
    for row in _family_rows(registry, "issues.providers"):
        profile = row.get("rateLimitProfile")
        if profile:
            lines.append(f"| `{row['id']}` | `{profile}` |")
    lines.append("")
    lines.append("Override per-provider budgets via `planning.store.requestBudget.<provider>` (request count +")
    lines.append("complexity for Linear).")
    lines.append("")
    lines.append("### Capability index entries (R16)")
    lines.append("")
    lines.append("| Provider | Index id | Source |")
    lines.append("| --- | --- | --- |")
    for row in _family_rows(registry, "issues.providers"):
        provider_id = str(row["id"])
        if provider_id == "none":
            continue
        lines.append(
            f"| `{provider_id}` | `provider.providers.issues.{provider_id}` | "
            f"`core/providers/issues/{provider_id}.md` |"
        )
    return "\n".join(lines)


def _patch_marked_region(text: str, generated: str) -> str:
    pattern = re.compile(
        re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END),
        re.DOTALL,
    )
    block = f"{MARKER_BEGIN}\n{generated.rstrip()}\n{MARKER_END}"
    if pattern.search(text):
        return pattern.sub(block, text, count=1)
    raise ValueError(f"missing capability-docs markers in target file")


def render_issues_capabilities_md(root: Path, registry: dict[str, Any]) -> str:
    path = root / ISSUES_CAPABILITIES_REL
    text = path.read_text(encoding="utf-8")
    generated = render_issues_registry_derived(root, registry)
    return _patch_marked_region(text, generated)


def validate_conformance_semantics(root: Path, registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    classification_path = root / KERNEL_CLASSIFICATION_REL
    if classification_path.is_file():
        classification = load_kernel_classification(root)
        errors.extend(validate_matrix_sources(root, classification))
    for row in _family_rows(registry, "issues.providers"):
        provider_id = str(row.get("id") or "")
        if not row.get("conformanceGated"):
            continue
        effective = effective_issues_status(root, row)
        record = load_conformance_record(root, provider_id)
        green = record.get("verdict") == "ok"
        if effective == "shipped" and not green:
            errors.append(
                f"{provider_id}: effective shipped status requires green conformance record "
                f"(got {record.get('verdict')!r})"
            )
        if str(row.get("status")) == "shipped" and row.get("conformanceGated") and not green:
            errors.append(
                f"{provider_id}: registry row is shipped+conformanceGated but conformance is not green"
            )
    expected_root = render_root_capabilities_md(root, registry)
    actual_root_path = root / ROOT_CAPABILITIES_REL
    actual_root = (
        actual_root_path.read_text(encoding="utf-8") if actual_root_path.is_file() else ""
    )
    actual_matrices_path = root / MATRICES_MD_REL
    actual_matrices = (
        actual_matrices_path.read_text(encoding="utf-8")
        if actual_matrices_path.is_file()
        else ""
    )
    if "`linear`" not in expected_root and _linear_recognized(root):
        errors.append("root CAPABILITIES.md must include linear provider row when recognized")
    elif _linear_recognized(root):
        linear_row_shipped = "`linear` | **shipped**" in expected_root or "`linear` | shipped" in expected_root
        linear_recognized_only = "`linear` | recognized (not shipped)" in expected_root
        if derive_shipped_issues_providers(root, registry) >= frozenset({"linear"}):
            if not linear_row_shipped:
                errors.append("linear: derived shipped but root docs do not render shipped")
            if "`linear`" not in actual_root:
                errors.append(
                    "linear: derived shipped but checked-in CAPABILITIES.md omits linear row"
                )
            if actual_matrices and "`linear`" not in actual_matrices:
                errors.append(
                    "linear: derived shipped but checked-in capability-family-matrices.md omits linear"
                )
        elif not linear_recognized_only and not linear_row_shipped:
            errors.append("linear: missing shipped or recognized-not-shipped rendering")
    return errors


def check_files_fresh(root: Path, registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_root = render_root_capabilities_md(root, registry)
    actual_root = (root / ROOT_CAPABILITIES_REL).read_text(encoding="utf-8")
    if actual_root != expected_root:
        errors.append(f"stale {ROOT_CAPABILITIES_REL} (run: python3 scripts/capability_docs.py generate)")

    expected_issues = render_issues_capabilities_md(root, registry)
    actual_issues = (root / ISSUES_CAPABILITIES_REL).read_text(encoding="utf-8")
    if actual_issues != expected_issues:
        errors.append(
            f"stale {ISSUES_CAPABILITIES_REL} (run: python3 scripts/capability_docs.py generate)"
        )

    matrices = collect_family_matrices(root)
    expected_json = json.dumps(matrices, indent=2, ensure_ascii=False) + "\n"
    actual_json_path = root / MATRICES_JSON_REL
    actual_json = (
        actual_json_path.read_text(encoding="utf-8")
        if actual_json_path.is_file()
        else ""
    )
    if actual_json != expected_json:
        errors.append(
            f"stale {MATRICES_JSON_REL} (run: python3 scripts/capability_docs.py generate)"
        )

    expected_md = render_family_matrices_md(matrices)
    actual_md_path = root / MATRICES_MD_REL
    actual_md = actual_md_path.read_text(encoding="utf-8") if actual_md_path.is_file() else ""
    if actual_md != expected_md:
        errors.append(
            f"stale {MATRICES_MD_REL} (run: python3 scripts/capability_docs.py generate)"
        )
    return errors


def _git_generated_paths_clean(root: Path) -> tuple[bool, str]:
    rel_paths = [str(path) for path in GENERATED_PATHS]
    completed = subprocess.run(
        ["git", "diff", "--exit-code", "--"] + rel_paths,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return True, ""
    detail = (completed.stdout or completed.stderr or "").strip()
    return False, detail or "generated capability docs differ from committed files"


def cmd_generate(root: Path) -> int:
    registry = load_registry(root)
    matrices = collect_family_matrices(root)
    (root / ROOT_CAPABILITIES_REL).write_text(
        render_root_capabilities_md(root, registry),
        encoding="utf-8",
    )
    (root / ISSUES_CAPABILITIES_REL).write_text(
        render_issues_capabilities_md(root, registry),
        encoding="utf-8",
    )
    (root / MATRICES_JSON_REL).write_text(
        json.dumps(matrices, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (root / MATRICES_MD_REL).write_text(
        render_family_matrices_md(matrices),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "verdict": "ok",
                "action": "capability-docs-generate",
                "families": sorted((matrices.get("families") or {}).keys()),
            },
            indent=2,
        )
    )
    return 0


def cmd_check(root: Path) -> int:
    registry = load_registry(root)
    errors = validate_conformance_semantics(root, registry)
    errors.extend(check_files_fresh(root, registry))
    payload = {
        "verdict": "ok" if not errors else "fail",
        "action": "capability-docs-check",
        "shippedBackends": sorted(derive_shipped_backends(registry)),
        "deferredBackends": sorted(derive_deferred_backends(registry)),
        "shippedIssuesProviders": sorted(derive_shipped_issues_providers(root, registry)),
        "deferredIssuesProviders": sorted(derive_deferred_issues_providers(root, registry)),
        "errors": errors,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not errors else 1


def cmd_regen_check(root: Path) -> int:
    """Regenerate in place and fail closed on dirty tree or semantic drift."""
    before_errors = cmd_generate(root)
    if before_errors != 0:
        return before_errors
    clean, diff_detail = _git_generated_paths_clean(root)
    semantic_errors = validate_conformance_semantics(root, load_registry(root))
    errors: list[str] = []
    if not clean:
        errors.append(
            "working tree changed after in-place capability docs regenerate "
            f"(commit generated outputs): {diff_detail}"
        )
    errors.extend(semantic_errors)
    payload = {
        "verdict": "ok" if not errors else "fail",
        "action": "capability-docs-regen-check",
        "errors": errors,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not errors else 1


def cmd_derived(root: Path) -> int:
    registry = load_registry(root)
    payload = {
        "shippedBackends": sorted(derive_shipped_backends(registry)),
        "deferredBackends": sorted(derive_deferred_backends(registry)),
        "shippedIssuesProviders": sorted(derive_shipped_issues_providers(root, registry)),
        "deferredIssuesProviders": sorted(derive_deferred_issues_providers(root, registry)),
    }
    print(json.dumps(payload, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Registry-sourced capability documentation (PRD 270 R8).")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("generate", "check", "derived", "regen-check"),
        default="check",
    )
    args = parser.parse_args(argv)
    root = repo_root()
    if args.command == "generate":
        return cmd_generate(root)
    if args.command == "derived":
        return cmd_derived(root)
    if args.command == "regen-check":
        return cmd_regen_check(root)
    return cmd_check(root)


if __name__ == "__main__":
    run_module_main(main)
