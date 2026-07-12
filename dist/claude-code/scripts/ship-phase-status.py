#!/usr/bin/env python3
"""Write durable /sw-ship phase-mode terminal status."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import argparse, json, os, shutil, subprocess
    from pathlib import Path
    root = SCRIPT_DIR.parent
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--verdict"); parser.add_argument("--cause"); parser.add_argument("--phase")
    parser.add_argument("--out"); parser.add_argument("--head"); parser.add_argument("--pr")
    parser.add_argument("--gate-json")
    ns, _ = parser.parse_known_args(list(sys.argv[1:] if argv is None else argv))
    verdict, cause, phase, out, head, pr, gate_json = ns.verdict, ns.cause, ns.phase, ns.out, ns.head, ns.pr, ns.gate_json
    if verdict not in ("merge-ready-green","blocked"):
        print(json.dumps({"verdict":"fail","error":"--verdict merge-ready-green|blocked required"}), file=sys.stderr); return 2
    if head:
        from status_integrity import is_full_head_sha
        if not is_full_head_sha(head):
            print(json.dumps({"verdict":"fail","error":"--head must be a 40-character hexadecimal SHA"}), file=sys.stderr)
            return 2
    if verdict == "blocked" and not cause:
        print(json.dumps({"verdict":"fail","error":"--cause required when verdict is blocked"}), file=sys.stderr); return 2
    if not phase: phase = os.environ.get("SW_PHASE_SLUG","")
    if not phase:
        import shipwright_state_lib as ssl
        try:
            import io
            old = sys.stdout; sys.stdout = io.StringIO(); ssl.cmd_read(Path.cwd()); data = json.loads(sys.stdout.getvalue()); sys.stdout = old
            phase = data.get("phaseSlug","")
        except Exception: phase = ""
    phase = phase or "unknown"
    if not head:
        from status_integrity import resolve_write_head
        head = resolve_write_head(root)
    if verdict == "merge-ready-green" and not head:
        print(json.dumps({"verdict":"fail","error":"could not resolve HEAD for merge-ready-green"}), file=sys.stderr); return 2
    ship_chain_arg = None
    if verdict == "merge-ready-green":
        import ship_phase_steps as _sps
        _run = os.environ.get("SW_RUN_DIR", "").strip()
        _steps_path = (Path(_run) / "ship-steps.json") if _run else _sps.resolve_steps_path(root, phase, None)
        _steps = _sps.load_steps(_steps_path)
        if not _sps.ship_chain_is_complete(root, phase, _steps):
            print(json.dumps({"verdict":"fail","error":"ship-chain:incomplete","halt":"ship-chain"}), file=sys.stderr)
            return 2
        ship_chain_arg = "complete"
    if verdict == "merge-ready-green":
        import importlib.util
        gap_gate = SCRIPT_DIR / "gap-check-gate.py"
        spec = importlib.util.spec_from_file_location("gap_check_gate", gap_gate)
        if spec is not None and spec.loader is not None:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if mod.gap_check_halt_blocks_merge_ready(root, phase):
                print(json.dumps({"verdict":"fail","error":"gap-check-gate:halt-blocks-merge-ready"}), file=sys.stderr)
                return 2
        from merge_ready_enforcement import evaluate_mandatory_gate_evidence, seed_mandatory_pass_records

        if os.environ.get("SW_HARNESS") == "1":
            seed_mandatory_pass_records(root, phase, head_sha=head)
        evidence = evaluate_mandatory_gate_evidence(root, phase, head_sha=head)
        if evidence.get("verdict") != "pass":
            print(
                json.dumps(
                    {
                        "verdict": "fail",
                        "error": evidence.get("cause") or "merge-ready:mandatory-gate-evidence",
                        "halt": evidence.get("halt") or "merge-ready:mandatory-gate-evidence",
                        "gateId": evidence.get("gateId"),
                        "failures": evidence.get("failures") or [],
                    }
                ),
                file=sys.stderr,
            )
            return 2
    if not out:
        sw_run = os.environ.get("SW_RUN_DIR","")
        out = f"{sw_run.rstrip('/')}/status.json" if sw_run else str(root/f".cursor/sw-deliver-runs/{phase}/status.json")
    write_args = ["write","--verdict",verdict,"--phase",phase,"--out",out]
    if head: write_args += ["--head", head]
    if pr: write_args += ["--pr", pr]
    if cause: write_args += ["--cause", cause]
    if gate_json and Path(gate_json).is_file(): write_args += ["--gate-json", gate_json]
    if ship_chain_arg: write_args += ["--ship-chain", ship_chain_arg]
    ship_steps = os.environ.get("SHIP_STEPS_PATH","")
    if ship_steps and Path(ship_steps).is_file(): write_args += ["--ship-steps-path", ship_steps]
    import status_integrity
    old_argv = sys.argv; sys.argv = ["status_integrity.py", *write_args]
    try: status_integrity.main()
    finally: sys.argv = old_argv
    canonical = os.environ.get("SW_REPO_ROOT","")
    if not canonical or not Path(canonical).is_dir():
        p = subprocess.run(["git","-C",str(root),"rev-parse","--git-common-dir"], capture_output=True, text=True)
        common = p.stdout.strip() if p.returncode==0 else ""
        if common and common != ".git":
            common_p = Path(common)
            if not common_p.is_absolute(): common_p = (root/common_p).resolve()
            canonical = str(common_p.parent)
        else: canonical = str(root)
    if canonical and Path(canonical).is_dir():
        cout = Path(canonical)/f".cursor/sw-deliver-runs/{phase}/status.json"
        cout.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out, cout); os.chmod(cout, 0o600)
    if verdict == "blocked":
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "wave_state.py"),
                str(root),
                "state",
                "phase",
                "--slug",
                phase,
                "--status",
                "blocked",
            ],
            capture_output=True,
            text=True,
        )
    return 0

if __name__ == "__main__":
    run_module_main(main)
