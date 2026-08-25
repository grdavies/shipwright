#!/usr/bin/env python3
"""Advisory ProjectBaseline@v1 synthesis (PRD 330 R6, R12, R14).

Stable callable/CLI surface for ``/sw-init`` and future PRD 331 ``/sw-explore``
consumers. Emits draft-only baselines with source evidence, confidence, and
preserved conflicts. Never promotes doctrine and never registers ``/sw-explore``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from _sw.cli import run_module_main

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Stable interface id for init / future explore handoff (R6).
SYNTHESIS_INTERFACE_VERSION = "project-baseline-synthesis@v1"
BASELINE_VERSION = "ProjectBaseline@v1"
SCHEMA_REL = Path("core/sw-reference/project-baseline.schema.json")
DEFAULT_DRAFT_REL = Path(".cursor/project-baseline.draft.json")
DEFAULT_DOCTRINE_REL = Path(".cursor/project-doctrine.json")

CONFIDENCE_VALUES = frozenset({"high", "medium", "low", "unknown"})
CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "unknown": 0}

FORBIDDEN_AUTHORITY_KEYS = frozenset(
    {"doctrineAuthority", "productAuthority", "autonomousPromotion", "promoted"}
)

# Marker files → (subject key, claim template, confidence).
_LANGUAGE_MARKERS: tuple[tuple[str, str, str, str], ...] = (
    ("package.json", "runtime.primary", "Primary runtime appears to be Node.js.", "high"),
    ("pyproject.toml", "runtime.primary", "Primary runtime appears to be Python.", "high"),
    ("setup.py", "runtime.primary", "Primary runtime appears to be Python.", "high"),
    ("setup.cfg", "runtime.primary", "Primary runtime appears to be Python.", "high"),
    ("go.mod", "runtime.primary", "Primary runtime appears to be Go.", "high"),
    ("Cargo.toml", "runtime.primary", "Primary runtime appears to be Rust.", "high"),
    ("Gemfile", "runtime.primary", "Primary runtime appears to be Ruby.", "high"),
    ("pom.xml", "runtime.primary", "Primary runtime appears to be JVM.", "high"),
    ("build.gradle", "runtime.primary", "Primary runtime appears to be JVM.", "high"),
    ("build.gradle.kts", "runtime.primary", "Primary runtime appears to be JVM.", "high"),
)

_DOC_MARKERS: tuple[tuple[str, str, str, str], ...] = (
    ("README.md", "docs.readme", "Repository includes a README.md.", "medium"),
    ("AGENTS.md", "docs.agents", "Repository includes AGENTS.md guidance.", "medium"),
    ("Makefile", "build.make", "Repository includes a Makefile.", "medium"),
    ("ansible.cfg", "ops.ansible", "Repository includes Ansible configuration.", "medium"),
    ("galaxy.yml", "ops.ansible", "Repository includes Ansible galaxy metadata.", "medium"),
)

_ADR_CANDIDATES: tuple[str, ...] = (
    "docs/adr",
    "docs/adrs",
    "docs/architecture/adr",
    "architecture/adr",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def file_uri(rel: str) -> str:
    return f"file://repo/{rel.lstrip('/')}"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_claim(claim: str) -> str:
    return " ".join(claim.strip().split()).lower()


def _rank_confidence(value: str | None) -> int:
    if value in CONFIDENCE_RANK:
        return CONFIDENCE_RANK[value]
    return CONFIDENCE_RANK["unknown"]


def _best_confidence(values: Sequence[str]) -> str:
    if not values:
        return "unknown"
    return max(values, key=_rank_confidence)


def _is_non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _observation_from_mapping(raw: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    key = str(raw.get("key") or raw.get("subject") or f"observation-{index}").strip()
    claim = str(raw.get("claim") or "").strip()
    if not claim:
        raise ValueError(f"observation[{index}] missing claim")
    evidence = raw.get("sourceEvidence")
    if isinstance(evidence, Mapping):
        uri = str(evidence.get("uri") or "").strip()
        digest = evidence.get("digest")
        quote = evidence.get("quote")
        accessed_at = evidence.get("accessedAt")
    else:
        uri = str(raw.get("uri") or "").strip()
        digest = raw.get("digest")
        quote = raw.get("quote")
        accessed_at = raw.get("accessedAt")
    if not uri:
        raise ValueError(f"observation[{index}] missing sourceEvidence.uri")
    confidence = str(raw.get("confidence") or "unknown").strip()
    if confidence not in CONFIDENCE_VALUES:
        confidence = "unknown"
    out: dict[str, Any] = {
        "key": key,
        "claim": claim,
        "confidence": confidence,
        "sourceEvidence": {"uri": uri},
    }
    if _is_non_empty_str(digest):
        out["sourceEvidence"]["digest"] = str(digest)
    if isinstance(quote, str):
        out["sourceEvidence"]["quote"] = quote
    if _is_non_empty_str(accessed_at):
        out["sourceEvidence"]["accessedAt"] = str(accessed_at)
    return out


def normalize_observations(
    observations: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Normalize caller-supplied observations into a stable internal shape."""
    if not observations:
        return []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(observations):
        if not isinstance(raw, Mapping):
            raise ValueError(f"observation[{index}] must be an object")
        normalized.append(_observation_from_mapping(raw, index=index))
    return normalized


