#!/usr/bin/env python3
"""Heterogeneous review provider synthesis (PRD 039 R13)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "info": 4}
PROVIDER_ID_RE = re.compile(r"^[a-z0-9-]*$")


def resolve_review_providers(review: dict[str, Any] | None) -> list[str]:
    """Coerce scalar review.provider to a single-element providers list."""
    review = review if isinstance(review, dict) else {}
    raw_providers = review.get("providers")
    if isinstance(raw_providers, list) and raw_providers:
        out: list[str] = []
        for item in raw_providers:
            pid = str(item or "").strip().lower()
            if pid and pid not in out:
                out.append(pid)
        if out:
            return out
    scalar = review.get("provider")
    if scalar is not None and str(scalar).strip() != "":
        return [str(scalar).strip().lower()]
    if "provider" not in review and "providers" not in review:
        return []
    return [str(scalar or "none").strip().lower()]


def _finding_key(item: dict[str, Any]) -> tuple[str, str, str]:
    path = str(item.get("path") or item.get("file") or "")
    line = str(item.get("line") or item.get("startLine") or "")
    body = str(item.get("body") or item.get("message") or item.get("title") or "")
    norm = re.sub(r"\s+", " ", body.strip().lower())[:120]
    return path, line, norm


def _severity(item: dict[str, Any]) -> str:
    sev = str(item.get("severity") or item.get("priority") or "P2").upper()
    if sev.startswith("P") and sev in SEVERITY_RANK:
        return sev
    if sev in ("INFO", "LOW"):
        return "P3"
    if sev in ("HIGH", "CRITICAL"):
        return "P0"
    return "P2"


def synthesize_findings(bundles: list[dict[str, Any]]) -> dict[str, Any]:
    """Severity-weighted union of non-overlapping findings across providers."""
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    providers: list[str] = []
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        provider = str(bundle.get("provider") or "unknown")
        if provider not in providers:
            providers.append(provider)
        findings = bundle.get("findings")
        if not isinstance(findings, list):
            inline = bundle.get("inlineThreads")
            non_inline = bundle.get("nonInline")
            findings = []
            if isinstance(inline, list):
                findings.extend(inline)
            if isinstance(non_inline, list):
                findings.extend(non_inline)
        for raw in findings if isinstance(findings, list) else []:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item.setdefault("severity", _severity(item))
            item.setdefault("providers", [provider])
            key = _finding_key(item)
            existing = merged.get(key)
            if existing is None:
                merged[key] = item
                continue
            if SEVERITY_RANK.get(_severity(item), 99) < SEVERITY_RANK.get(_severity(existing), 99):
                provs = sorted(set((existing.get("providers") or []) + [provider]))
                item["providers"] = provs
                merged[key] = item
            else:
                provs = sorted(set((existing.get("providers") or []) + [provider]))
                existing["providers"] = provs
    ordered = sorted(
        merged.values(),
        key=lambda f: (SEVERITY_RANK.get(_severity(f), 99), _finding_key(f)),
    )
    return {"providers": providers, "findings": ordered, "findingCount": len(ordered)}


def synthesize_gate_adapters(states: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Merge per-head adapter stdout JSON into provider-agnostic reviewLanded barrier."""
    active: list[tuple[str, dict[str, Any]]] = []
    for pid, state in states:
        if not isinstance(state, dict):
            continue
        if pid in ("none", "") and not state.get("capabilities"):
            continue
        active.append((pid, state))

    if not active:
        return {
            "reviewProviders": [],
            "reviewState": "unconfigured",
            "reviewLanded": True,
            "reviewedHead": None,
            "perProvider": {},
        }

    per_provider: dict[str, Any] = {}
    landed_all = True
    worst_state = "landed"
    reviewed_head = ""
    state_rank = {"off": 0, "unconfigured": 1, "skipped": 2, "landed": 3, "in-flight": 4}

    for pid, state in active:
        per_provider[pid] = state
        has_per_head = bool((state.get("capabilities") or {}).get("perHeadState"))
        if not has_per_head:
            landed = False
            rstate = "in-flight"
        else:
            landed = bool(state.get("perHeadLanded"))
            rstate = str(state.get("perHeadState") or "in-flight")
        if not landed:
            landed_all = False
        if state_rank.get(rstate, 99) >= state_rank.get(worst_state, 0):
            worst_state = rstate
        head = str(state.get("reviewedHead") or "")
        if head:
            reviewed_head = head

    return {
        "reviewProviders": [p for p, _ in active],
        "reviewState": worst_state if not landed_all else worst_state,
        "reviewLanded": landed_all,
        "reviewedHead": reviewed_head or None,
        "perProvider": per_provider,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(
            "usage: review_synthesize.py {resolve-providers|synthesize-findings|synthesize-gate} ...",
            file=sys.stderr,
        )
        return 2
    cmd = args[0]
    if cmd == "resolve-providers":
        cfg = json.loads(args[1]) if len(args) > 1 else {}
        review = cfg.get("review") if isinstance(cfg, dict) else {}
        print(json.dumps({"providers": resolve_review_providers(review if isinstance(review, dict) else {})}))
        return 0
    if cmd == "synthesize-findings":
        raw = sys.stdin.read() if len(args) == 1 else Path(args[1]).read_text(encoding="utf-8")
        bundles = json.loads(raw or "[]")
        if not isinstance(bundles, list):
            bundles = [bundles]
        print(json.dumps(synthesize_findings(bundles)))
        return 0
    if cmd == "synthesize-gate":
        raw = sys.stdin.read() if len(args) == 1 else Path(args[1]).read_text(encoding="utf-8")
        payload = json.loads(raw or "[]")
        states: list[tuple[str, dict[str, Any]]] = []
        if isinstance(payload, dict) and "states" in payload:
            for pid, st in (payload.get("states") or {}).items():
                states.append((str(pid), st if isinstance(st, dict) else {}))
        elif isinstance(payload, list):
            for row in payload:
                if isinstance(row, dict) and "provider" in row:
                    states.append((str(row["provider"]), row))
        print(json.dumps(synthesize_gate_adapters(states)))
        return 0
    print(json.dumps({"verdict": "fail", "reason": f"unknown subcommand: {cmd}"}))
    return 2


if __name__ == "__main__":
    run_module_main(main)
