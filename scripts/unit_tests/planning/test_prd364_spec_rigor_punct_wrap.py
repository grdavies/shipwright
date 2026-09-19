"""PRD 364 — punctuation-wrapper narrowing (phase 2: R5, R6)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def _load_matcher():
    path = _WORKTREE_ROOT / "scripts/spec-rigor-check.py"
    spec = importlib.util.spec_from_file_location("spec_rigor_check_prd364", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_r5_wrap_tokens_three_unfinished_only() -> None:
    m = _load_matcher()
    # Ordinary word + colon / non-colliding bracket are not wrapper hits.
    assert m.text_has_ambiguity_marker("Source: approved specification.") is False
    assert m.text_has_ambiguity_marker("Pending: must not wrap") is False
    assert m.text_has_ambiguity_marker("Label [Pending] in UI") is False
    assert m.text_has_ambiguity_marker(
        "Required critical states: Todo/in progress/verifying/done/blocked/cancelled"
    ) is False
    # Colliding unfinished-work wraps still fail (case-insensitive).
    assert m.text_has_ambiguity_marker("State Todo: must be explicit") is True
    assert m.text_has_ambiguity_marker("State TBD: open") is True
    assert m.text_has_ambiguity_marker("State FIXME: open") is True
    assert m.text_has_ambiguity_marker("Label [todo] in UI") is True
    assert m.text_has_ambiguity_marker("Label [TBD] in UI") is True
    assert m.text_has_ambiguity_marker("Label [FIXME] in UI") is True


def test_r6_wrap_before_title_case_precedence() -> None:
    m = _load_matcher()
    # Title-case bare Todo passes (361 R2); Todo: wrap still fails before masking.
    assert m.text_has_ambiguity_marker("Workflow enters Todo when criteria met") is False
    assert m.text_has_ambiguity_marker("State Todo: must be explicit") is True
    # Wrap layer remains ahead of Title-case masking for colliding wraps.
    assert m.text_has_ambiguity_marker("Todo: next step after named-state") is True
