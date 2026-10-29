import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import install as legacy, team_install, team_settings

ROOT = Path(__file__).resolve().parents[1]


class TeamInstallTests(unittest.TestCase):
    def test_untracked_fixed_model_policy_stops_without_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / ".codex"
            home.mkdir()
            target = home / "AGENTS.md"
            original = "## Role-based subagent policy\nThe Sol root stays on `gpt-5.6-sol`.\n"
            target.write_text(original)
            with self.assertRaisesRegex(legacy.InstallError, "untracked_legacy_instructions_requires_review"):
                team_install.install(ROOT, home, apply=True)
            self.assertEqual(target.read_text(), original)
            self.assertEqual(sorted(p.name for p in home.iterdir()), ["AGENTS.md"])

    def test_clean_install_preserves_root_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / ".codex"
            home.mkdir()
            config = home / "config.toml"
            config.write_text('model = "gpt-6-astra"\nservice_tier = "fast"\n')
            original = config.read_bytes()
            self.assertTrue(team_install.install(ROOT, home)["changes"])
            self.assertFalse((home / team_install.STATE).exists())
            self.assertTrue(team_install.install(ROOT, home, apply=True)["verified"])
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(team_install.install(ROOT, home, apply=True)["changes"], [])

    def test_legacy_migration_and_user_instruction_preservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / ".codex"
            home.mkdir()
            instructions = home / "AGENTS.md"
            instructions.write_text("My personal instruction.\n")
            legacy.install(ROOT, home, base, apply=True, with_usage=False)
            config_before = (home / "config.toml").read_bytes()
            result = team_install.install(ROOT, home, apply=True)
            self.assertTrue(result["legacy_migrated"])
            self.assertIn("My personal instruction.", instructions.read_text())
            self.assertNotIn("The Sol root stays on", instructions.read_text())
            self.assertEqual((home / "config.toml").read_bytes(), config_before)
            for role in (home / "agents").glob("*.toml"):
                parsed = legacy.tomllib.loads(role.read_text())
                self.assertFalse(set(parsed) & {"model", "model_reasoning_effort", "sandbox_mode", "service_tier"})
            self.assertEqual(team_settings.read(home / team_settings.SETTINGS_NAME)["model"], "gpt-5.6-luna")
            self.assertEqual(team_install.install(ROOT, home, apply=True)["changes"], [])

    def test_edited_legacy_role_fails_before_any_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / ".codex"
            legacy.install(ROOT, home, base, apply=True, with_usage=False)
            role = next((home / "agents").glob("*.toml"))
            role.write_text(role.read_text() + "# personal edit\n")
            original = (home / "AGENTS.md").read_bytes()
            with self.assertRaisesRegex(legacy.InstallError, "legacy_role_changed"):
                team_install.install(ROOT, home, apply=True)
            self.assertEqual((home / "AGENTS.md").read_bytes(), original)
            self.assertFalse((home / team_install.STATE).exists())

    def test_failed_write_rolls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / ".codex"
            home.mkdir()
            target = home / "AGENTS.md"
            target.write_text("Personal instructions\n")
            original = target.read_bytes()
            real_write = legacy._atomic_write
            def fail_settings(path, data):
                if path.name == team_settings.SETTINGS_NAME:
                    raise OSError("simulated disk error")
                real_write(path, data)
            with patch.object(legacy, "_atomic_write", side_effect=fail_settings):
                with self.assertRaises(OSError):
                    team_install.install(ROOT, home, apply=True)
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse((home / team_install.STATE).exists())


if __name__ == "__main__":
    unittest.main()
