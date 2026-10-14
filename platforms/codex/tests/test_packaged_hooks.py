"""Run installed Codex hook commands without source-tree import assistance."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

REPO = Path(__file__).resolve().parents[3]
CODEX = REPO / "platforms" / "codex"


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    sys.path.insert(0, str(CODEX))
    spec = importlib.util.spec_from_file_location("codex_hooks_generator", CODEX / "generator.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    out = tmp_path_factory.mktemp("codex package with spaces") / "plugin"
    generator.generate(out, repo_root=REPO, core_root=REPO / "core", enable_mcp=False)
    return out


def run_hook(package, workspace, event, **fields):
    document = json.loads((package / "hooks/hooks.json").read_text())
    command = document["hooks"][event][0]["hooks"][0]["command"]
    payload = {"hook_event_name": event, "cwd": str(workspace), **fields}
    return subprocess.run(
        ["/bin/sh", "-c", command], input=json.dumps(payload), text=True,
        capture_output=True, cwd=workspace, timeout=20,
        # No source-tree PYTHONPATH, harness variables, or provider credentials.
        env={"PATH": os.path.dirname(sys.executable) + os.pathsep + os.defpath,
             "PLUGIN_ROOT": str(package), "PYTHONDONTWRITEBYTECODE": "1"},
    )


def record_prework(workspace):
    path = workspace / ".cursor/hooks/state/memory-prework-search.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"outcome": "memory:none", "expiresAt": int(time.time()) + 300,
                                "mutationBudget": 50, "mutationsUsed": 0}))
    return path


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit", "PreToolUse",
                                     "PostToolUse", "Stop", "SubagentStart", "SubagentStop"])
def test_all_registered_launchers_are_standalone(package, tmp_path, event):
    result = run_hook(package, tmp_path, event, tool_name="Read", tool_input={"path": "x"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
    assert not result.stderr
    assert not list(tmp_path.iterdir())
    assert (package / "shipwright.pyz").is_file()


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit", "PostToolUse",
                                     "Stop", "SubagentStart", "SubagentStop"])
def test_non_pretool_events_do_not_consume_mutation_records(package, tmp_path, event):
    record = record_prework(tmp_path)
    original = record.read_bytes()
    result = run_hook(package, tmp_path, event, tool_name="apply_patch",
                      tool_input={"command": "*** Begin Patch\n*** End Patch"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
    assert record.read_bytes() == original


def test_codex_edit_denial_uses_native_protocol(package, tmp_path):
    result = run_hook(package, tmp_path, "PreToolUse", tool_name="apply_patch",
                      tool_input={"command": "*** Begin Patch\n*** End Patch"})
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    decision = output["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    assert "pre-work memory search" in decision["permissionDecisionReason"]
    assert "permission" not in output
    assert not result.stderr


def test_codex_edit_consumes_exactly_one_prework_use(package, tmp_path):
    record = record_prework(tmp_path)
    result = run_hook(package, tmp_path, "PreToolUse", tool_name="apply_patch",
                      tool_input={"command": "*** Begin Patch\n*** End Patch"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
    assert json.loads(record.read_text())["mutationsUsed"] == 1
    assert not result.stderr


def test_codex_bash_read_uses_bundled_script_dependencies(package, tmp_path):
    result = run_hook(package, tmp_path, "PreToolUse", tool_name="Bash",
                      tool_input={"command": "printf 'read only'"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
    assert not result.stderr


def test_codex_bash_tracked_write_is_denied(package, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "tracked.txt").write_text("original\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)
    result = run_hook(package, tmp_path, "PreToolUse", tool_name="Bash",
                      tool_input={"command": "echo changed > tracked.txt"})
    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "tracked-file mutations" in decision["permissionDecisionReason"]
    assert (tmp_path / "tracked.txt").read_text() == "original\n"


def test_model_binding_preserves_tool_arguments(package, tmp_path):
    # The core policy is a boundary here: this checks Codex replacement-input
    # semantics, independently of model selection and nonce lifecycle tests.
    driver = '''
import json, sys
sys.path.insert(0, sys.argv[1] + '/hooks')
import hook_adapter
hooks = hook_adapter._core_hooks_dir()
sys.path.insert(0, str(hooks))
from sw_hook_util import ensure_plugin_scripts_importable
ensure_plugin_scripts_importable(hooks.parent.parent)
import before_task_dispatch
before_task_dispatch.evaluate_pre_tool_use = lambda payload, root: before_task_dispatch.DispatchResult(
    verdict='pass', model_id='test-model', dispatch_id='dispatch-1', intensity='normal')
hook_adapter.before_task_dispatch_stdio(json.load(sys.stdin))
'''
    payload = {"tool_name": "Task", "cwd": str(tmp_path), "tool_input": {
        "prompt": "keep this prompt", "description": "keep this description",
        "metadata": {"command": "sw-review", "trace": "keep this trace"}}}
    result = subprocess.run([sys.executable, "-I", "-B", "-c", driver, str(package)],
                            input=json.dumps(payload), capture_output=True, text=True,
                            cwd=tmp_path, timeout=20)
    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "allow"
    updated = decision["updatedInput"]
    assert updated["prompt"] == payload["tool_input"]["prompt"]
    assert updated["description"] == payload["tool_input"]["description"]
    assert updated["metadata"] == {"command": "sw-review", "trace": "keep this trace",
                                   "dispatchId": "dispatch-1", "intensity": "normal"}
    assert updated["model"] == "test-model"


def test_broken_runtime_denies_instead_of_silently_allowing(package, tmp_path):
    import shutil

    broken = tmp_path / "broken"
    shutil.copytree(package / "hooks", broken / "hooks")
    shutil.copytree(package / "core/hooks", broken / "core/hooks")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = run_hook(broken, workspace, "PreToolUse", tool_name="Read", tool_input={})
    assert result.returncode == 0
    decision = json.loads(result.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "ModuleNotFoundError" in result.stderr
    assert not list(workspace.iterdir())


@pytest.mark.parametrize("raw", ["[]", "not json", '{}', '{"hook_event_name":"Unknown"}'])
def test_invalid_payload_is_reported_without_echoing_input(package, tmp_path, raw):
    result = subprocess.run([sys.executable, "-I", "-B", str(package / "hooks/codex-hook.py")],
                            input=raw, text=True, capture_output=True, cwd=tmp_path, timeout=20)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == "Shipwright Codex hook: invalid event payload"
