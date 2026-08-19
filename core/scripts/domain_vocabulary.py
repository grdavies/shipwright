#!/usr/bin/env python3
"""Domain vocabulary store + divergence CLI (PRD 280 R7–R11).

Terms are authoritative in planning issue-store (`vocab-<slug>` units). This
module never writes under ``docs/`` in the code repo — all persistence routes
through ``planning_store``.
"""
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
from codebase_intelligence_signals import intelligence_config
from host_lib import load_workflow_config
from planning_materialize import parse_frontmatter
from planning_store import get_backend

VOCAB_UNIT_PREFIX = "vocab-"
VOCAB_BODY_PREFIX = "docs/planning/vocabulary/"
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")
TERM_STATUSES = frozenset({"active", "deprecated"})
REQUIRED_TERM_FIELDS = ("canonicalName", "definition")
OPTIONAL_LIST_FIELDS = ("aliases", "forbiddenAliases", "relationships", "invariants")
OPTIONAL_SCALAR_FIELDS = ("introducedBy", "supersedes")
DIVERGENCE_ARTIFACT_DIR = ".cursor/sw-vocabulary-divergence"
DIVERGENCE_ARTIFACT_NAME = "last.json"

# PRD 280 R9 fixture triplet — advisory divergence when all three appear.
FIXTURE_CONFLICT_TERMS = frozenset({"account", "tenant", "workspace"})
WORD_RE = re.compile(r"\b([a-z][a-z0-9_-]{2,})\b", re.IGNORECASE)
IDENT_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*)\b")


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_root(start: Path | None = None) -> Path:
    import subprocess

    cwd = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        fail("not a git repository")
    return Path(proc.stdout.strip())


def vocabulary_slug(slug: str) -> str:
    value = str(slug or "").strip().lower()
    if not SLUG_RE.match(value):
        fail("invalid-vocabulary-slug", slug=slug)
    return value


def vocabulary_unit_id(slug: str) -> str:
    slug = vocabulary_slug(slug)
    unit = f"{VOCAB_UNIT_PREFIX}{slug}"
    if not unit.startswith(VOCAB_UNIT_PREFIX):
        fail("invalid-vocabulary-unit-id", unitId=unit)
    return unit


def vocabulary_body_path(slug: str) -> str:
    return f"{VOCAB_BODY_PREFIX}{vocabulary_slug(slug)}.md"


def _coerce_string_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                fail("invalid-term-field", field=field, reason="list items must be non-empty strings")
            out.append(item.strip())
        return out
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text.replace("'", '"'))
            except json.JSONDecodeError:
                parsed = [part.strip() for part in text.strip("[]").split(",") if part.strip()]
            if isinstance(parsed, list):
                return _coerce_string_list(parsed, field=field)
        return [text]
    fail("invalid-term-field", field=field, reason="expected string list")


def validate_term(term: dict[str, Any]) -> dict[str, Any]:
    """Validate vocabulary term schema (PRD 280 R7)."""
    if not isinstance(term, dict):
        fail("invalid-term", reason="term must be an object")
    errors: list[str] = []
    for field in REQUIRED_TERM_FIELDS:
        raw = term.get(field)
        if not isinstance(raw, str) or not raw.strip():
            errors.append(f"missing or empty required field: {field}")
    status = str(term.get("status") or "active").strip().lower()
    if status not in TERM_STATUSES:
        errors.append(f"invalid status: {status}")
    normalized: dict[str, Any] = {
        "canonicalName": str(term.get("canonicalName", "")).strip(),
        "definition": str(term.get("definition", "")).strip(),
        "status": status,
        "aliases": _coerce_string_list(term.get("aliases"), field="aliases"),
        "forbiddenAliases": _coerce_string_list(term.get("forbiddenAliases"), field="forbiddenAliases"),
        "relationships": _coerce_string_list(term.get("relationships"), field="relationships"),
        "invariants": _coerce_string_list(term.get("invariants"), field="invariants"),
    }
    for field in OPTIONAL_SCALAR_FIELDS:
        raw = term.get(field)
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str):
            errors.append(f"invalid scalar field: {field}")
        else:
            normalized[field] = raw.strip()
    if errors:
        fail("term-schema-invalid", errors=errors)
    return normalized


