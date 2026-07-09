#!/usr/bin/env python3
"""Golden-fixture doc-review compression parity harness (PRD 058 R30).

Builds representative persona-panel dispatch prompts with compression disabled vs
enabled, extracts deterministic review-signal finding sets, and requires material
equivalence after orchestrator-side retrieve() recovery for compressed runs.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dispatch_prompt import (  # noqa: E402
    ContextBlock,
    build_task_dispatch_prompt,
    load_context_compression_config,
    recover_compressed_context,
)

SIGNAL_RE = re.compile(r"FINDING_SIGNAL:([A-Z0-9-]+)")
PERSONA_PANEL = (
    "sw-security-reviewer",
    "sw-coherence-reviewer",
    "sw-feasibility-reviewer",
    "sw-product-reviewer",
)


def _fixture_path() -> Path:
    return SCRIPT_DIR / "golden-doc-review-context.json"


def _load_fixture_text() -> str:
    return _fixture_path().read_text(encoding="utf-8")


def extract_finding_signals(text: str) -> set[str]:
    return set(SIGNAL_RE.findall(text))


def _write_config(tmp: Path, *, enabled: bool, threshold: int = 400, name: str) -> Path:
    cfg_path = tmp / name
    cfg_path.write_text(
        json.dumps(
            {
                "contextCompression": {
                    "enabled": enabled,
                    "thresholdTokens": threshold,
                    "strategies": {
                        "json": "compress",
                        "diff": "compress",
                        "log": "compress",
                        "prose": "compress",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return cfg_path


def collect_findings(result, *, root: Path) -> set[str]:
    corpus = [result.prompt]
    for key in result.retrieve_keys:
        corpus.append(recover_compressed_context(key, root=root))
    found: set[str] = set()
    for chunk in corpus:
        found |= extract_finding_signals(chunk)
    return found


def run_persona_panel(*, root: Path, config_path: Path, enabled: bool) -> dict[str, object]:
    fixture = _load_fixture_text()
    config = load_context_compression_config(root, str(config_path))
    panel: dict[str, object] = {}
    all_findings: set[str] = set()
    total_before = 0
    total_after = 0
    any_compression = False

    for persona in PERSONA_PANEL:
        result = build_task_dispatch_prompt(
            intensity="normal",
            intensity_source="routing.skills",
            body=f"Review the attached PRD context as {persona}.",
            context_blocks=[ContextBlock(text=fixture, label="golden-prd", content_type="json")],
            config_path=str(config_path),
            root=root,
        )
        findings = collect_findings(result, root=root)
        panel[persona] = {
            "tokensBefore": result.tokens_before,
            "tokensAfter": result.tokens_after,
            "compressionApplied": result.compression_applied,
            "findingCount": len(findings),
        }
        all_findings |= findings
        total_before += result.tokens_before
        total_after += result.tokens_after
        any_compression = any_compression or result.compression_applied

    return {
        "enabled": enabled,
        "findings": sorted(all_findings),
        "panel": panel,
        "tokensBefore": total_before,
        "tokensAfter": total_after,
        "compressionApplied": any_compression,
    }


def run_parity_check() -> dict[str, object]:
    fixture = _load_fixture_text()
    expected = extract_finding_signals(fixture)
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        off_cfg = _write_config(root, enabled=False, name="compression-off.config.json")
        on_cfg = _write_config(root, enabled=True, threshold=400, name="compression-on.config.json")
        baseline = run_persona_panel(root=root, config_path=off_cfg, enabled=False)
        compressed = run_persona_panel(root=root, config_path=on_cfg, enabled=True)

    baseline_set = set(baseline["findings"])
    compressed_set = set(compressed["findings"])
    materially_equivalent = baseline_set == compressed_set == expected
    smaller = int(compressed["tokensAfter"]) < int(baseline["tokensAfter"])
    compressed_ran = bool(compressed["compressionApplied"])

    verdict = "pass" if materially_equivalent and smaller and compressed_ran else "fail"
    reasons: list[str] = []
    if baseline_set != expected:
        reasons.append("baseline-missing-signals")
    if compressed_set != expected:
        missing = sorted(expected - compressed_set)
        reasons.append(f"compressed-missing-signals:{','.join(missing[:5])}")
    if not smaller:
        reasons.append("compressed-not-smaller")
    if not compressed_ran:
        reasons.append("compression-not-applied")

    return {
        "verdict": verdict,
        "action": "context-compress-parity",
        "expectedFindingCount": len(expected),
        "baseline": {
            "findingCount": len(baseline_set),
            "tokensAfter": baseline["tokensAfter"],
            "compressionApplied": baseline["compressionApplied"],
        },
        "compressed": {
            "findingCount": len(compressed_set),
            "tokensAfter": compressed["tokensAfter"],
            "compressionApplied": compressed["compressionApplied"],
        },
        "reasons": reasons,
    }


def main() -> int:
    out = run_parity_check()
    print(json.dumps(out, indent=2))
    return 0 if out.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
