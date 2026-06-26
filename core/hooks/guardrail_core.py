"""Platform-neutral guardrail decisions for Shipwright hooks."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from sw_hook_util import (
    filter_rules_by_allowlist,
    guardrails_enforce_before_submit,
    guardrails_require_rule_class,
    load_allowlist,
    load_config,
    memory_provider_marker_path,
    resolve_memory_provider,
    rules_script_for_provider,
    synthetic_config_from_marker,
    workflow_config_path,
)

_STATE_RELPATH = Path(".cursor") / "hooks" / "state" / "shipwright-memory-sync-scheduler.json"
_DEFAULT_MIN_TURNS = 10
_DEFAULT_MIN_MINUTES = 120
_FOLLOWUP = (
    "Run `/sw-memory-sync` now to distill new agent-transcript deltas into durable memories "
    "via the configured memory provider. Read the delta only; store high-signal substance "
    "(decisions, hard-won learnings, bug root-causes, design choices, notable review/CI "
    "patterns) with the right category, tags, and related files; search-before-store to "
    "avoid duplicates; never store raw transcripts or secrets. If nothing durable surfaced, "
    "respond exactly: No high-signal memory updates."
)


@dataclass(frozen=True)
class SubmitGuardResult:
    allow: bool
    message: str = ""


@dataclass(frozen=True)
class StopSyncResult:
    followup_message: str | None = None


def _rules_script(root: Path, plugin_root: Path, config: dict) -> Path | None:
    override = os.environ.get("SW_RULES_SCRIPT", "").strip()
    if override:
        return Path(override)
    provider = resolve_memory_provider(root, config)
    if not provider:
        return None
    return rules_script_for_provider(plugin_root, provider)


def fetch_rules(
    root: Path,
    plugin_root: Path,
    config: dict,
    *,
    rules_script: Path | None = None,
) -> tuple[bool, list[dict]]:
    script = rules_script if rules_script is not None else _rules_script(root, plugin_root, config)
    if script is None or not script.is_file():
        return False, []
    env = os.environ.copy()
    env["SW_WORKSPACE_ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(plugin_root), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    try:
        proc = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, []
    if proc.returncode != 0:
        return False, []
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError:
        return False, []
    if not payload.get("ok", False):
        return False, []
    rules = payload.get("rules", [])
    if not isinstance(rules, list):
        return False, []
    return True, [r for r in rules if isinstance(r, dict)]


def provider_unreachable_message(provider: str | None) -> str:
    name = provider or "memory"
    if provider == "recallium":
        return (
            "Shipwright: cannot reach Recallium to load rule-class guardrails. "
            "Fix Recallium connectivity or set memory.connection.restBaseUrl (localhost only), then retry. "
            "(Credentials are env-sourced — never committed config.)"
        )
    if provider == "in-repo":
        return (
            "Shipwright: in-repo rules adapter failed to load rule-class guardrails from disk. "
            "Check .cursor/sw-memory/rules/ and run /sw-setup to validate the store."
        )
    return (
        f"Shipwright: cannot load rule-class guardrails for provider '{name}'. "
        "Fix memory provider configuration or run /sw-setup, then retry."
    )


def resolve_submit_config(root: Path) -> dict | None:
    config_path = workflow_config_path(root)
    if config_path is None:
        return synthetic_config_from_marker(root)
    return load_config(root)


def evaluate_submit_guard(root: Path, plugin_root: Path) -> SubmitGuardResult:
    if os.environ.get("SW_TEST_SUBMIT_RAISE", "").strip() == "1":
        raise RuntimeError("injected test failure")

    config = resolve_submit_config(root)
    if config is None:
        return SubmitGuardResult(allow=True)

    if not guardrails_enforce_before_submit(config):
        return SubmitGuardResult(allow=True)

    provider = resolve_memory_provider(root, config)
    ok, rules = fetch_rules(root, plugin_root, config)
    if not ok:
        return SubmitGuardResult(allow=False, message=provider_unreachable_message(provider))

    allowlist_status, allowlist = load_allowlist(root)
    if allowlist_status == "corrupt":
        return SubmitGuardResult(
            allow=False,
            message=(
                "Shipwright: sw-memory-rule-allowlist.json is corrupt. "
                "Fix or remove the file, then retry."
            ),
        )

    rules = filter_rules_by_allowlist(rules, allowlist_status, allowlist)

    if not rules and guardrails_require_rule_class(config):
        return SubmitGuardResult(
            allow=False,
            message=(
                "Shipwright: this repo requires at least one allowlisted rule-class guardrail "
                "(memory.guardrails.requireRuleClass is true) but none are confirmed. "
                "Promote rules via /sw-memory-audit and update .cursor/sw-memory-rule-allowlist.json, "
                "or set requireRuleClass to false for greenfield/bootstrap repos."
            ),
        )

    return SubmitGuardResult(allow=True)


def memory_binding(config: dict, root: Path) -> dict:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    if not isinstance(memory, dict):
        memory = {}
    resolved = dict(memory)
    provider = resolve_memory_provider(root, config)
    if provider:
        resolved["provider"] = provider
    if not resolved.get("project"):
        resolved["project"] = root.name
        resolved["_projectInferredFromWorkspace"] = True
    return resolved


def _memory_line(memory: dict) -> str:
    provider = memory.get("provider") or "recallium"
    project = memory.get("project", "(unset — set memory.project in workflow.config.json)")
    scope = memory.get("defaultScope", "project")
    source = " (inferred from workspace root)" if memory.get("_projectInferredFromWorkspace") else ""
    return (
        f"- Memory provider: **{provider}**, project: **{project}**{source}, default scope: **{scope}**.\n"
        f"- Run a memory-preflight `load-context` for project `{project}` now, then targeted "
        f"`search` per command. Route every memory op through the `{provider}` adapter "
        f"(`providers/{provider}.md`) — never call a provider tool directly."
    )


def _setup_hint(root: Path) -> str | None:
    if workflow_config_path(root) is not None:
        return None
    if memory_provider_marker_path(root) is not None:
        return (
            "\n> **Tip:** This repo uses the in-repo memory marker. Run `/sw-setup` to customize "
            "providers, guardrails, and review settings."
        )
    return (
        "\n> **Tip:** Run `/sw-setup` to configure Shipwright providers, guardrails, and memory for this repo."
    )


def fetch_rule_summaries(root: Path, plugin_root: Path, config: dict) -> list[str]:
    override = os.environ.get("SW_RULES_SCRIPT", "").strip()
    if override:
        script: Path | None = Path(override)
    else:
        provider = resolve_memory_provider(root, config)
        script = None
        if provider:
            script = rules_script_for_provider(plugin_root, provider)
        if script is None:
            script = plugin_root / "providers" / "recallium-rules.sh"
    if not script.is_file():
        return []
    ok, rules = fetch_rules(root, plugin_root, config, rules_script=script)
    if not ok:
        return []
    allowlist_status, allowlist = load_allowlist(root)
    rules = filter_rules_by_allowlist(rules, allowlist_status, allowlist)
    lines: list[str] = []
    for item in rules:
        text = (item.get("summary") or "").strip()
        if text:
            lines.append(text)
    return lines


def _communication_defaults_path(plugin_root: Path) -> Path:
    return plugin_root / "core" / "sw-reference" / "communication-routing.defaults.json"


def _load_communication_routing(config: dict, plugin_root: Path) -> tuple[dict[str, dict[str, str]], str]:
    defaults_path = _communication_defaults_path(plugin_root)
    base_commands: dict[str, str] = {}
    base_skills: dict[str, str] = {}
    base_agents: dict[str, str] = {}
    default_intensity = "full"
    try:
        if defaults_path.is_file():
            parsed = json.loads(defaults_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                default_intensity = str(parsed.get("defaultIntensity", "full"))
                routing = parsed.get("routing", {})
                if isinstance(routing, dict):
                    commands = routing.get("commands", {})
                    if isinstance(commands, dict):
                        base_commands = {str(k): str(v) for k, v in commands.items()}
                    skills = routing.get("skills", {})
                    if isinstance(skills, dict):
                        base_skills = {str(k): str(v) for k, v in skills.items()}
                    agents = routing.get("agents", {})
                    if isinstance(agents, dict):
                        base_agents = {str(k): str(v) for k, v in agents.items()}
    except (OSError, ValueError, TypeError):
        pass

    comm = config.get("communication", {}) if isinstance(config, dict) else {}
    if isinstance(comm, dict):
        default_intensity = str(comm.get("defaultIntensity", default_intensity))
        routing = comm.get("routing", {})
        if isinstance(routing, dict):
            commands = routing.get("commands", {})
            if isinstance(commands, dict):
                base_commands = {**base_commands, **{str(k): str(v) for k, v in commands.items()}}
            skills = routing.get("skills", {})
            if isinstance(skills, dict):
                base_skills = {**base_skills, **{str(k): str(v) for k, v in skills.items()}}
            agents = routing.get("agents", {})
            if isinstance(agents, dict):
                base_agents = {**base_agents, **{str(k): str(v) for k, v in agents.items()}}

    merged = {"commands": base_commands, "skills": base_skills, "agents": base_agents}
    return merged, default_intensity


def resolve_communication_intensity(
    command: str,
    config: dict,
    plugin_root: Path,
    *,
    skill: str | None = None,
    agent: str | None = None,
    child_command: str | None = None,
) -> tuple[str, str]:
    """Return (intensity, source) for command -> skill -> agent -> default precedence."""
    routing, default_intensity = _load_communication_routing(config, plugin_root)
    commands = routing.get("commands", {}) if isinstance(routing, dict) else {}
    skills = routing.get("skills", {}) if isinstance(routing, dict) else {}
    agents = routing.get("agents", {}) if isinstance(routing, dict) else {}

    def _normalize(raw: str, source: str) -> tuple[str, str]:
        if raw in {"normal", "lite", "full", "ultra"}:
            return raw, source
        if raw == "inherit":
            return "inherit", source
        return default_intensity, "invalid-fallback"

    if command:
        raw = str(commands.get(command, default_intensity))
        source = "routing.commands" if command in commands else "defaultIntensity"
        value, source = _normalize(raw, source)
        if value == "inherit" and child_command:
            child_raw = str(commands.get(child_command, default_intensity))
            child_value, child_source = _normalize(child_raw, f"inherit.command:{child_command}")
            if child_value != "inherit":
                return child_value, child_source
        elif value != "inherit":
            return value, source

    if skill:
        raw = str(skills.get(skill, default_intensity))
        source = "routing.skills" if skill in skills else "defaultIntensity"
        value, source = _normalize(raw, source)
        if value != "inherit":
            return value, source

    if agent:
        raw = str(agents.get(agent, default_intensity))
        source = "routing.agents" if agent in agents else "defaultIntensity"
        value, source = _normalize(raw, source)
        if value != "inherit":
            return value, source

    fallback, source = _normalize(default_intensity, "defaultIntensity")
    if fallback == "inherit":
        return "full", "defaultIntensity:inherit-fallback"
    return fallback, source


def _dispatch_preflight_record(root: Path) -> dict | None:
    path = root / ".cursor" / "hooks" / "state" / "task-dispatch-preflight.json"
    try:
        if not path.is_file():
            return None
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    intensity = parsed.get("intensity")
    if intensity not in {"normal", "lite", "full", "ultra"}:
        return None
    consumed = parsed.get("consumedAt")
    if consumed:
        return None
    return parsed


def _load_caveman_core(plugin_root: Path) -> str:
    path = plugin_root / "core" / "communication" / "caveman-core.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def build_session_context(root: Path, plugin_root: Path, context_template: Path) -> str:
    parts: list[str] = []
    try:
        parts.append(context_template.read_text(encoding="utf-8").strip())
    except OSError:
        parts.append("This repo uses the Shipwright workflow plugin.")

    config = load_config(root)
    caveman_core = _load_caveman_core(plugin_root)
    if caveman_core:
        dispatch_preflight = _dispatch_preflight_record(root)
        if dispatch_preflight:
            intensity = str(dispatch_preflight.get("intensity"))
            source = "dispatch-preflight"
        else:
            intensity, source = resolve_communication_intensity("", config, plugin_root)
        parts.append(
            "\n## Caveman communication (bundled)\n\n"
            f"**Resolved intensity:** `{intensity}` ({source})\n\n"
            + caveman_core
        )

    memory = memory_binding(config, root)
    parts.append("\n## Resolved memory binding\n\n" + _memory_line(memory))

    hint = _setup_hint(root)
    if hint:
        parts.append(hint)

    provider = memory.get("provider", "in-repo")
    rules = fetch_rule_summaries(root, plugin_root, config)
    if rules:
        block = "\n\n".join(rules)
        parts.append(
            "\n## Standing memory rules (auto-injected)\n\n"
            "Provider-sourced guardrails (allowlist-filtered). Git state and frozen specs outrank memory.\n\n"
            f"<sw-guardrails provider=\"{provider}\">\n"
            + block
            + "\n</sw-guardrails>"
        )

    return "\n".join(parts)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _auto_sync_settings(config: dict) -> tuple[bool, int, int]:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    auto = memory.get("autoSync", {}) if isinstance(memory, dict) else {}

    enabled = bool(auto.get("enabled", True))
    if os.environ.get("PHASE_FLOW_MEMORY_SYNC_DISABLE", "").strip().lower() in {"1", "true", "yes", "on"}:
        enabled = False

    def _pos_int(value, fallback: int) -> int:
        try:
            parsed = int(value)
            return parsed if parsed > 0 else fallback
        except (TypeError, ValueError):
            return fallback

    min_turns = _pos_int(
        os.environ.get("PHASE_FLOW_MEMORY_SYNC_MIN_TURNS", auto.get("minTurns")),
        _DEFAULT_MIN_TURNS,
    )
    min_minutes = _pos_int(
        os.environ.get("PHASE_FLOW_MEMORY_SYNC_MIN_MINUTES", auto.get("minMinutes")),
        _DEFAULT_MIN_MINUTES,
    )
    return enabled, min_turns, min_minutes


def _load_state(state_path: Path) -> dict:
    fallback = {
        "version": 1,
        "lastRunAtMs": 0,
        "turnsSinceLastRun": 0,
        "lastTranscriptMtimeMs": None,
        "lastCompletedGenerationId": None,
    }
    try:
        if state_path.is_file():
            parsed = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict) and parsed.get("version") == 1:
                merged = {**fallback, **parsed}
                if merged.get("lastCompletedGenerationId") is None and merged.get("lastProcessedGenerationId"):
                    merged["lastCompletedGenerationId"] = merged.pop("lastProcessedGenerationId", None)
                return merged
    except (OSError, ValueError):
        pass
    return fallback


def _save_state(state_path: Path, state: dict) -> None:
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _transcript_mtime_ms(transcript_path) -> int | None:
    if not transcript_path:
        return None
    try:
        return int(Path(transcript_path).stat().st_mtime_ns / 1_000_000)
    except OSError:
        return None


def evaluate_stop_sync(payload: dict, root: Path) -> StopSyncResult:
    config = load_config(root)
    enabled, min_turns, min_minutes = _auto_sync_settings(config)
    if not enabled:
        return StopSyncResult()

    state_path = root / _STATE_RELPATH
    state = _load_state(state_path)

    generation_id = payload.get("generation_id")
    counted_turn = payload.get("status") == "completed" and payload.get("loop_count", 0) == 0

    if counted_turn and generation_id and generation_id == state.get("lastCompletedGenerationId"):
        return StopSyncResult()

    turns_since = state.get("turnsSinceLastRun", 0) + (1 if counted_turn else 0)
    now = _now_ms()

    last_run = state.get("lastRunAtMs", 0) or 0
    minutes_since = (now - last_run) / 60000 if last_run > 0 else float("inf")

    transcript_mtime = _transcript_mtime_ms(payload.get("transcript_path"))
    last_mtime = state.get("lastTranscriptMtimeMs")
    transcript_advanced = transcript_mtime is not None and (
        last_mtime is None or transcript_mtime > last_mtime
    )

    should_trigger = (
        counted_turn
        and turns_since >= min_turns
        and minutes_since >= min_minutes
        and transcript_advanced
    )

    if should_trigger:
        state["lastRunAtMs"] = now
        state["turnsSinceLastRun"] = 0
        state["lastTranscriptMtimeMs"] = transcript_mtime
        if counted_turn and generation_id:
            state["lastCompletedGenerationId"] = generation_id
        _save_state(state_path, state)
        return StopSyncResult(followup_message=_FOLLOWUP)

    state["turnsSinceLastRun"] = turns_since
    if counted_turn and generation_id:
        state["lastCompletedGenerationId"] = generation_id
    _save_state(state_path, state)
    return StopSyncResult()
