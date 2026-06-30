#!/usr/bin/env python3
"""Regression suite for provider rule-script resolution (guardrail false-positive).

PRD 042 ported `providers/<provider>-rules.sh` to `<provider>-rules.py`, but
`rules_script_for_provider` kept resolving the `.sh` suffix only. The missing
`.sh` made the resolver return ``None``, which `evaluate_submit_guard` reported
as a provider-unreachable block — surfacing the misleading "cannot reach
Recallium" guardrail even when the memory provider was perfectly reachable.

These checks exercise the resolver and the end-to-end submit-guard path with no
``SW_RULES_SCRIPT`` override (the exact code path that regressed), so a future
suffix regression fails closed in CI.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CORE_HOOKS = ROOT / "core" / "hooks"


def _load_module(name: str):
    path = CORE_HOOKS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    if str(CORE_HOOKS) not in sys.path:
        sys.path.insert(0, str(CORE_HOOKS))
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _make_plugin_root(tmp: Path) -> Path:
    """Plugin root with .py provider adapters that emit deterministic rules."""
    providers = tmp / "plugin" / "providers"
    providers.mkdir(parents=True, exist_ok=True)
    stub = (
        "import json\n"
        "print(json.dumps({'ok': True, 'rules': [{'id': 'r1', 'summary': 's'}]}))\n"
    )
    for provider in ("recallium", "in-repo"):
        (providers / f"{provider}-rules.py").write_text(stub, encoding="utf-8")
    return providers.parent


def main() -> int:
    sw_hook_util = _load_module("sw_hook_util")
    guardrail_core = _load_module("guardrail_core")
    failures = 0

    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        plugin_root = _make_plugin_root(tmp)

        # 1) Resolver picks the .py adapter for every known provider.
        for provider in ("recallium", "in-repo"):
            resolved = sw_hook_util.rules_script_for_provider(plugin_root, provider)
            if resolved is not None and resolved.name == f"{provider}-rules.py" and resolved.is_file():
                print(f"OK  resolver picks {provider}-rules.py")
            else:
                print(f"FAIL resolver did not resolve {provider}-rules.py (got {resolved})")
                failures += 1

        # 2) .py preferred over a stale .sh sibling (partial-migration safety).
        legacy = plugin_root / "providers" / "recallium-rules.sh"
        legacy.write_text("#!/usr/bin/env bash\necho '{}'\n", encoding="utf-8")
        resolved = sw_hook_util.rules_script_for_provider(plugin_root, "recallium")
        if resolved is not None and resolved.suffix == ".py":
            print("OK  resolver prefers .py over stale .sh sibling")
        else:
            print(f"FAIL resolver should prefer .py over .sh (got {resolved})")
            failures += 1
        legacy.unlink()

        # 3) Unknown provider resolves to None (fail-safe, not a crash).
        if sw_hook_util.rules_script_for_provider(plugin_root, "bogus") is None:
            print("OK  resolver returns None for unknown provider")
        else:
            print("FAIL resolver should return None for unknown provider")
            failures += 1

        # 4) End-to-end: a reachable recallium provider must NOT trip the
        #    "cannot reach Recallium" block when no SW_RULES_SCRIPT override is set.
        workspace = tmp / "ws"
        (workspace / ".cursor").mkdir(parents=True, exist_ok=True)
        (workspace / ".cursor" / "workflow.config.json").write_text(
            json.dumps(
                {
                    "memory": {
                        "provider": "recallium",
                        "project": "regression",
                        "guardrails": {"enforceBeforeSubmit": True},
                    }
                }
            ),
            encoding="utf-8",
        )
        os.environ.pop("SW_RULES_SCRIPT", None)
        result = guardrail_core.evaluate_submit_guard(workspace, plugin_root)
        if result.allow:
            print("OK  reachable recallium provider allows submit (no false unreachable block)")
        else:
            print(f"FAIL submit guard blocked a reachable provider: {result.message}")
            failures += 1

    if failures:
        print(f"run-guardrail-rules-resolution-fixtures: FAIL ({failures})", file=sys.stderr)
        return 1
    print("run-guardrail-rules-resolution-fixtures: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