def term_to_markdown(slug: str, term: dict[str, Any], *, project_key: str = "planning") -> str:
    validated = validate_term(term)
    unit_id = vocabulary_unit_id(slug)
    lines = [
        f"<!-- sw-project-key: {project_key} -->",
        "<!-- sw-artifact-type: vocabulary -->",
        f"<!-- sw-unit-id: {unit_id} -->",
        "<!-- sw-canonical-version: 1 -->",
        "",
        "---",
        f"id: {unit_id}",
        "type: vocabulary",
        f"status: {validated['status']}",
        "visibility: public",
        f"canonicalName: {validated['canonicalName']}",
        f"definition: {validated['definition']}",
    ]
    if validated["aliases"]:
        lines.append(f"aliases: {json.dumps(validated['aliases'])}")
    if validated["forbiddenAliases"]:
        lines.append(f"forbiddenAliases: {json.dumps(validated['forbiddenAliases'])}")
    if validated["relationships"]:
        lines.append(f"relationships: {json.dumps(validated['relationships'])}")
    if validated["invariants"]:
        lines.append(f"invariants: {json.dumps(validated['invariants'])}")
    for field in OPTIONAL_SCALAR_FIELDS:
        if field in validated:
            lines.append(f"{field}: {validated[field]}")
    lines.extend(
        [
            "---",
            "",
            f"# {validated['canonicalName']}",
            "",
            validated["definition"],
            "",
        ]
    )
    return "\n".join(lines)


def parse_term_markdown(content: str) -> dict[str, Any]:
    fm = parse_frontmatter(content) or {}
    term: dict[str, Any] = {
        "canonicalName": str(fm.get("canonicalName") or "").strip(),
        "definition": str(fm.get("definition") or "").strip(),
        "status": str(fm.get("status") or "active").strip().lower(),
        "aliases": _coerce_string_list(fm.get("aliases"), field="aliases"),
        "forbiddenAliases": _coerce_string_list(fm.get("forbiddenAliases"), field="forbiddenAliases"),
        "relationships": _coerce_string_list(fm.get("relationships"), field="relationships"),
        "invariants": _coerce_string_list(fm.get("invariants"), field="invariants"),
    }
    for field in OPTIONAL_SCALAR_FIELDS:
        if fm.get(field):
            term[field] = str(fm[field]).strip()
    return validate_term(term)


def _project_key(root: Path, cfg: dict[str, Any]) -> str:
    store = cfg.get("planning", {}).get("store", {}) if isinstance(cfg.get("planning"), dict) else {}
    if isinstance(store, dict) and store.get("projectKey"):
        return str(store["projectKey"])
    return "planning"


def put_term(root: Path, slug: str, term: dict[str, Any]) -> dict[str, Any]:
    unit_id = vocabulary_unit_id(slug)
    body_path = vocabulary_body_path(slug)
    local_dest = root / body_path
    if local_dest.exists():
        fail(
            "local-vocabulary-write-refused",
            reason="vocabulary is issue-store authoritative; remove local file or use planning_store only",
            path=str(body_path),
        )
    cfg = load_workflow_config(root)
    content = term_to_markdown(slug, term, project_key=_project_key(root, cfg))
    backend = get_backend(root, cfg, operation="write")
    result = backend.put(unit_id, body_path, content)
    if result.verdict not in {"ok", "deferred"}:
        fail("put-term-failed", unitId=unit_id, bodyPath=body_path, storeVerdict=result.verdict)
    return {
        "verdict": "pass",
        "action": "put-term",
        "unitId": unit_id,
        "bodyPath": body_path,
        "backend": result.backend,
        "storeVerdict": result.verdict,
        "term": validate_term(term),
        "humanGated": True,
    }


def get_term(root: Path, slug: str) -> dict[str, Any]:
    unit_id = vocabulary_unit_id(slug)
    body_path = vocabulary_body_path(slug)
    cfg = load_workflow_config(root)
    backend = get_backend(root, cfg, operation="read")
    result = backend.get(unit_id, body_path)
    if result.verdict != "ok" or not result.content:
        fail("get-term-missing", unitId=unit_id, bodyPath=body_path, storeVerdict=result.verdict)
    term = parse_term_markdown(result.content)
    return {
        "verdict": "pass",
        "action": "get-term",
        "unitId": unit_id,
        "bodyPath": body_path,
        "backend": result.backend,
        "term": term,
    }


