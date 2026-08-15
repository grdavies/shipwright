#!/usr/bin/env python3
"""PRD 270 R8 — registry-sourced capability documentation for planning/issue providers."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from planning.provider_conformance import load_conformance_record

REGISTRY_REL = Path("core/sw-reference/capability-registry.json")
ROOT_CAPABILITIES_REL = Path("CAPABILITIES.md")
ISSUES_CAPABILITIES_REL = Path("core/providers/issues/CAPABILITIES.md")
GENERATOR_BANNER = (
    "Generated from `core/sw-reference/capability-registry.json` via "
    "`scripts/capability_docs.py` — do not edit by hand."
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
    root_md = render_root_capabilities_md(root, registry)
    if "linear" not in root_md:
        errors.append("root CAPABILITIES.md must include linear provider row when recognized")
    elif _linear_recognized(root):
        linear_row_shipped = "`linear` | **shipped**" in root_md or "`linear` | shipped" in root_md
        linear_recognized_only = "`linear` | recognized (not shipped)" in root_md
        if derive_shipped_issues_providers(root, registry) >= frozenset({"linear"}):
            if not linear_row_shipped:
                errors.append("linear: derived shipped but root docs do not render shipped")
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
    return errors


def cmd_generate(root: Path) -> int:
    registry = load_registry(root)
    (root / ROOT_CAPABILITIES_REL).write_text(
        render_root_capabilities_md(root, registry),
        encoding="utf-8",
    )
    (root / ISSUES_CAPABILITIES_REL).write_text(
        render_issues_capabilities_md(root, registry),
        encoding="utf-8",
    )
    print(json.dumps({"verdict": "ok", "action": "capability-docs-generate"}, indent=2))
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
        choices=("generate", "check", "derived"),
        default="check",
    )
    args = parser.parse_args(argv)
    root = repo_root()
    if args.command == "generate":
        return cmd_generate(root)
    if args.command == "derived":
        return cmd_derived(root)
    return cmd_check(root)


if __name__ == "__main__":
    run_module_main(main)
