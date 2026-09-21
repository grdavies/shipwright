import sys
import subprocess
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

def test_consumer_plan_stamps(tmp_path):
    from wave_plan_validate import plan_stamps
    stamps = plan_stamps(tmp_path)
    assert stamps['kernelVersion']
    assert stamps['guidelineVersion']
    assert not (tmp_path / 'core').exists()

def test_local_invalid_classification_is_not_hidden(tmp_path):
    from kernel_classification import load_classification
    path = tmp_path / 'core/sw-reference/kernel-classification.json'
    path.parent.mkdir(parents=True)
    path.write_text('[]')
    with pytest.raises(ValueError):
        load_classification(tmp_path)

@pytest.mark.parametrize("branch", ["feat/demo", "feat/other"])
def test_fresh_entry_binds_explicit_task_before_adoption(tmp_path, monkeypatch, branch, capsys):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    import wave_deliver_loop as loop
    import wave_deliver as entry
    task = 'docs/prds/001-demo/tasks-001-demo.md'
    path = tmp_path / task
    path.parent.mkdir(parents=True)
    path.write_text('---\nfrozen: true\ntopic: demo\n---\n')
    state = {'target': {'branch': branch}, 'orchestratorWorktree': {'path': str(tmp_path)}}
    monkeypatch.setattr(loop, 'load_state', lambda *a: state)
    monkeypatch.setattr(loop, 'resolve_plan_with_adoption', lambda *a: ({}, state))
    monkeypatch.setattr(loop, 'should_attempt_orch_cwd_adopt', lambda *a, **k: True)
    monkeypatch.setattr(entry, 'require_task_list_frozen', lambda *a: None)
    class ReachedAdopt(Exception): pass
    def adopt(root, actual, plan, **kwargs):
        assert actual['source_task_list'] == task
        assert 'runId' not in actual
        raise ReachedAdopt
    monkeypatch.setattr(loop, 'try_adopt_recorded_orchestrator_worktree', adopt)
    if branch != 'feat/demo':
        with pytest.raises(SystemExit):
            loop.cmd_deliver_loop(tmp_path, ['--task-list', task])
        assert 'adopt:task-list-target-mismatch' in capsys.readouterr().out
        assert 'source_task_list' not in state
    else:
        with pytest.raises(ReachedAdopt):
            loop.cmd_deliver_loop(tmp_path, ['--task-list', task])


def test_consumer_execute_dependency_rules(tmp_path):
    from execute_plan import load_dependency_rules
    assert isinstance(load_dependency_rules(tmp_path)['rules'], list)
    assert not (tmp_path / 'core').exists()


def test_invalid_consumer_execute_rules_are_not_hidden(tmp_path, capsys):
    from execute_plan import load_dependency_rules
    path = tmp_path / 'core/sw-reference/execute-dependency-rules.json'
    path.parent.mkdir(parents=True)
    path.write_text('[]')
    with pytest.raises(SystemExit):
        load_dependency_rules(tmp_path)
    assert 'invalid execute-dependency-rules.json shape' in capsys.readouterr().out
