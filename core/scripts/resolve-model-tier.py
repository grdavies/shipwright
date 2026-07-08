#!/usr/bin/env python3
"""Resolve semantic model tier → concrete dispatch ID from workflow config + bundled defaults."""
from __future__ import annotations

import sys

from _sw.cli import build_parser, run_module_main


def main(argv: list[str] | None = None) -> int:
    import json
    import sys
    from pathlib import Path

    parser = build_parser(
        prog="resolve-model-tier",
        description="Resolve semantic model tier -> concrete dispatch ID (command -> skill -> agent -> tier).",
    )
    parser.add_argument("--tier", default="")
    parser.add_argument("--command", default="")
    parser.add_argument("--skill", default="")
    parser.add_argument("--agent", default="")
    parser.add_argument("--delegate", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--defaults", default="")
    args = parser.parse_args(argv)

    if not any((args.tier, args.command, args.skill, args.agent)):
        parser.print_help()
        return 2

    root = Path(__file__).resolve().parent.parent
    defaults_path = args.defaults or str(root / "core/sw-reference/model-routing.defaults.json")
    config_path = args.config
    if not config_path:
        for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
            if candidate.is_file():
                config_path = str(candidate)
                break

    tier_arg, command, skill, agent, delegate = (
        args.tier,
        args.command,
        args.skill,
        args.agent,
        args.delegate,
    )
    SEMANTIC = {"cheap", "build", "mid", "deep", "inherit"}


    def load_json(path: str) -> dict:
        p = Path(path)
        if not p.is_file():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))


    def fail(msg: str, code: int = 20, **extra: object) -> None:
        print(json.dumps({"verdict": "fail", "error": msg, **extra}))
        sys.exit(code)


    defaults_doc = load_json(defaults_path)
    base_cmd = defaults_doc.get("routing", {}).get("commands", {})
    base_skill = defaults_doc.get("routing", {}).get("skills", {})
    base_agents = defaults_doc.get("routing", {}).get("agents", {})

    cfg = load_json(config_path) if config_path else {}
    models = cfg.get("models", {}) if isinstance(cfg, dict) else {}
    tiers = models.get("tiers", {}) if isinstance(models, dict) else {}
    aliases = models.get("aliases", {}) if isinstance(models, dict) else {}
    roles = models.get("roles", {}) if isinstance(models, dict) else {}
    routing = models.get("routing", {}) if isinstance(models, dict) else {}
    cmd_routing = {**base_cmd, **(routing.get("commands", {}) if isinstance(routing.get("commands"), dict) else {})}
    skill_routing = {**base_skill, **(routing.get("skills", {}) if isinstance(routing.get("skills"), dict) else {})}
    agent_routing = {**base_agents, **(routing.get("agents", {}) if isinstance(routing.get("agents"), dict) else {})}


    def resolve_tier_name(name: str, source: str) -> None:
        if name in aliases:
            name = aliases[name]
            source = f"{source}:alias"
        if name not in SEMANTIC:
            fail(f"unknown tier {name!r}")
        if name == "inherit":
            print(json.dumps({"tier": "inherit", "modelId": None, "source": source}))
            sys.exit(0)
        if name not in tiers:
            fail(f"tier {name!r} not in models.tiers")
        print(json.dumps({"tier": name, "modelId": tiers[name], "source": source}))
        sys.exit(0)


    NATIVE_PANEL_IDS = {
        "correctness", "security", "adversarial", "data-migration", "maintainability",
        "scope-fidelity", "testing", "performance", "api-contract", "reliability",
        "ui-ux", "type-design", "comment-accuracy", "ai-native",
    }


    def is_bound_agent(agent_id: str) -> bool:
        return (agent_id.startswith("sw-") and agent_id.endswith("-reviewer")) or agent_id in NATIVE_PANEL_IDS


    def has_explicit_agent_routing(agent_id: str) -> bool:
        return agent_id in agent_routing


    def resolve_inherit_agent_fallback(cmd: str, agent_id: str, source: str) -> None:
        """R18: an `inherit` orchestrator dispatching a concrete sub-agent must not dead-end
        on `binding:no-model` for an agent absent from `models.routing.agents`. Resolution
        order: agent map -> `models.roles` fallback -> actionable remediation (never a bare
        inherit/None pass-through, and never forces the caller into inline authoring)."""
        if agent_id in agent_routing:
            resolve_tier_name(agent_routing[agent_id], f"{source}:agent-map:{agent_id}")
        role_tier = roles.get("builder")
        if role_tier:
            resolve_tier_name(role_tier, f"{source}:roles.builder-fallback")
        fail(
            f"inherit orchestrator {cmd!r} has no concrete-model route for unmapped agent {agent_id!r}",
            cause="no-model:remediation",
            agent=agent_id,
            command=cmd,
            remediation=(
                f"add models.routing.agents.{agent_id!r} or set models.roles.builder "
                "in workflow.config.json"
            ),
        )

    def resolve_command_tier(cmd: str) -> None:
        if cmd not in cmd_routing:
            fail(f"missing routing.commands entry for {cmd!r}")
        raw = cmd_routing[cmd]
        source = "routing.commands"
        if raw == "inherit":
            if delegate:
                if delegate not in cmd_routing:
                    fail(f"missing routing.commands entry for delegate {delegate!r}")
                child_raw = cmd_routing[delegate]
                source = f"inherit:{delegate}"
                if child_raw == "inherit":
                    fail(f"delegate {delegate!r} also inherits — cannot resolve")
                resolve_tier_name(child_raw, source)
            if agent:
                resolve_inherit_agent_fallback(cmd, agent, source)
            resolve_tier_name("inherit", source)
        resolve_tier_name(raw, source)


    def resolve_agent_tier(agent_id: str) -> None:
        reviewer_tier = roles.get("reviewer", roles.get("builder", "build"))
        if agent_id in agent_routing:
            resolve_tier_name(agent_routing[agent_id], "routing.agents")
        resolve_tier_name(reviewer_tier, "roles.reviewer-default")


    if tier_arg:
        resolve_tier_name(tier_arg, "tier")

    # R39b precedence: explicit bound-agent routing → command → skill → agent.
    # A bound agent with an explicit routing.agents entry wins over both --command
    # and --skill (gap-088) — a persona's own model tier must not be displaced by
    # the orchestrating skill's (often `inherit`) tier just because both were passed
    # to the same dispatch-check call.
    agent_wins = bool(agent) and is_bound_agent(agent) and has_explicit_agent_routing(agent)
    lookup_command = command
    lookup_agent = agent
    if agent and command:
        if agent_wins:
            lookup_command = ""
        else:
            lookup_agent = ""

    if lookup_command:
        resolve_command_tier(lookup_command)

    if skill and not agent_wins:
        if skill not in skill_routing:
            fail(f"missing routing.skills entry for {skill!r}")
        raw = skill_routing[skill]
        resolve_tier_name(raw, "routing.skills")

    if lookup_agent:
        resolve_agent_tier(lookup_agent)

    fail("no lookup performed")
    return 0


if __name__ == "__main__":
    run_module_main(main)
