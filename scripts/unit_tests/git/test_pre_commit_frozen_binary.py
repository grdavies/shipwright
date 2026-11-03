"""Exercise the native frozen guard through real commits, including binary blobs."""
from __future__ import annotations

import io
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "core/hooks/pre-commit-frozen.py"
FROZEN = b"---\nfrozen: true\n---\n- [ ] 1.1 Original task\n"


def zipapp_bytes(version: int) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("__main__.py", f"print({version})\n")
        archive.writestr("payload.bin", b"\xff\xfe\x80" + bytes([version]))
    return b"#!/usr/bin/env python3\n" + stream.getvalue()


class FrozenBinaryHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="sw-frozen-binary-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        # Keep fixtures independent of the caller's Git index, hooks and signing.
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        self.git("init", "--template=")
        self.git("config", "user.name", "Freeze guard fixture")
        self.git("config", "user.email", "freeze-fixture@localhost")
        self.git("config", "core.hooksPath", str(self.repo / ".git/hooks"))
        scripts = self.repo / "scripts"
        scripts.mkdir()
        for name in ("check-frozen.py", "checkbox_diff.py"):
            shutil.copyfile(ROOT / "scripts" / name, scripts / name)
        self.git("add", "scripts")
        self.git("commit", "-m", "fixture: seed native guard helpers")
        hooks = self.repo / ".git/hooks"
        hooks.mkdir(exist_ok=True)
        self.hook = hooks / "pre-commit"
        self.hook.write_text(
            f"#!{sys.executable}\n" + HOOK.read_text(encoding="utf-8").split("\n", 1)[1],
            encoding="utf-8",
        )
        self.hook.chmod(0o755)

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=self.env,
            capture_output=True, text=True, check=check,
        )

    def seed(self, files: dict[str, bytes]) -> None:
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.git("add", ".")
        self.git("commit", "-m", "fixture: commit original blobs")

    def commit_change(self, name: str, content: bytes | None) -> subprocess.CompletedProcess[str]:
        if content is None:
            (self.repo / name).unlink()
        else:
            (self.repo / name).write_bytes(content)
        self.git("add", "-A")
        return self.git("commit", "-m", "fixture: exercise native frozen guard", check=False)

    def assert_blocked(self, result: subprocess.CompletedProcess[str], name: str) -> None:
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("frozen artifact(s) modified:", result.stderr)
        self.assertIn(f"  {name}\n", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("UnicodeDecodeError", result.stderr)

    def test_modified_binary_zipapp_can_commit(self) -> None:
        self.seed({"dist/runtime.pyz": zipapp_bytes(1)})
        result = self.commit_change("dist/runtime.pyz", zipapp_bytes(2))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("status", "--porcelain").stdout, "")

    def test_deleted_binary_zipapp_can_commit(self) -> None:
        self.seed({"runtime.pyz": zipapp_bytes(1)})
        result = self.commit_change("runtime.pyz", None)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unfrozen_plaintext_can_commit(self) -> None:
        self.seed({"draft.md": b"---\nfrozen: false\n---\nDraft\n"})
        result = self.commit_change("draft.md", b"Revised draft\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_frozen_plaintext_edit_is_blocked(self) -> None:
        self.seed({"tasks.md": FROZEN})
        self.assert_blocked(self.commit_change("tasks.md", FROZEN + b"Changed\n"), "tasks.md")

    def test_frozen_plaintext_deletion_is_blocked(self) -> None:
        self.seed({"tasks.md": FROZEN})
        self.assert_blocked(self.commit_change("tasks.md", None), "tasks.md")

    def test_frozen_checkbox_only_change_can_commit(self) -> None:
        self.seed({"tasks.md": FROZEN})
        result = self.commit_change("tasks.md", FROZEN.replace(b"[ ]", b"[x]"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_binary_cannot_mask_frozen_edit_in_same_commit(self) -> None:
        self.seed({"a-runtime.pyz": zipapp_bytes(1), "tasks.md": FROZEN})
        (self.repo / "a-runtime.pyz").write_bytes(zipapp_bytes(2))
        self.assert_blocked(self.commit_change("tasks.md", FROZEN + b"Changed\n"), "tasks.md")

    def test_invalid_utf8_does_not_hide_ascii_frozen_frontmatter(self) -> None:
        for original in (
            b"\xff\n" + FROZEN,
            FROZEN.replace(b"frozen:", b"title: \xff\nfrozen:"),
            FROZEN + b"\xff\n",
        ):
            with self.subTest(original=original):
                # Use new paths so every original is committed through the hook.
                name = f"invalid-{original.index(bytes([255]))}.md"
                self.seed({name: original})
                result = self.commit_change(name, original + b"Changed\n")
                self.assert_blocked(result, name)
                # Clear only the rejected fixture edit before the next subcase.
                self.git("restore", "--staged", "--worktree", name)

    def test_empty_index_is_allowed(self) -> None:
        result = self.git("commit", "--allow-empty", "-m", "fixture: no staged paths", check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_embedded_frozen_examples_allow_edits_and_deletion(self) -> None:
        examples = [
            b'#!/usr/bin/env python3\n_SOURCE = r"""\n' + FROZEN + b'"""\n',
            b"#!/bin/sh\ncat <<'DOC'\n" + FROZEN + b"DOC\n",
            b"# Example\n\n```yaml\n" + FROZEN + b"```\n",
            b"Meaningful prose before the example\n" + FROZEN,
            b"\xffprint('source')\n" + FROZEN,
        ]
        for index, original in enumerate(examples):
            with self.subTest(index=index):
                name = f"example-{index}.py"
                self.seed({name: original})
                edited = self.commit_change(name, original + b"# revised\n")
                self.assertEqual(edited.returncode, 0, edited.stderr)
                deleted = self.commit_change(name, None)
                self.assertEqual(deleted.returncode, 0, deleted.stderr)

    def test_frozen_baseline_cannot_be_unfrozen_by_new_preamble(self) -> None:
        for index, prefix in enumerate((b"# new preamble\n", b"#!/bin/sh\n", b"\xffsource\n")):
            with self.subTest(prefix=prefix):
                name = f"protected-{index}.py"
                self.seed({name: FROZEN})
                self.assert_blocked(self.commit_change(name, prefix + FROZEN), name)
                self.git("restore", "--staged", "--worktree", name)

    def test_bom_blank_crlf_frontmatter_remains_frozen(self) -> None:
        original = b"\xef\xbb\xbf\r\n \t\r\n" + FROZEN.replace(b"\n", b"\r\n")
        self.seed({"protected.bin": original})
        self.assert_blocked(self.commit_change("protected.bin", original.replace(b"frozen: true", b"frozen: false")), "protected.bin")

    def test_first_unfrozen_block_does_not_freeze_later_example(self) -> None:
        original = b"---\nfrozen: false\n---\n# Example\n" + FROZEN
        self.seed({"draft.md": original})
        result = self.commit_change("draft.md", original + b"Revised\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_hook_and_ci_frontmatter_boundaries_match(self) -> None:
        import check_frozen_scan as scanner

        spec = importlib.util.spec_from_file_location("readiness_frozen_hook", HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        cases = [
            (FROZEN, True),
            (b"\xff\n" + FROZEN, True),
            (FROZEN.replace(b"frozen:", b"title: \xff\nfrozen:"), True),
            (FROZEN + b"\xff\n", True),
            (b"\xef\xbb\xbf" + FROZEN, True),
            (b"\n\t\n" + FROZEN, True),
            (b"#!/bin/sh\n" + FROZEN, False),
            (b'payload = """\n' + FROZEN + b'"""\n', False),
            (b"\xffsource\n" + FROZEN, False),
            (b"# Example\n" + FROZEN, False),
            (b"\x00\n" + FROZEN, False),
            (b"\xef\xbf\xbd\n" + FROZEN, False),
            (b"---\nfrozen: false\n---\n" + FROZEN, False),
        ]
        self.seed({f"boundary-{index}.py": data for index, (data, _) in enumerate(cases)})
        with patch.object(scanner, "git_root", return_value=self.repo), patch.dict(os.environ, self.env, clear=True):
            for index, (_, expected) in enumerate(cases):
                name = f"boundary-{index}.py"
                with self.subTest(index=index):
                    self.assertEqual(hook._is_frozen_at_head(self.repo, name), expected)
                    self.assertEqual(scanner.is_frozen_at_ref(name, "HEAD"), expected)

    def test_ci_binary_cannot_mask_corrupt_frozen_document(self) -> None:
        original = b"\xff\n" + FROZEN
        self.seed({"runtime.pyz": zipapp_bytes(1), "tasks.md": original})
        base = self.git("rev-parse", "HEAD").stdout.strip()
        (self.repo / "runtime.pyz").write_bytes(zipapp_bytes(2))
        (self.repo / "tasks.md").write_bytes(b"New preamble\n" + original)
        self.git("add", "runtime.pyz", "tasks.md")
        tree = self.git("write-tree").stdout.strip()
        # Model an untrusted incoming commit through plumbing in this owned repo;
        # CI must reject it even when client hooks were never involved.
        commit = self.git("commit-tree", tree, "-p", base, "-m", "fixture: incoming frozen edit").stdout.strip()
        self.git("update-ref", "HEAD", commit, base)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/check_frozen_scan.py"), base],
                                cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason"], "frozen artifact modified")
        self.assertEqual(payload["files"], ["tasks.md"])


if __name__ == "__main__":
    unittest.main()
