"""Gate bundle authority stays separate from consumer policy and evidence."""
import json
from pathlib import Path
import shutil

import pytest
import gate_manifest as gates
from merge_ready_enforcement import mandatory_gate_ids


@pytest.fixture
def runtime(tmp_path, repo_root, monkeypatch):
    bundle = tmp_path / "runtime"
    (bundle / "scripts").mkdir(parents=True)
    for name in ("check-gate.py", "resolve-model-tier.py"):
        (bundle / "scripts" / name).touch()
    reference = bundle / "core/sw-reference"
    reference.mkdir(parents=True)
    for name in ("gate-manifest.json", "kernel-classification.json"):
        shutil.copy2(repo_root / "core/sw-reference" / name, reference / name)
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(bundle / "scripts"))
    return bundle


def consumer(tmp_path):
    root = tmp_path / "consumer"
    root.mkdir()
    return root


def test_consumer_resolves_runtime_but_retains_own_overrides(tmp_path, runtime):
    root = consumer(tmp_path)
    (root / ".cursor").mkdir()
    (root / ".cursor/workflow.config.json").write_text(json.dumps({"gates": {"classOverrides": {"sw-simplify": "mandatory", "secret-scan": "advisory"}}}))
    assert gates.manifest_path(root) == runtime / gates.MANIFEST_REL
    manifest = gates.load_manifest(root)
    assert gates.resolve_gate_class("sw-simplify", manifest, root=root) == "mandatory"
    assert gates.resolve_gate_class("secret-scan", manifest, root=root) == "mandatory"
    ids = mandatory_gate_ids(root)
    assert "sw-simplify" in ids and "secret-scan" in ids
    assert not (root / "core").exists()


def test_consumer_cannot_replace_runtime_manifest_or_classification(tmp_path, runtime):
    root = consumer(tmp_path)
    (root / "core/sw-reference").mkdir(parents=True)
    for name in ("gate-manifest.json", "kernel-classification.json"):
        (root / "core/sw-reference" / name).write_text("{}")
    assert gates.load_manifest(root)["gates"]


@pytest.mark.parametrize("name", ["gate-manifest.json", "kernel-classification.json"])
@pytest.mark.parametrize("damage", ["missing", "corrupt", "not-object"])
def test_selected_runtime_missing_or_invalid_never_falls_back(tmp_path, runtime, name, damage):
    root = consumer(tmp_path)
    target = runtime / "core/sw-reference" / name
    if damage == "missing":
        target.unlink()
    else:
        target.write_text("[1]" if damage == "not-object" else "{invalid")
    with pytest.raises((FileNotFoundError, ValueError)):
        gates.load_manifest(root)


def test_changed_manifest_is_revalidated_in_same_process(tmp_path, runtime):
    root = consumer(tmp_path)
    assert gates.load_manifest(root)["gates"]
    (runtime / gates.MANIFEST_REL).write_text("{invalid")
    with pytest.raises(ValueError):
        gates.load_manifest(root)


def test_changed_classification_is_revalidated_in_same_process(tmp_path, runtime):
    root = consumer(tmp_path)
    assert gates.load_manifest(root)["gates"]
    path = runtime / "core/sw-reference/kernel-classification.json"
    data = json.loads(path.read_text())
    data["kernelChokepoints"] = []
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        gates.load_manifest(root)


def test_plugin_self_keeps_its_manifest(repo_root, runtime):
    assert gates.manifest_path(repo_root) == repo_root / gates.MANIFEST_REL
    assert gates.load_manifest(repo_root)["gates"]


@pytest.mark.parametrize("binding", ["missing", "untrusted", "relative"])
def test_invalid_runtime_binding_is_not_replaced_by_executor(tmp_path, monkeypatch, binding):
    root = consumer(tmp_path)
    path = tmp_path / binding
    if binding == "untrusted":
        path.mkdir()
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", "relative/path" if binding == "relative" else str(path))
    with pytest.raises(RuntimeError):
        gates.load_manifest(root)


def test_emitted_runtime_contains_required_manifest_and_lineage(tmp_path, runtime, repo_root, monkeypatch):
    monkeypatch.syspath_prepend(str(repo_root))
    from sw.emitter_base import copy_closed_sw_reference_files

    root = consumer(tmp_path)
    manifest = runtime / gates.MANIFEST_REL
    manifest.unlink()
    (runtime / "core/sw-reference/kernel-classification.json").unlink()
    copy_closed_sw_reference_files(repo_root / "core", runtime)
    assert manifest.read_bytes() == (repo_root / gates.MANIFEST_REL).read_bytes()
    assert gates.load_manifest(root)["gates"]
