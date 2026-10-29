import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TeamSetupTests(unittest.TestCase):
    def run_setup(self, root, *args):
        return subprocess.run([sys.executable, str(root / "scripts/setup.py"), *args],
                              capture_output=True, text=True, timeout=30)

    def test_current_defaults_preview_apply_doctor_and_root_preservation(self):
        for root in (ROOT, ROOT / "plugins/sol-luna-orchestration-kit"):
            with self.subTest(root=root), tempfile.TemporaryDirectory() as temporary:
                codex = Path(temporary) / ".codex"
                args = ("--codex-home", str(codex))
                preview = self.run_setup(root, *args, "--preview-only")
                self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
                self.assertFalse(codex.exists())
                self.assertEqual(json.loads(preview.stdout)["version"], "0.7.0")
                self.assertEqual(self.run_setup(root, *args, "--doctor").returncode, 1)
                installed = self.run_setup(root, *args)
                self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
                self.assertFalse((codex / "config.toml").exists())
                self.assertEqual(json.loads((codex / "sol-luna-team.json").read_text())["model"], "gpt-6-luna")
                self.assertEqual(self.run_setup(root, *args, "--doctor").returncode, 0)
                self.assertEqual(json.loads(self.run_setup(root, *args, "--update").stdout)["changes"], [])

    def test_old_switch_requires_explicit_legacy(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex = Path(temporary) / ".codex"
            result = self.run_setup(ROOT, "--codex-home", str(codex), "--tier", "fast")
            self.assertEqual(result.returncode, 2)
            self.assertFalse(codex.exists())
