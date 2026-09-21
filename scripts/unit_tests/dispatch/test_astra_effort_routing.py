"""Codex uses one model ID with explicit effort per routing tier."""
import json
import subprocess
import sys
from pathlib import Path
import pytest

SCRIPTS = Path(__file__).resolve().parents[2]

@pytest.fixture
def config(tmp_path):
    path = tmp_path / 'workflow.config.json'
    path.write_text(json.dumps({
        'models': {
            'tiers': dict.fromkeys(['cheap', 'build', 'mid', 'deep'], 'gpt-6-astra'),
            'reasoningEffortByTier': {'cheap': 'low', 'build': 'medium', 'mid': 'medium', 'deep': 'high'},
            'roles': {'builder': 'build', 'reviewer': 'deep'},
            'routing': {'agents': {'sw-coherence-reviewer': 'deep'}, 'commands': {'sw-execute': 'build', 'sw-review': 'deep', 'sw-status': 'cheap'}},
        },
        'communication': {'defaultIntensity': 'normal'},
    }))
    return path

def run(script, config, *args):
    result = subprocess.run([sys.executable, str(SCRIPTS / script), '--config', str(config), *args], capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout)

@pytest.mark.parametrize('command,effort', [('sw-execute', 'medium'), ('sw-review', 'high'), ('sw-status', 'low')])
def test_resolve_effort(config, command, effort):
    code, result = run('resolve-model-tier.py', config, '--command', command)
    assert code == 0, result
    assert result['modelId'] == 'gpt-6-astra'
    assert result['reasoningEffort'] == effort

@pytest.mark.parametrize('effort', ['none', 'invalid'])
def test_reject_invalid_astra_effort(config, effort):
    doc = json.loads(config.read_text())
    doc['models']['reasoningEffortByTier']['build'] = effort
    config.write_text(json.dumps(doc))
    code, result = run('resolve-model-tier.py', config, '--command', 'sw-execute')
    assert code != 0
    assert result['cause'] == 'binding:invalid-reasoning-effort'

def test_dispatch_carries_effort_and_explicit_parent_tier(config):
    code, result = run('dispatch-check.py', config, '--agent', 'sw-coherence-reviewer', '--command', 'sw-review', '--parent-model', 'gpt-6-astra', '--parent-tier', 'deep')
    assert code == 0, result
    assert result['reasoningEffort'] == 'high'
    assert result['parentTier'] == 'deep'

def test_parent_tier_cannot_claim_another_model(config):
    doc = json.loads(config.read_text())
    doc['models']['tiers']['deep'] = 'composer-2.5'
    config.write_text(json.dumps(doc))
    code, result = run('dispatch-check.py', config, '--agent', 'sw-coherence-reviewer', '--command', 'sw-review', '--parent-model', 'gpt-6-astra', '--parent-tier', 'deep')
    assert code != 0
    assert result['cause'] == 'binding:parent-tier-model-mismatch'


def test_default_config_comes_from_consumer(config):
    consumer = config.parent
    directory = consumer / ".shipwright"
    directory.mkdir()
    (directory / "workflow.config.json").write_text(config.read_text())
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "resolve-model-tier.py"), "--command", "sw-execute"],
        cwd=consumer, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert (payload["modelId"], payload["reasoningEffort"]) == ("gpt-6-astra", "medium")


def test_missing_effort_preserves_existing_default(config):
    doc = json.loads(config.read_text())
    del doc['models']['reasoningEffortByTier']
    config.write_text(json.dumps(doc))
    code, result = run('resolve-model-tier.py', config, '--command', 'sw-execute')
    assert code == 0, result
    assert 'reasoningEffort' not in result


def test_explicit_cheap_parent_still_fails_reviewer_floor(config):
    code, result = run('dispatch-check.py', config, '--agent', 'sw-coherence-reviewer', '--command', 'sw-review', '--parent-model', 'gpt-6-astra', '--parent-tier', 'cheap')
    assert code != 0
    assert result['cause'] == 'binding:no-model'
    assert result['parentTier'] == 'cheap'


def test_dispatch_defaults_to_consumer_config(config):
    consumer = config.parent
    directory = consumer / '.shipwright'
    directory.mkdir()
    (directory / 'workflow.config.json').write_text(config.read_text())
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / 'dispatch-check.py'), '--agent', 'sw-coherence-reviewer', '--command', 'sw-review', '--parent-model', 'gpt-6-astra', '--parent-tier', 'deep'],
        cwd=consumer, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert (payload['modelId'], payload['reasoningEffort']) == ('gpt-6-astra', 'high')