def discover_observations(root: Path, *, accessed_at: str | None = None) -> list[dict[str, Any]]:
    """Scan a brownfield tree for advisory marker observations (R6)."""
    root = root.resolve()
    stamp = accessed_at or utc_now()
    found: list[dict[str, Any]] = []

    def _add(rel: str, key: str, claim: str, confidence: str) -> None:
        path = root / rel
        if not path.is_file():
            return
        data = path.read_bytes()
        found.append(
            {
                "key": key,
                "claim": claim,
                "confidence": confidence,
                "sourceEvidence": {
                    "uri": file_uri(rel),
                    "digest": sha256_hex(data),
                    "accessedAt": stamp,
                },
            }
        )

    for rel, key, claim, confidence in _LANGUAGE_MARKERS:
        _add(rel, key, claim, confidence)
    for rel, key, claim, confidence in _DOC_MARKERS:
        _add(rel, key, claim, confidence)

    for adr_rel in _ADR_CANDIDATES:
        adr_dir = root / adr_rel
        if not adr_dir.is_dir():
            continue
        entries = sorted(p.name for p in adr_dir.iterdir() if p.is_file())
        claim = (
            f"ADR inventory observed under {adr_rel}/ ({len(entries)} file(s))."
            if entries
            else f"ADR directory present at {adr_rel}/ with no files yet."
        )
        found.append(
            {
                "key": "architecture.adr-inventory",
                "claim": claim,
                "confidence": "medium" if entries else "low",
                "sourceEvidence": {
                    "uri": file_uri(adr_rel + "/"),
                    "quote": ", ".join(entries[:8]),
                    "accessedAt": stamp,
                },
            }
        )
        break

    return found


def synthesize_baseline(
    observations: Sequence[Mapping[str, Any]] | None = None,
    *,
    baseline_id: str = "consumer-baseline",
    created_at: str | None = None,
    provenance_source: str = "baseline-synthesis",
    actor: str | None = None,
) -> dict[str, Any]:
    """Synthesize a schema-shaped ProjectBaseline@v1 **draft** (never promoted).

    Zero observations → empty facts + ``confidence: unknown``.
    One or many agreeing observations → facts with evidence.
    Contradictory claims on the same key → open conflicts (R14).
    """
    stamp = created_at or utc_now()
    normalized = normalize_observations(observations)
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in normalized:
        by_key[obs["key"]].append(obs)

    facts: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    fact_counter = 0
    conflict_counter = 0

    for key in sorted(by_key):
        group = by_key[key]
        claim_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for obs in group:
            claim_groups[_normalize_claim(obs["claim"])].append(obs)

        if len(claim_groups) == 1:
            members = next(iter(claim_groups.values()))
            primary = members[0]
            fact_counter += 1
            fact: dict[str, Any] = {
                "id": f"fact-{fact_counter}",
                "claim": primary["claim"],
                "sourceEvidence": dict(primary["sourceEvidence"]),
                "confidence": _best_confidence([str(m["confidence"]) for m in members]),
            }
            facts.append(fact)
            continue

        conflict_counter += 1
        observations_out: list[dict[str, Any]] = []
        for members in claim_groups.values():
            for member in members:
                fact_counter += 1
                obs_out: dict[str, Any] = {
                    "factId": f"fact-{fact_counter}",
                    "claim": member["claim"],
                    "sourceEvidence": dict(member["sourceEvidence"]),
                    "confidence": member["confidence"],
                }
                observations_out.append(obs_out)
        conflicts.append(
            {
                "id": f"conflict-{key.replace('.', '-')}",
                "status": "open",
                "observations": observations_out,
            }
        )

    root_confidence = (
        "unknown"
        if not facts and not conflicts
        else _best_confidence(
            [str(f.get("confidence") or "unknown") for f in facts]
            + [
                str(obs.get("confidence") or "unknown")
                for conflict in conflicts
                for obs in conflict["observations"]
            ]
        )
    )
    if conflicts and root_confidence in {"high", "medium"}:
        # Conflicts lower overall draft confidence until operator review.
        root_confidence = "low"

    provenance: dict[str, Any] = {
        "createdAt": stamp,
        "source": provenance_source,
    }
    if actor:
        provenance["actor"] = actor

    document: dict[str, Any] = {
        "id": baseline_id,
        "version": BASELINE_VERSION,
        "provenance": provenance,
        "status": "draft",
        "confidence": root_confidence,
        "facts": facts,
    }
    if conflicts:
        document["conflicts"] = conflicts
    return document


