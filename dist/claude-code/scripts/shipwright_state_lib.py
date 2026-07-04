"""Per-worktree Shipwright state helpers."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

def resolve_state_path(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    proc = subprocess.run(["git","-C",str(start),"rev-parse","--git-dir"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("error: not a git repository")
    git_dir = Path(proc.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (start / git_dir).resolve()
    return git_dir / "shipwright.json"

def read_json_arg(arg: str) -> str:
    return sys.stdin.read() if arg == "-" else arg

def cmd_path(start: Path) -> int:
    print(resolve_state_path(start)); return 0

def cmd_read(start: Path) -> int:
    state = resolve_state_path(start)
    print(state.read_text(encoding="utf-8") if state.is_file() else "{}")
    return 0

def _merge_write(path: Path, patch: dict) -> None:
    current = {}
    if path.is_file():
        current = json.loads(path.read_text(encoding="utf-8"))
    current.update(patch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def cmd_write(start: Path, arg: str) -> int:
    state = resolve_state_path(start)
    _merge_write(state, json.loads(read_json_arg(arg)))
    print(state); return 0

def cmd_override_add(start: Path, arg: str) -> int:
    state = resolve_state_path(start)
    current = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else {}
    overrides = current.get("overrides") if isinstance(current.get("overrides"), list) else []
    overrides.append(json.loads(read_json_arg(arg)))
    current["overrides"] = overrides
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(state); return 0

def cmd_dispatch_override_add(start: Path, arg: str) -> int:
    state = resolve_state_path(start)
    entry = json.loads(read_json_arg(arg))
    required = ("actor","timestamp","dispatchId","skippedFields")
    missing = [k for k in required if k not in entry]
    if missing:
        print(json.dumps({"verdict":"fail","error":"missing fields","missing":missing})); return 2
    if not isinstance(entry.get("skippedFields"), list) or not entry["skippedFields"]:
        print(json.dumps({"verdict":"fail","error":"skippedFields must be a non-empty list"})); return 2
    current = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else {}
    records = current.get("dispatchOverrides") if isinstance(current.get("dispatchOverrides"), list) else []
    records.append(entry)
    current["dispatchOverrides"] = records
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"verdict":"pass","count":len(records)})); print(state); return 0

def cmd_init(start: Path, arg: str) -> int:
    state = resolve_state_path(start)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(read_json_arg(arg).rstrip() + "\n", encoding="utf-8")
    print(state); return 0

def cmd_sync_ship_steps(root: Path, start: Path) -> int:
    steps_py = SCRIPT_DIR / "ship-phase-steps.py"
    if not steps_py.is_file():
        print("error: ship-phase-steps.py missing", file=sys.stderr)
        return 1
    proc = subprocess.run(
        [sys.executable, str(steps_py), "sync-state"],
        cwd=str(start),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print("error: ship-phase-steps sync-state failed", file=sys.stderr)
        return 1
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print("error: ship-phase-steps sync-state returned invalid JSON", file=sys.stderr)
        return 1
    phase_ship = raw.get("phaseShip")
    if not phase_ship:
        print(resolve_state_path(start))
        return 0
    state = resolve_state_path(start)
    current = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else {}
    current["phaseShip"] = phase_ship
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(state)
    return 0

def cmd_index(root: Path) -> int:
    def resolve_state_path_wt(worktree: str, gitdir: str):
        if not gitdir: return None
        gd = Path(gitdir)
        if not gd.is_absolute(): gd = (Path(worktree)/gd).resolve()
        else: gd = gd.resolve()
        return gd / "shipwright.json"
    try:
        out = subprocess.check_output(["git","-C",str(root),"worktree","list","--porcelain"], text=True)
    except subprocess.CalledProcessError:
        out = ""
    entries, block = [], {}
    for line in out.splitlines():
        if not line.strip():
            if block: entries.append(block); block = {}
            continue
        key, _, val = line.partition(" "); block[key] = val
    if block: entries.append(block)
    index = []
    for e in entries:
        wt_path = e.get("worktree",""); gitdir = e.get("gitdir","")
        sp = resolve_state_path_wt(wt_path, gitdir); state = {}
        if sp and sp.is_file():
            try: state = json.loads(sp.read_text(encoding="utf-8"))
            except json.JSONDecodeError: state = {"error":"invalid-json"}
        index.append({"worktree":wt_path,"branch":e.get("branch","").lstrip("refs/heads/"),
                        "statePath":str(sp) if sp else None,"state":state})
    print(json.dumps({"worktrees":index}, indent=2)); return 0

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent.parent
    start = Path.cwd()
    if not args: print(__doc__); return 1
    cmd = args[0]
    rest = args[1:]
    if cmd == "path": return cmd_path(start)
    if cmd == "read": return cmd_read(start)
    if cmd == "write": return cmd_write(start, rest[0]) if rest else 1
    if cmd == "override-add": return cmd_override_add(start, rest[0]) if rest else 1
    if cmd == "dispatch-override-add": return cmd_dispatch_override_add(start, rest[0]) if rest else 1
    if cmd == "init": return cmd_init(start, rest[0]) if rest else 1
    if cmd == "sync-ship-steps": return cmd_sync_ship_steps(root, start)
    if cmd == "index": return cmd_index(root)
    print(f"unknown command: {cmd}", file=sys.stderr); return 1
