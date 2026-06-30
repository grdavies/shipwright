"""Shared helpers for scripts/test fixture suites (R27)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from _sw import proc


def repo_root(from_file: str | Path | None = None) -> Path:
    if from_file is not None:
        return Path(from_file).resolve().parent.parent.parent
    return Path(__file__).resolve().parent.parent.parent


def content_path(root: Path, rel: str) -> Path:
    for base in (root, root / "core"):
        candidate = base / rel
        if candidate.is_file():
            return candidate
    return root / rel


class FixtureContext:
  """Fixture runner context mirroring fixture-lib.sh + ok/bad helpers."""

  def __init__(self, from_file: str | Path) -> None:
      self.root = repo_root(from_file)
      self.failures = 0
      self._cleanups: list[Path] = []
      self.env = os.environ.copy()
      self.env.setdefault("PYTHONPATH", str(self.root / "scripts"))
      if "PYTHONPATH" in self.env and str(self.root / "scripts") not in self.env["PYTHONPATH"].split(os.pathsep):
          self.env["PYTHONPATH"] = str(self.root / "scripts") + os.pathsep + self.env["PYTHONPATH"]

  def ok(self, name: str) -> None:
      print(f"OK  {name}")

  def bad(self, name: str) -> None:
      print(f"FAIL {name}")
      self.failures += 1

  def mktemp(self, prefix: str = "sw-fix-") -> Path:
      path = Path(tempfile.mkdtemp(prefix=prefix))
      self._cleanups.append(path)
      return path

  def cleanup(self) -> None:
      for path in self._cleanups:
          shutil.rmtree(path, ignore_errors=True)
      self._cleanups.clear()

  def script_path(self, rel: str) -> Path:
      rel = rel.replace(".sh", ".py")
      return self.root / rel

  def run_py(
      self,
      rel: str,
      *args: str,
      cwd: Path | None = None,
      env: dict[str, str] | None = None,
      input_text: str | None = None,
      check: bool = False,
  ) -> subprocess.CompletedProcess[str]:
      path = self.script_path(rel)
      cmd = [sys.executable, str(path), *args]
      merged = self.env.copy()
      if env:
          merged.update(env)
      return proc.run(cmd, cwd=str(cwd or self.root), env=merged, input_text=input_text, check=check)

  def run_git(self, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
      return proc.run(["git", *args], cwd=str(cwd), env=self.env, check=False)

  def jq(self, text: str, expr: str) -> str:
      completed = proc.run(
          [sys.executable, "-c", f"import json,sys; d=json.load(sys.stdin); print({expr})"],
          input_text=text,
      )
      return completed.stdout.strip()

  def load_json(self, text: str) -> object:
      return json.loads(text)

  def exit_code(self) -> int:
      return 1 if self.failures else 0
