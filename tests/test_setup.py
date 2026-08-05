import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "setup.py"
PLUGIN_SETUP = ROOT / "plugins" / "sol-luna-orchestration-kit" / "scripts" / "setup.py"


def _run(setup: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(setup), *arguments],
        cwd=setup.parents[1],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


class CrossPlatformSetupTests(unittest.TestCase):
    def test_preview_is_non_mutating_and_fresh_install_defaults_to_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            codex_home = home / ".codex"
            preview = _run(
                SETUP,
                "--preview-only",
                "--usage",
                "without-usage",
                "--home",
                str(home),
                "--codex-home",
                str(codex_home),
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertFalse(codex_home.exists())
            payload = json.loads(preview.stdout.splitlines()[-1])
            self.assertEqual(payload["luna_tier"], "fast")
            self.assertEqual(payload["status"], "dry-run")
            self.assertIn("No files were changed", preview.stderr)

    def test_setup_apply_and_doctor_complete_from_any_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            home.mkdir()
            codex_home = home / ".codex"
            installed = _run(
                SETUP,
                "--tier",
                "standard",
                "--home",
                str(home),
                "--codex-home",
                str(codex_home),
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            records = [json.loads(line) for line in installed.stdout.splitlines()]
            self.assertTrue(records[-1]["verification"]["ok"], records[-1])
            self.assertTrue((codex_home / "agents" / "luna_worker_standard.toml").is_file())
            self.assertTrue((home / ".agents" / "skills" / "sol-luna-status" / "SKILL.md").is_file())
            checked = _run(
                SETUP,
                "--doctor",
                "--home",
                str(home),
                "--codex-home",
                str(codex_home),
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            diagnosis = json.loads(checked.stdout)
            self.assertTrue(diagnosis["ok"], diagnosis)
            self.assertEqual(diagnosis["luna_tier"], "standard")

    def test_update_without_tier_preserves_the_installed_tier_and_usage_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            codex_home = home / ".codex"
            installed = _run(
                SETUP,
                "--tier",
                "standard",
                "--usage",
                "without-usage",
                "--home",
                str(home),
                "--codex-home",
                str(codex_home),
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            updated = _run(
                SETUP,
                "--update",
                "--home",
                str(home),
                "--codex-home",
                str(codex_home),
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)
            payload = json.loads(updated.stdout.splitlines()[-1])
            self.assertEqual(payload["luna_tier"], "standard")
            self.assertEqual(payload["usage"], "declined")
            self.assertIn("No restart is required", updated.stderr)

    def test_plugin_bundle_auto_avoids_duplicate_global_status_copy(self):
        self.assertTrue(PLUGIN_SETUP.is_file())
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            codex_home = home / ".codex"
            installed = _run(
                PLUGIN_SETUP,
                "--tier",
                "fast",
                "--home",
                str(home),
                "--codex-home",
                str(codex_home),
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertFalse((home / ".agents" / "skills" / "sol-luna-status").exists())


if __name__ == "__main__":
    unittest.main()
