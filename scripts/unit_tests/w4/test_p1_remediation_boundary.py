"""A refused auto-patch must distinguish repair handoff from merge readiness."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'code-review-apply-check.py'

@pytest.mark.parametrize('validated', [False, True])
def test_phase_p1_surfaces_repair_without_admitting_auto_apply(tmp_path, validated):
    finding = {'severity': 'P1', 'file': 'src/provider.py', 'suggested_fix': 'return value',
               'requires_verification': False}
    env = {k: v for k, v in os.environ.items() if k not in
           {'FINDING', 'PHASE_MODE', 'VALIDATED', 'APPLY_POLICY', 'REPO_ROOT'}}
    args = [sys.executable, str(SCRIPT), '--repo-root', str(tmp_path),
            '--finding', json.dumps(finding), '--phase-mode']
    if validated:
        args.append('--validated')
    result = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 20
    out = json.loads(result.stdout)
    assert out['eligible'] is False
    assert out['severity'] == 'P1'
    assert out['autoApply'] is False
    assert out['nextAction'] == 'surface-for-scoped-remediation'
    assert out['requiresAuthorization'] is True
    assert out['requiresVerification'] is True
    assert out['requiresFreshReview'] is True
    assert out['mergeReady'] is False