def _iter_vocabulary_records(root: Path) -> list[dict[str, Any]]:
    cfg = load_workflow_config(root)
    backend = get_backend(root, cfg, operation="read")
    if backend.backend_id != "issue-store":
        return []
    client = getattr(backend, "_client", None)
    search = getattr(client, "issue_search", None)
    if not callable(search):
        return []
    project_key = getattr(backend, "project_key", _project_key(root, cfg))
    records = search(project_key=project_key)
    out: list[dict[str, Any]] = []
    for record in records:
        unit_id = str(getattr(record, "unit_id", "") or "")
        if not unit_id.startswith(VOCAB_UNIT_PREFIX):
            continue
        slug = unit_id[len(VOCAB_UNIT_PREFIX) :]
        body_path = vocabulary_body_path(slug)
        got = backend.get(unit_id, body_path)
        if got.verdict != "ok" or not got.content:
            continue
        try:
            term = parse_term_markdown(got.content)
        except SystemExit:
            continue
        out.append(
            {
                "slug": slug,
                "unitId": unit_id,
                "bodyPath": body_path,
                "term": term,
            }
        )
    out.sort(key=lambda item: item["slug"])
    return out


def list_terms(root: Path) -> dict[str, Any]:
    terms = _iter_vocabulary_records(root)
    return {
        "verdict": "pass",
        "action": "list-terms",
        "count": len(terms),
        "terms": terms,
    }


def _extract_surface_terms(text: str) -> set[str]:
    surfaces: set[str] = set()
    for match in WORD_RE.finditer(text):
        surfaces.add(match.group(1).lower())
    return surfaces


def _code_symbol_surfaces(root: Path, needles: set[str]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    if not needles:
        return hits
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(term) for term in sorted(needles)) + r")\b",
        re.IGNORECASE,
    )
    for rel_root in ("scripts", "core/scripts"):
        base = root / rel_root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "unit_tests" in path.parts:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in pattern.finditer(content):
                term = match.group(1).lower()
                rel = str(path.relative_to(root))
                hits.setdefault(term, [])
                if rel not in hits[term]:
                    hits[term].append(rel)
    return hits


def _openapi_surfaces(root: Path, needles: set[str]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    candidates = list(root.glob("**/openapi*.json")) + list(root.glob("**/openapi*.yaml"))
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(term) for term in sorted(needles)) + r")\b",
        re.IGNORECASE,
    )
    for path in candidates[:20]:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not pattern.search(content):
            continue
        for match in pattern.finditer(content):
            term = match.group(1).lower()
            rel = str(path.relative_to(root))
            hits.setdefault(term, [])
            if rel not in hits[term]:
                hits[term].append(rel)
    return hits