def synthesize_from_root(
    root: Path,
    *,
    baseline_id: str = "consumer-baseline",
    created_at: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Discover brownfield markers under ``root`` and synthesize a draft baseline."""
    stamp = created_at or utc_now()
    observations = discover_observations(root, accessed_at=stamp)
    return synthesize_baseline(
        observations,
        baseline_id=baseline_id,
        created_at=stamp,
        provenance_source="baseline-synthesis",
        actor=actor,
    )


def validate_baseline(document: Mapping[str, Any]) -> list[str]:
    """Lightweight ProjectBaseline@v1 draft validation (schema-aligned)."""
    errors: list[str] = []
    if not isinstance(document, Mapping):
        return ["invalid:document"]
    for key in document:
        if key in FORBIDDEN_AUTHORITY_KEYS:
            errors.append(f"forbidden:{key}")
    if not _is_non_empty_str(document.get("id")):
        errors.append("missing:id")
    if document.get("version") != BASELINE_VERSION:
        errors.append("invalid:version")
    if document.get("status") != "draft":
        errors.append("invalid:status")
    provenance = document.get("provenance")
    if not isinstance(provenance, Mapping):
        errors.append("missing:provenance")
    else:
        if not _is_non_empty_str(provenance.get("createdAt")):
            errors.append("missing:provenance.createdAt")
        if not _is_non_empty_str(provenance.get("source")):
            errors.append("missing:provenance.source")
    has_confidence = document.get("confidence") in CONFIDENCE_VALUES
    has_expiry = _is_non_empty_str(document.get("expiresAt"))
    if not has_confidence and not has_expiry:
        errors.append("missing:confidence-or-expiresAt")
    facts = document.get("facts")
    if not isinstance(facts, list):
        errors.append("missing:facts")
    else:
        for fact in facts:
            if not isinstance(fact, Mapping):
                errors.append("invalid:facts.entry")
                continue
            if not _is_non_empty_str(fact.get("id")) or not _is_non_empty_str(fact.get("claim")):
                errors.append("invalid:facts.entry")
            evidence = fact.get("sourceEvidence")
            if not isinstance(evidence, Mapping) or not _is_non_empty_str(evidence.get("uri")):
                errors.append("invalid:facts.sourceEvidence")
            fact_conf = fact.get("confidence") in CONFIDENCE_VALUES
            fact_exp = _is_non_empty_str(fact.get("expiresAt"))
            if not fact_conf and not fact_exp:
                errors.append("invalid:facts.confidence-or-expiresAt")
    conflicts = document.get("conflicts")
    if conflicts is not None:
        if not isinstance(conflicts, list):
            errors.append("invalid:conflicts")
        else:
            for conflict in conflicts:
                if not isinstance(conflict, Mapping):
                    errors.append("invalid:conflicts.entry")
                    continue
                if not _is_non_empty_str(conflict.get("id")):
                    errors.append("invalid:conflicts.id")
                if conflict.get("status") not in {"open", "acknowledged"}:
                    errors.append("invalid:conflicts.status")
                observations = conflict.get("observations")
                if not isinstance(observations, list) or len(observations) < 2:
                    errors.append("invalid:conflicts.observations")
                    continue
                for obs in observations:
                    if not isinstance(obs, Mapping):
                        errors.append("invalid:conflicts.observation")
                        continue
                    if not _is_non_empty_str(obs.get("factId")) or not _is_non_empty_str(
                        obs.get("claim")
                    ):
                        errors.append("invalid:conflicts.observation")
                    evidence = obs.get("sourceEvidence")
                    if not isinstance(evidence, Mapping) or not _is_non_empty_str(
                        evidence.get("uri")
                    ):
                        errors.append("invalid:conflicts.observation.sourceEvidence")
    return errors


def load_schema(root: Path) -> dict[str, Any]:
    return json.loads((root / SCHEMA_REL).read_text(encoding="utf-8"))


def validate_baseline_against_schema(
    document: Mapping[str, Any],
    *,
    root: Path | None = None,
    schema: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate with jsonschema when available; always run lightweight checks."""
    errors = validate_baseline(document)
    if errors:
        return errors
    try:
        import jsonschema
    except ImportError:
        return errors
    if schema is None:
        if root is None:
            return errors
        schema = load_schema(root)
    try:
        jsonschema.validate(dict(document), schema, cls=jsonschema.Draft202012Validator)
    except jsonschema.ValidationError as exc:
        errors.append(f"schema:{exc.message}")
    return errors


def draft_path(root: Path, rel: Path | None = None) -> Path:
    return root / (rel or DEFAULT_DRAFT_REL)


def write_draft(
    root: Path,
    document: Mapping[str, Any],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Persist a draft baseline only. Refuses non-draft or authority-bearing docs."""
    errors = validate_baseline(document)
    if errors:
        return {
            "verdict": "fail",
            "action": "write-draft",
            "error": "invalid-baseline",
            "errors": errors,
        }
    if document.get("status") != "draft":
        return {
            "verdict": "fail",
            "action": "write-draft",
            "error": "non-draft-refused",
            "cause": "baseline-status-must-be-draft",
        }
    target = path or draft_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(document), indent=2) + "\n", encoding="utf-8")
    return {
        "verdict": "pass",
        "action": "write-draft",
        "path": str(target.relative_to(root)) if target.is_relative_to(root) else str(target),
        "status": "draft",
        "promoted": False,
        "interface": SYNTHESIS_INTERFACE_VERSION,
    }


def refuse_promote(
    *,
    confirm: bool = False,
    doctrine_path: Path | None = None,
) -> dict[str, Any]:
    """Promotion is out of scope for this module (R12, R14).

    Explicit confirmation still refuses here — doctrine promotion belongs to
    ``project_doctrine.py`` / operator init flow, never silent synthesis.
    """
    _ = doctrine_path  # reserved for future handoff; never written here
    return {
        "verdict": "fail",
        "action": "promote",
        "error": "auto-promote-refused",
        "cause": "project-baseline-synthesis-is-draft-only",
        "confirm": bool(confirm),
        "promoted": False,
        "remediation": (
            "Review the draft baseline, then promote via the explicit operator "
            "doctrine lifecycle (project_doctrine /sw-init) — not project_baseline."
        ),
        "interface": SYNTHESIS_INTERFACE_VERSION,
    }


def interface_contract() -> dict[str, Any]:
    """Stable discovery contract for /sw-init and future /sw-explore (R6)."""
    return {
        "interface": SYNTHESIS_INTERFACE_VERSION,
        "baselineVersion": BASELINE_VERSION,
        "status": "draft-only",
        "registersCommands": [],
        "forbidsCommands": ["/sw-explore"],
        "callable": [
            "synthesize_baseline",
            "synthesize_from_root",
            "discover_observations",
            "validate_baseline",
            "write_draft",
            "refuse_promote",
        ],
        "autoPromote": False,
        "advisory": True,
    }


def _emit(payload: dict[str, Any], code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


def _load_observations_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("observations"), list):
        rows = data["observations"]
    elif isinstance(data, list):
        rows = data
    else:
        raise ValueError("observations file must be a list or {observations: [...]}")
    return [dict(row) for row in rows]


def cmd_interface(_args: argparse.Namespace) -> int:
    return _emit({"verdict": "pass", "action": "interface", **interface_contract()}, 0)


def cmd_discover(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    observations = discover_observations(root)
    return _emit(
        {
            "verdict": "pass",
            "action": "discover",
            "interface": SYNTHESIS_INTERFACE_VERSION,
            "count": len(observations),
            "observations": observations,
        },
        0,
    )


def cmd_synthesize(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    created_at = args.created_at or utc_now()
    if args.observations:
        try:
            observations = _load_observations_file(Path(args.observations))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _emit(
                {
                    "verdict": "fail",
                    "action": "synthesize",
                    "error": "invalid-observations",
                    "detail": str(exc),
                },
                20,
            )
        document = synthesize_baseline(
            observations,
            baseline_id=args.id,
            created_at=created_at,
            actor=args.actor,
        )
    else:
        document = synthesize_from_root(
            root,
            baseline_id=args.id,
            created_at=created_at,
            actor=args.actor,
        )

    errors = validate_baseline_against_schema(document, root=root)
    if errors:
        return _emit(
            {
                "verdict": "fail",
                "action": "synthesize",
                "error": "invalid-baseline",
                "errors": errors,
                "baseline": document,
            },
            20,
        )

    payload: dict[str, Any] = {
        "verdict": "pass",
        "action": "synthesize",
        "interface": SYNTHESIS_INTERFACE_VERSION,
        "status": "draft",
        "promoted": False,
        "registersCommands": [],
        "baseline": document,
    }
    if args.out:
        write_result = write_draft(root, document, path=Path(args.out))
        if write_result.get("verdict") != "pass":
            return _emit({**payload, **write_result, "verdict": "fail"}, 20)
        payload["path"] = write_result.get("path")
    return _emit(payload, 0)


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    path = Path(args.path)
    if not path.is_absolute():
        path = root / path
    document = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_baseline_against_schema(document, root=root)
    if errors:
        return _emit(
            {
                "verdict": "fail",
                "action": "validate",
                "errors": errors,
            },
            20,
        )
    return _emit(
        {
            "verdict": "pass",
            "action": "validate",
            "status": document.get("status"),
            "promoted": False,
        },
        0,
    )


def cmd_promote(args: argparse.Namespace) -> int:
    result = refuse_promote(confirm=bool(args.confirm))
    return _emit(result, 20)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="project_baseline.py",
        description=(
            "Advisory ProjectBaseline@v1 synthesis — draft only; "
            "does not promote doctrine or register /sw-explore."
        ),
    )
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command")

    interface_p = sub.add_parser("interface", help="Print stable synthesis interface contract")
    interface_p.set_defaults(func=cmd_interface)

    discover_p = sub.add_parser("discover", help="Discover brownfield marker observations")
    discover_p.set_defaults(func=cmd_discover)

    synthesize_p = sub.add_parser("synthesize", help="Synthesize a draft ProjectBaseline@v1")
    synthesize_p.add_argument("--id", default="consumer-baseline")
    synthesize_p.add_argument("--observations", help="JSON file of observations (skip discovery)")
    synthesize_p.add_argument("--out", help="Optional draft output path")
    synthesize_p.add_argument("--actor", default="")
    synthesize_p.add_argument("--created-at", default="")
    synthesize_p.set_defaults(func=cmd_synthesize)

    validate_p = sub.add_parser("validate", help="Validate a ProjectBaseline@v1 document")
    validate_p.add_argument("--path", required=True)
    validate_p.set_defaults(func=cmd_validate)

    promote_p = sub.add_parser(
        "promote",
        help="Always refuses — synthesis is draft-only (use doctrine lifecycle)",
    )
    promote_p.add_argument(
        "--confirm",
        action="store_true",
        help="Even with confirm, promote remains refused in this module",
    )
    promote_p.set_defaults(func=cmd_promote)

    parser.set_defaults(command="interface", func=cmd_interface)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    run_module_main(main)
