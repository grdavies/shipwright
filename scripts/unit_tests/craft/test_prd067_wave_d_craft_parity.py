"""PRD 067 Wave D — craft-parity operator UX (R24-R35) presence and contract fixtures."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMMANDS = ROOT / "core" / "commands"
SKILLS = ROOT / "core" / "skills"
GUIDES = ROOT / "docs" / "guides"
PROVENANCE = re.compile(r"\bPRD\s*\d+|\bR\d+\b|\bGAP-\d+", re.I)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing file: {path}"
    return path.read_text(encoding="utf-8")


# --- R24: guided /sw-init interview -----------------------------------------------------------

def test_sw_init_has_guided_interview() -> None:
    text = _read(COMMANDS / "sw-init.md")
    assert "Guided interview" in text
    assert "unresolved" in text.lower()
    assert "doctor" in text.lower()
    assert re.search(r"recommended\s+default", text, re.I)


# --- R25: state-aware /sw entry ---------------------------------------------------------------

def test_sw_entry_command_exists_and_routes_from_state() -> None:
    text = _read(COMMANDS / "sw.md")
    assert "not a static menu" in text.lower() or "not a menu" in text.lower()
    assert "shipwright-state.py read" in text
    assert "confirm" in text.lower()
    assert "/sw-init" in text
    assert "/sw-deliver run" in text


# --- R26: closed rename table, no PRD/R-ID tokens in docs --------------------------------------

def test_commands_guide_has_closed_rename_table() -> None:
    text = _read(GUIDES / "commands.md")
    assert "/sw-setup" in text
    assert "/sw-init" in text
    assert "/sw-compound" in text
    assert "/sw-retrospective" in text
    assert "One release" in text or "one release" in text


def test_new_commands_documented_in_commands_guide() -> None:
    text = _read(GUIDES / "commands.md")
    for cmd in ("/sw`", "/sw-ask`", "/sw-become`", "/sw-note`", "/sw-guide`"):
        assert cmd in text, f"missing {cmd} in commands.md"


def test_user_guides_free_of_prd_tokens() -> None:
    paths = list(GUIDES.glob("*.md")) + [ROOT / "README.md"]
    offenders: list[str] = []
    for path in paths:
        if PROVENANCE.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


# --- R27/R28/R31: brainstorm divergence, unsure routing, optional persona enrichment -----------

def test_brainstorm_skill_has_divergence_phase() -> None:
    text = _read(SKILLS / "brainstorm" / "SKILL.md")
    assert "Divergence phase" in text
    assert "core tension" in text.lower()
    assert "cross-domain" in text.lower()
    assert "conviction" in text.lower()


def test_brainstorm_skill_has_unsure_routing_by_type() -> None:
    text = _read(SKILLS / "brainstorm" / "SKILL.md")
    assert "Unsure routing" in text
    assert "calibration-loop" in text
    assert "narrower" in text.lower()
    assert "explicit delegation" in text.lower() or "delegated" in text.lower()


def test_brainstorm_skill_has_optional_persona_enrichment() -> None:
    text = _read(SKILLS / "brainstorm" / "SKILL.md")
    assert "persona enrichment" in text.lower()
    assert "non-blocking" in text.lower() or "never block" in text.lower()


def test_requirements_sections_persist_divergence_outcome() -> None:
    text = _read(SKILLS / "brainstorm" / "references" / "requirements-sections.md")
    assert "divergence" in text.lower()
    assert "rejected" in text.lower()


# --- R29: calibration-loop skill + three wired consumers ---------------------------------------

def test_calibration_loop_skill_exists_with_fixed_verdict_set() -> None:
    path = SKILLS / "calibration-loop" / "SKILL.md"
    text = _read(path)
    assert "name: calibration-loop" in text
    for verdict in ("`A`", "`B`", "`either`", "`neither`", "`more-info`"):
        assert verdict in text
    assert "stop on stability" in text.lower() or "stability" in text.lower()
    assert "restate" in text.lower()


def test_calibration_loop_wired_to_three_consumers() -> None:
    text = _read(SKILLS / "calibration-loop" / "SKILL.md")
    assert "/sw-brainstorm" in text
    assert "/sw-doc-review" in text
    assert "/sw-feedback" in text

    doc_review_synthesis = _read(SKILLS / "doc-review" / "references" / "synthesis.md")
    assert "calibration-loop" in doc_review_synthesis
    assert "Disposition disputes" in doc_review_synthesis

    feedback_skill = _read(SKILLS / "feedback" / "SKILL.md")
    assert "calibration-loop" in feedback_skill
    assert "ambiguous" in feedback_skill.lower()


# --- R30: /sw-ask read-only consult --------------------------------------------------------------

def test_sw_ask_is_read_only_persona_router() -> None:
    text = _read(COMMANDS / "sw-ask.md")
    assert "read-only" in text.lower()
    assert "no pipeline side effects" in text.lower() or "no side effects" in text.lower()
    assert "sw-coherence-reviewer" in text


# --- R32: /sw-become single destination, confirm-before-write, no overwrite --------------------

def test_sw_become_has_fixed_destination_and_no_overwrite_guard() -> None:
    text = _read(COMMANDS / "sw-become.md")
    assert "core/personas/<slug>.md" in text
    assert "confirm-before-write" in text.lower() or "confirm-before-write" in text
    assert "no-overwrite" in text.lower() or "never overwrite" in text.lower() or "no overwrite" in text.lower()
    assert "models.routing.agents" in text


# --- R33/R34: /sw-note shapes, graduate provenance, redact-or-skip session index ---------------

def test_sw_note_supports_three_shapes_and_graduate_provenance() -> None:
    text = _read(COMMANDS / "sw-note.md")
    for shape in ("idea", "task", "note"):
        assert f"`{shape}`" in text
    assert ".cursor/sw-notebook" in text
    assert "graduate" in text.lower()
    assert "bidirectional provenance" in text.lower() or "back-pointer" in text.lower()
    assert "at most one" in text.lower()


def test_sw_note_session_index_gated_and_fails_closed() -> None:
    text = _read(COMMANDS / "sw-note.md")
    assert "notebook.sessionIndex" in text
    assert "memory-redact.py" in text
    assert "skip injection" in text.lower()


def test_notebook_config_key_schema_default_false() -> None:
    for schema_path in (ROOT / ".sw" / "config.schema.json", ROOT / "core" / "sw-reference" / "config.schema.json"):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        notebook = schema["properties"]["notebook"]["properties"]["sessionIndex"]
        assert notebook["type"] == "boolean"
        assert notebook["default"] is False


# --- R35: /sw-guide read-only diagnostic ---------------------------------------------------------

def test_sw_guide_is_read_only_diagnostic() -> None:
    text = _read(COMMANDS / "sw-guide.md")
    assert "read-only" in text.lower()
    assert "never mutates" in text.lower() or "no writes" in text.lower()
    assert "sw-configure.py drift-check" in text
    assert "planning-doctor.py" in text


# --- Model tier + communication routing registered for all new surfaces ------------------------

def test_new_commands_and_skill_have_model_tier_routing() -> None:
    routing = json.loads((ROOT / "core" / "sw-reference" / "model-routing.defaults.json").read_text(encoding="utf-8"))
    commands = routing["routing"]["commands"]
    for cmd in ("sw", "sw-ask", "sw-become", "sw-note", "sw-guide"):
        assert cmd in commands, f"missing model-tier routing for {cmd}"
    assert "calibration-loop" in routing["routing"]["skills"]


def test_new_commands_have_communication_routing() -> None:
    routing = json.loads(
        (ROOT / "core" / "sw-reference" / "communication-routing.defaults.json").read_text(encoding="utf-8")
    )
    commands = routing["routing"]["commands"]
    for cmd in ("sw", "sw-ask", "sw-become", "sw-note", "sw-guide"):
        assert cmd in commands, f"missing communication routing for {cmd}"
    assert "calibration-loop" in routing["routing"]["skills"]


# --- Build-chain parity: new core files mirrored into dist/ ------------------------------------

def test_new_surfaces_mirrored_into_dist() -> None:
    for platform_dir in ("dist/cursor", "dist/claude-code"):
        for rel in (
            "commands/sw.md",
            "commands/sw-ask.md",
            "commands/sw-become.md",
            "commands/sw-note.md",
            "commands/sw-guide.md",
            "skills/calibration-loop/SKILL.md",
        ):
            assert (ROOT / platform_dir / rel).is_file(), f"missing {platform_dir}/{rel}"
