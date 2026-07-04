#!/usr/bin/env python3
"""E2E/smoke verify adapter selector."""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main
import sw_resolve_plugin_root as spr

def cfg(config: Path | None, key: str, default: str) -> str:
    if config and config.is_file():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            cur = data
            for part in key.strip(".").split("."):
                if isinstance(cur, dict) and part in cur: cur = cur[part]
                else: return default
            return str(cur) if cur is not None else default
        except json.JSONDecodeError: return default
    return default

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    plugin_root = spr.resolve_plugin_root(SCRIPT_DIR)
    p = subprocess.run(["git","rev-parse","--show-toplevel"], capture_output=True, text=True)
    root = Path(p.stdout.strip()) if p.returncode==0 else Path.cwd()
    config = None
    i = 0
    while i < len(args):
        if args[i] == "--config" and i+1 < len(args): config = Path(args[i+1]); i += 2
        elif args[i] in ("-h","--help"): print("usage: verify-e2e [--config PATH]"); return 0
        else:
            print(json.dumps({"status":"failed","reason":"unknown argument"}), file=sys.stderr); return 2
    if config is None:
        for c in (root/".cursor/workflow.config.json", root/"workflow.config.json"):
            if c.is_file(): config = c; break
    provider = cfg(config, "verifyE2e.provider", "none")
    enabled = str(cfg(config, "verifyE2e.enabled", "false")).lower() == "true"
    if provider == "none" or not enabled:
        adapter = plugin_root/"providers/verify/none.sh"
        if (plugin_root/"providers/verify/none.py").is_file(): adapter = plugin_root/"providers/verify/none.py"
        return subprocess.run(["bash" if adapter.suffix==".sh" else sys.executable, str(adapter)]).returncode
    if not provider.replace("-","").isalnum():
        print(json.dumps({"status":"failed","exitCode":2,"name":"e2e","provider":provider,"skipped":False,"reason":"invalid provider id"})); return 2
    adapter = plugin_root/f"providers/verify/{provider}.sh"
    py_adapter = plugin_root/f"providers/verify/{provider}.py"
    if py_adapter.is_file(): adapter = py_adapter
    if not adapter.is_file():
        print(json.dumps({"status":"failed","exitCode":2,"name":"e2e","provider":provider,"skipped":False,"reason":"unknown verify provider"})); return 2
    changed = sorted(set((subprocess.run(["git","-C",str(root),"diff","--name-only"], capture_output=True, text=True).stdout or "").split() +
        (subprocess.run(["git","-C",str(root),"diff","--cached","--name-only"], capture_output=True, text=True).stdout or "").split() +
        (subprocess.run(["git","-C",str(root),"ls-files","--others","--exclude-standard"], capture_output=True, text=True).stdout or "").split()))
    env = {**os.environ, "SW_VERIFY_ROOT": str(root), "SW_CHANGED_FILES": "\n".join(changed), "SW_E2E_ROUTES": cfg(config,"verifyE2e.routes","[]"), "SW_E2E_CONFIG": str(config or "")}
    proc = subprocess.run(["bash" if adapter.suffix==".sh" else sys.executable, str(adapter)], capture_output=True, text=True, env=env)
    sys.stdout.write(proc.stdout)
    try:
        ec = json.loads(proc.stdout).get("exitCode")
        if ec is None: ec = proc.returncode
    except json.JSONDecodeError: ec = proc.returncode
    return int(ec if ec is not None else proc.returncode)
if __name__ == "__main__": run_module_main(main)