def _build_registry_index(terms: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Map lowercase surface form -> canonical concept key."""
    index: dict[str, set[str]] = {}
    for entry in terms:
        term = entry.get("term") or {}
        canonical = str(term.get("canonicalName") or entry.get("slug") or "").strip()
        if not canonical:
            continue
        concept = canonical.lower()
        surfaces = {concept, str(entry.get("slug") or "").lower()}
        surfaces.update(s.lower() for s in term.get("aliases") or [])
        surfaces.update(s.lower() for s in term.get("forbiddenAliases") or [])
        surfaces.discard("")
        for surface in surfaces:
            index.setdefault(surface, set()).add(concept)
    return index


def check_divergence(
    root: Path,
    *,
    text: str,
    unit_id: str | None = None,
    strict_mode: bool | None = None,
) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    intel = intelligence_config(root)
    strict = intel["strictMode"] if strict_mode is None else bool(strict_mode)
    body = text
    if unit_id:
        from planning_store import _default_body_path

        body_path = _default_body_path(unit_id, "prd")
        backend = get_backend(root, cfg, operation="read")
        result = backend.get(unit_id, body_path)
        if result.verdict != "ok" or not result.content:
            fail("divergence-source-missing", unitId=unit_id, storeVerdict=result.verdict)
        body = result.content

    registry_terms = _iter_vocabulary_records(root)
    registry_index = _build_registry_index(registry_terms)
    surfaces = _extract_surface_terms(body)
    divergences: list[dict[str, Any]] = []

    fixture_hits = sorted(term for term in FIXTURE_CONFLICT_TERMS if term in surfaces)
    if len(fixture_hits) >= 2:
        occurrences = [{"surface": term, "source": "text"} for term in fixture_hits]
        code_hits = _code_symbol_surfaces(root, FIXTURE_CONFLICT_TERMS)
        for term, paths in sorted(code_hits.items()):
            occurrences.append({"surface": term, "source": "code", "paths": paths[:10]})
        api_hits = _openapi_surfaces(root, FIXTURE_CONFLICT_TERMS)
        for term, paths in sorted(api_hits.items()):
            occurrences.append({"surface": term, "source": "schema", "paths": paths[:10]})
        severity = "error" if strict else "warn"
        divergences.append(
            {
                "concept": "customer-entity",
                "occurrences": occurrences,
                "severity": severity,
                "note": "fixture triplet account/tenant/workspace detected",
            }
        )

    for entry in registry_terms:
        term = entry["term"]
        canonical = str(term["canonicalName"])
        concept = canonical.lower()
        forbidden = {s.lower() for s in term.get("forbiddenAliases") or []}
        present_forbidden = sorted(forbidden & surfaces)
        if present_forbidden:
            divergences.append(
                {
                    "concept": concept,
                    "occurrences": [
                        {"surface": surface, "source": "text", "forbidden": True}
                        for surface in present_forbidden
                    ],
                    "severity": "error" if strict else "warn",
                    "note": f"forbidden alias for {canonical}",
                }
            )
        aliases = {concept, str(entry["slug"]).lower()}
        aliases.update(s.lower() for s in term.get("aliases") or [])
        alias_hits = sorted(aliases & surfaces)
        conflicting = sorted(
            surface
            for surface in surfaces
            if surface in registry_index
            and concept in registry_index[surface]
            and surface not in aliases
        )
        if conflicting:
            divergences.append(
                {
                    "concept": concept,
                    "occurrences": [
                        {"surface": surface, "source": "text"} for surface in conflicting
                    ],
                    "severity": "warn",
                    "note": f"surface form conflicts with canonical {canonical}",
                }
            )
        elif len(alias_hits) > 1:
            divergences.append(
                {
                    "concept": concept,
                    "occurrences": [{"surface": surface, "source": "text"} for surface in alias_hits],
                    "severity": "info",
                    "note": "multiple registered aliases present",
                }
            )

    max_severity = "info"
    rank = {"info": 0, "warn": 1, "error": 2}
    for item in divergences:
        sev = str(item.get("severity") or "info")
        if rank.get(sev, 0) > rank.get(max_severity, 0):
            max_severity = sev

    artifact = {
        "verdict": "pass",
        "action": "check-divergence",
        "checkedAt": utc_now(),
        "strictMode": strict,
        "divergence": divergences,
        "maxSeverity": max_severity,
        "registryTermCount": len(registry_terms),
        "humanGated": True,
        "note": "advisory by default; strictMode escalates severity to error",
    }
    if strict and max_severity == "error":
        artifact["verdict"] = "fail"
        artifact["error"] = "vocabulary-divergence-strict"

    artifact_path = root / DIVERGENCE_ARTIFACT_DIR / DIVERGENCE_ARTIFACT_NAME
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifact["artifactPath"] = str(artifact_path.relative_to(root))
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Domain vocabulary store + divergence (PRD 280)")
    parser.add_argument("--root", type=Path, default=None, help="Repository root (default: git root)")
    sub = parser.add_subparsers(dest="command", required=True)

    put_p = sub.add_parser("put-term", help="Store a vocabulary term via planning_store")
    put_p.add_argument("--slug", required=True)
    put_p.add_argument("--json", dest="json_body", help="Term JSON object")
    put_p.add_argument("--file", type=Path, help="Term JSON file")

    get_p = sub.add_parser("get-term", help="Fetch a vocabulary term from planning_store")
    get_p.add_argument("--slug", required=True)

    sub.add_parser("list-terms", help="List vocabulary terms from issue-store")

    div_p = sub.add_parser("check-divergence", help="Detect terminology drift in PRD/body text")
    div_p.add_argument("--text", help="Inline body text to scan")
    div_p.add_argument("--file", type=Path, help="Body file to scan (read-only; not persisted)")
    div_p.add_argument("--unit-id", help="PRD unit id to load from planning_store")
    div_p.add_argument(
        "--strict",
        action="store_true",
        help="Force strictMode for this invocation",
    )

    args = parser.parse_args(argv)
    root = (args.root or git_root()).resolve()

    if args.command == "put-term":
        if args.json_body:
            term = json.loads(args.json_body)
        elif args.file:
            term = json.loads(args.file.read_text(encoding="utf-8"))
        else:
            fail("put-term-requires-json", reason="pass --json or --file")
        emit(put_term(root, args.slug, term))

    if args.command == "get-term":
        emit(get_term(root, args.slug))

    if args.command == "list-terms":
        emit(list_terms(root))

    if args.command == "check-divergence":
        if args.unit_id:
            text = ""
        elif args.text:
            text = args.text
        elif args.file:
            text = args.file.read_text(encoding="utf-8")
        else:
            fail("check-divergence-requires-input", reason="pass --text, --file, or --unit-id")
        result = check_divergence(
            root,
            text=text,
            unit_id=args.unit_id,
            strict_mode=True if args.strict else None,
        )
        code = 20 if result.get("verdict") == "fail" else 0
        emit(result, code)

    fail(f"unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    run_module_main(main)
