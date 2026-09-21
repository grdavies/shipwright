import sys,subprocess
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import worktree

def test_consumer_cwd_beats_runtime_checkout(tmp_path,monkeypatch):
 subprocess.run(['git','init','-q',str(tmp_path)],check=True)
 monkeypatch.chdir(tmp_path)
 assert worktree.repo_root().resolve()==tmp_path.resolve()

def test_explicit_consumer_beats_runtime_checkout(tmp_path):
 subprocess.run(['git','init','-q',str(tmp_path)],check=True)
 assert worktree.repo_root(tmp_path).resolve()==tmp_path.resolve()


@pytest.mark.parametrize('command', ['provision', 'teardown'])
def test_execute_worktree_commands_use_consumer_cwd(tmp_path, monkeypatch, command):
    import argparse
    import execute_plan
    import subprocess
    monkeypatch.setattr(execute_plan, 'resolve_sub_branch_ceiling', lambda root: 4)
    monkeypatch.setattr(execute_plan, 'active_sub_branch_count', lambda phase: 0)
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs['cwd'] == str(tmp_path)
        return subprocess.CompletedProcess(argv, 0, '{}', '')
    monkeypatch.setattr(subprocess, 'run', run)
    args = argparse.Namespace(task_ref='1.1', phase_slug='baseline', feature_slug='demo',
                              worktree_name='', branch='', base='feat/demo')
    action = getattr(execute_plan, 'cmd_' + command + '_sub_branch')
    with pytest.raises(SystemExit) as raised:
        action(tmp_path, args)
    assert raised.value.code == 0
    assert calls[0][0][2] == command
