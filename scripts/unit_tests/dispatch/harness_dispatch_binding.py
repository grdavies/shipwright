#!/usr/bin/env python3
"""PRD 050 A2 — dispatch-check unregistered parent model tier fixtures."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from _sw.vendor_paths import repo_root

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
ROOT = repo_root(__file__)
def run_dispatch(root: Path, cfg: dict, agent: str, parent: str) -> tuple[int, dict]:
    cfg_path = root / '.cursor' / 'workflow.config.json'
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg), encoding='utf-8')
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / 'scripts' / 'dispatch-check.py'),
            str(root),
            agent,
            parent,
            'child-model',
            'build',
            '0',
            'dispatch-1',
            'sw-doc',
            '',
        ],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {}
    return proc.returncode, data


def main() -> int:
    fail = 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = {
            'models': {
                'tiers': {'cheap': 'cheap-m', 'build': 'build-m', 'mid': 'mid-m', 'deep': 'deep-m'},
                'roles': {'builder': 'build'},
            }
        }
        ec, data = run_dispatch(root, cfg, 'sw-prd', 'unregistered-parent-model')
        if ec == 0 and data.get('verdict') == 'pass':
            print('OK  dispatch-unregistered-parent-delegated-atomic-passes')
        else:
            print('FAIL dispatch-unregistered-parent-delegated-atomic-passes', ec, data)
            fail += 1

        ec2, data2 = run_dispatch(root, cfg, 'correctness', 'unregistered-parent-model')
        if ec2 == 20 and data2.get('cause') == 'binding:no-model':
            print('OK  dispatch-unregistered-parent-reviewer-fails-closed')
        else:
            print('FAIL dispatch-unregistered-parent-reviewer-fails-closed', ec2, data2)
            fail += 1

        cfg_fb = {**cfg, 'dispatch': {'unregisteredParentModelTier': 'deep'}}
        ec3, data3 = run_dispatch(root, cfg_fb, 'correctness', 'unregistered-parent-model')
        if ec3 == 0 and data3.get('verdict') == 'pass' and data3.get('parentTierFallbackUsed'):
            print('OK  dispatch-unregistered-parent-reviewer-fallback-passes')
        else:
            print('FAIL dispatch-unregistered-parent-reviewer-fallback-passes', ec3, data3)
            fail += 1

    return 1 if fail else 0


if __name__ == '__main__':
    raise SystemExit(main())
