#!/usr/bin/env python3
"""Validate model-routing.defaults.json coverage and tier references. Usage: model-routing-check.py [--config PATH] [--defaults PATH]"""
from __future__ import annotations

import sys

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Example workflow config JSON")
    parser.add_argument(
        "--defaults",
        default="",
        help="model-routing.defaults.json (default: core/sw-reference/...)",
    )
    parser.add_argument(
        "--communication-defaults",
        default="",
        help="communication-routing.defaults.json (optional parity check)",
    )
    parser.add_argument("--root", default="", help="Repository root (inferred from --config)")
    ns = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    config_path = ns.config
    cfg_p = Path(config_path).resolve()
    root_p = Path(ns.root).resolve() if ns.root else cfg_p.parents[2]
    defaults_path = ns.defaults or str(root_p / "core/sw-reference/model-routing.defaults.json")
    comm_defaults_path = ns.communication_defaults or str(
        root_p / "core/sw-reference/communication-routing.defaults.json"
    )
    root = str(root_p)
    config_path = str(cfg_p)
    violations = []

    defaults = json.loads(Path(defaults_path).read_text())
    cmd_map = defaults.get("routing", {}).get("commands", {})
    skill_map = defaults.get("routing", {}).get("skills", {})
    valid_tiers = {"cheap", "build", "mid", "deep", "inherit"}

    for key, tier in cmd_map.items():
        if tier not in valid_tiers:
            violations.append({"kind": "command", "key": key, "error": f"invalid tier {tier!r}"})
    for key, tier in skill_map.items():
        if tier not in valid_tiers:
            violations.append({"kind": "skill", "key": key, "error": f"invalid tier {tier!r}"})

    shipped_cmds = sorted(p.stem for p in (root_p / "core/commands").glob("sw-*.md"))
    for cmd in shipped_cmds:
        if cmd not in cmd_map:
            violations.append({"kind": "command", "key": cmd, "error": "missing from defaults"})

    shipped_skills = sorted(p.parent.name for p in (root_p / "core/skills").glob("*/SKILL.md"))
    for sk in shipped_skills:
        if sk not in skill_map:
            violations.append({"kind": "skill", "key": sk, "error": "missing from defaults"})

    comm_path = Path(comm_defaults_path)
    if comm_path.is_file():
        comm = json.loads(comm_path.read_text())
        comm_routing = comm.get("routing", {}) or {}
        comm_cmds = set((comm_routing.get("commands", {}) or {}).keys())
        comm_skills = set((comm_routing.get("skills", {}) or {}).keys())
        comm_agents = set((comm_routing.get("agents", {}) or {}).keys())
        model_cmds = set(cmd_map.keys())
        model_skills = set(skill_map.keys())
        model_agents = set(defaults.get("routing", {}).get("agents", {}).keys())
        if comm_cmds != model_cmds:
            only_comm = sorted(comm_cmds - model_cmds)
            only_model = sorted(model_cmds - comm_cmds)
            if only_comm or only_model:
                violations.append({
                    "kind": "parity",
                    "error": "communication vs model routing key mismatch",
                    "onlyCommunication": only_comm,
                    "onlyModel": only_model,
                })
        if comm_skills != model_skills:
            only_comm = sorted(comm_skills - model_skills)
            only_model = sorted(model_skills - comm_skills)
            if only_comm or only_model:
                violations.append({
                    "kind": "parity",
                    "error": "communication skills vs model skills mismatch",
                    "onlyCommunication": only_comm,
                    "onlyModel": only_model,
                })
        if comm_agents != model_agents:
            only_comm = sorted(comm_agents - model_agents)
            only_model = sorted(model_agents - comm_agents)
            if only_comm or only_model:
                violations.append({
                    "kind": "parity",
                    "error": "communication agents vs model agents mismatch",
                    "onlyCommunication": only_comm,
                    "onlyModel": only_model,
                })

    cfg_path = Path(config_path)
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text())
        tiers = (cfg.get("models") or {}).get("tiers") or {}
        for key, tier in {**cmd_map, **skill_map}.items():
            if tier != "inherit" and tier not in tiers:
                violations.append({"kind": "config", "key": key, "error": f"tier {tier!r} absent from example models.tiers"})

    if violations:
        print(json.dumps({"verdict": "fail", "violations": violations}, ensure_ascii=False))
        sys.exit(20)

    print(json.dumps({
        "verdict": "pass",
        "commandCount": len(cmd_map),
        "skillCount": len(skill_map),
        "communicationParityChecked": comm_path.is_file(),
    }))
    return 0


if __name__ == "__main__":
    run_module_main(main)
