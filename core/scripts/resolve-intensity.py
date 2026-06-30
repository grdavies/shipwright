#!/usr/bin/env python3
"""Resolve caveman communication intensity using command -> skill -> agent -> default precedence."""
from __future__ import annotations

import sys

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    import json
    import sys
    from pathlib import Path

    command_name, skill_name, agent_name, child_command, config_path, defaults_path = sys.argv[1:7]
    ALLOWED = {"normal", "lite", "full", "ultra", "inherit"}


    def load_json(path: str) -> dict:
        p = Path(path)
        if not p.is_file():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))


    defaults_doc = load_json(defaults_path)
    defaults_routing = defaults_doc.get("routing", {}) if isinstance(defaults_doc, dict) else {}
    base_commands = defaults_routing.get("commands", {}) if isinstance(defaults_routing, dict) else {}
    base_skills = defaults_routing.get("skills", {}) if isinstance(defaults_routing, dict) else {}
    base_agents = defaults_routing.get("agents", {}) if isinstance(defaults_routing, dict) else {}
    default_intensity = str(defaults_doc.get("defaultIntensity", "full"))

    cfg = load_json(config_path) if config_path else {}
    comm = cfg.get("communication", {}) if isinstance(cfg, dict) else {}
    routing = comm.get("routing", {}) if isinstance(comm, dict) else {}
    cfg_commands = routing.get("commands", {}) if isinstance(routing, dict) else {}
    cfg_skills = routing.get("skills", {}) if isinstance(routing, dict) else {}
    cfg_agents = routing.get("agents", {}) if isinstance(routing, dict) else {}
    if isinstance(comm, dict):
        default_intensity = str(comm.get("defaultIntensity", default_intensity))

    commands = {**base_commands, **(cfg_commands if isinstance(cfg_commands, dict) else {})}
    skills = {**base_skills, **(cfg_skills if isinstance(cfg_skills, dict) else {})}
    agents = {**base_agents, **(cfg_agents if isinstance(cfg_agents, dict) else {})}


    def normalize(value: str, source: str) -> tuple[str, str]:
        if value in {"normal", "lite", "full", "ultra"}:
            return value, source
        if value == "inherit":
            return "inherit", source
        if value.startswith("wenyan"):
            print(
                json.dumps(
                    {
                        "verdict": "fail",
                        "cause": "binding:no-intensity",
                        "error": "wenyan intensity rejected",
                        "source": source,
                    }
                )
            )
            sys.exit(20)
        return default_intensity, "invalid-fallback"


    def resolve() -> tuple[str, str]:
        if command_name:
            raw = str(commands.get(command_name, default_intensity))
            source = "routing.commands" if command_name in commands else "defaultIntensity"
            if raw == "inherit" and child_command:
                child_raw = str(commands.get(child_command, default_intensity))
                if child_raw != "inherit":
                    value, _ = normalize(child_raw, f"inherit.command:{child_command}")
                    if value != "inherit":
                        return value, f"inherit.command:{child_command}"
                source = "inherit.command-unresolved"
            else:
                value, source = normalize(raw, source)
                if value != "inherit":
                    return value, source
        if skill_name:
            raw = str(skills.get(skill_name, default_intensity))
            source = "routing.skills" if skill_name in skills else "defaultIntensity"
            value, source = normalize(raw, source)
            if value != "inherit":
                return value, source
        if agent_name:
            raw = str(agents.get(agent_name, default_intensity))
            source = "routing.agents" if agent_name in agents else "defaultIntensity"
            value, source = normalize(raw, source)
            if value != "inherit":
                return value, source
        value, source = normalize(default_intensity, "defaultIntensity")
        if value == "inherit":
            return "full", "defaultIntensity:inherit-fallback"
        return value, source


    intensity, source = resolve()
    if intensity not in {"normal", "lite", "full", "ultra"}:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "cause": "binding:no-intensity",
                    "command": command_name or None,
                    "skill": skill_name or None,
                    "agent": agent_name or None,
                    "source": source,
                    "remediation": "set communication.defaultIntensity or routing entries to normal|lite|full|ultra",
                }
            )
        )
        sys.exit(20)

    print(
        json.dumps(
            {
                "command": command_name or None,
                "skill": skill_name or None,
                "agent": agent_name or None,
                "intensity": intensity,
                "source": source,
            }
        )
    )
    return 0


if __name__ == "__main__":
    run_module_main(main)
