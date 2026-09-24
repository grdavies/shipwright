from pathlib import Path
import json
import sys
import ship_pre_pr_smoke as smoke


def configure(root, command):
    (root / ".cursor").mkdir(exist_ok=True)
    (root / ".cursor/workflow.config.json").write_text(json.dumps({"verify": {"test": command}}))


def test_consumer_runs_own_command_and_propagates_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("_runner.run_pytest_scope", lambda *a, **k: (_ for _ in ()).throw(AssertionError("plugin suite invoked")))
    script = tmp_path / "verify.py"
    script.write_text("from pathlib import Path; Path('consumer-ran').write_text(str(Path.cwd())); raise SystemExit(7)")
    configure(tmp_path, f'"{sys.executable}" verify.py')
    assert smoke.run_pre_pr_smoke(tmp_path) == (7, "pre-pr-smoke:verify-exit-7")
    assert (tmp_path / "consumer-ran").read_text() == str(tmp_path)
    script.write_text("raise SystemExit(0)")
    assert smoke.run_pre_pr_smoke(tmp_path) == (0, None)


def test_consumer_missing_configuration_fails_closed(tmp_path):
    assert smoke.run_pre_pr_smoke(tmp_path) == (20, "pre-pr-smoke:verify-unconfigured")
    configure(tmp_path, "   ")
    assert smoke.run_pre_pr_smoke(tmp_path) == (20, "pre-pr-smoke:verify-unconfigured")


def test_internal_smoke_retains_scoped_pytest_and_restores_environment(tmp_path, monkeypatch):
    (tmp_path / "scripts/unit_tests").mkdir(parents=True)
    (tmp_path / "core/sw-reference").mkdir(parents=True)
    for marker in (".shipwright-dev", "version.txt", "scripts/check-gate.py"):
        (tmp_path / marker).touch()
    monkeypatch.setenv("SW_PHASE_ID", "original")
    monkeypatch.setenv("SW_TEST_SCOPE", "original")
    monkeypatch.setenv("SW_CHANGED_PATHS", "explicit.py")
    calls = []
    def run(root, *, scope):
        import os
        assert "SW_PHASE_ID" not in os.environ
        assert os.environ["SW_CHANGED_PATHS"] == "explicit.py"
        calls.append((root, scope))
        return 4
    monkeypatch.setattr("_runner.run_pytest_scope", run)
    assert smoke.run_pre_pr_smoke(tmp_path) == (4, "pre-pr-smoke:pytest-exit-4")
    assert calls == [(tmp_path, "phase")]
    import os
    assert os.environ["SW_PHASE_ID"] == "original"
    assert os.environ["SW_TEST_SCOPE"] == "original"
    assert os.environ["SW_CHANGED_PATHS"] == "explicit.py"
    monkeypatch.delenv("SW_CHANGED_PATHS")
    monkeypatch.setattr(smoke, "_seed_changed_paths_from_integration", lambda root: os.environ.__setitem__("SW_CHANGED_PATHS", "derived.py"))
    def seeded_run(root, *, scope):
        assert os.environ["SW_CHANGED_PATHS"] == "derived.py"
        return 0
    monkeypatch.setattr("_runner.run_pytest_scope", seeded_run)
    assert smoke.run_pre_pr_smoke(tmp_path) == (0, None)
    assert "SW_CHANGED_PATHS" not in os.environ


def test_consumer_with_python_unit_directory_still_uses_own_verification(tmp_path, monkeypatch):
    (tmp_path / "scripts/unit_tests").mkdir(parents=True)
    configure(tmp_path, f'"{sys.executable}" -c "raise SystemExit(9)"')
    monkeypatch.setattr("_runner.run_pytest_scope", lambda *a, **k: (_ for _ in ()).throw(AssertionError("plugin suite invoked")))
    assert smoke.run_pre_pr_smoke(tmp_path) == (9, "pre-pr-smoke:verify-exit-9")
