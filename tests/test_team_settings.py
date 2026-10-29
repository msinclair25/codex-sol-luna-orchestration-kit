import tempfile
import unittest
from pathlib import Path

from scripts import team_settings as team


CATALOG = [
    {"slug": "gpt-6-luna", "default_reasoning_level": "high",
     "supported_reasoning_levels": [{"effort": "high"}, {"effort": "max"}]},
    {"slug": "gpt-6.1-sol", "default_reasoning_level": "low",
     "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}, {"effort": "ultra"}]},
]


class TeamSettingsTests(unittest.TestCase):
    def test_chat_change_controls_next_launch_without_custom_role_pin(self):
        saved = {"model": "gpt-6.1-sol", "reasoning": "ultra"}
        resolved = team.resolve(personal=saved, chat={"model": "gpt-6-luna"})
        args = team.launch(resolved["settings"], "worker", catalog=CATALOG, runtime_limit=3)["spawn"]
        self.assertEqual(args, {"agent_type": "default", "fork_turns": "none",
                                "model": "gpt-6-luna", "reasoning_effort": "high"})
        self.assertEqual(saved["reasoning"], "ultra")

    def test_inherit_omits_model_and_reasoning(self):
        result = team.launch({"model": "inherit"}, "critic", catalog=[], runtime_limit=3)
        self.assertEqual(set(result["spawn"]), {"agent_type", "fork_turns"})
        self.assertFalse(result["runtime_verified"])

    def test_scopes_replace_role_set_and_keep_other_preferences(self):
        roles = {"security": {"instructions": "Review authentication. Do not edit."}}
        result = team.resolve({"model": "gpt-6.1-sol"}, {"roles": roles}, {"max_concurrent": 2})
        self.assertEqual(result["settings"]["roles"], roles)
        self.assertEqual(result["sources"], {"model": "personal", "roles": "project", "max_concurrent": "chat"})
        with self.assertRaisesRegex(team.SettingsError, "role_disabled"):
            team.launch(result["settings"], "worker", catalog=CATALOG, runtime_limit=3)

    def test_explicit_role_model_uses_own_effort(self):
        settings = {"model": "gpt-6.1-sol", "reasoning": "ultra",
                    "roles": {"critic": {"instructions": "Review.", "model": "gpt-6-luna"}}}
        self.assertEqual(team.launch(settings, "critic", catalog=CATALOG, runtime_limit=3)["spawn"]["reasoning_effort"], "high")

    def test_runtime_ceiling_and_disabled_delegation(self):
        for settings, active in (({"max_concurrent": 12}, 2), ({"max_concurrent": 0}, 0)):
            with self.assertRaisesRegex(team.SettingsError, "concurrency_limit"):
                team.launch(settings, "worker", catalog=CATALOG, runtime_limit=2, active=active)

    def test_no_silent_model_or_effort_fallback(self):
        for settings in ({"model": "gpt-6.1-luna"}, {"reasoning": "ultra"},
                         {"model": "inherit", "reasoning": "high"}):
            with self.assertRaises(team.SettingsError):
                team.launch(settings, "worker", catalog=CATALOG, runtime_limit=3)

    def test_save_backup_reset_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / ".codex" / team.SETTINGS_NAME
            team.save(path, {"model": "gpt-6.1-sol", "reasoning": "ultra"})
            unrelated = path.parent / "config.toml"
            unrelated.write_text('model = "user-choice"\n')
            before = path.read_bytes()
            result = team.save(path, {"model": "gpt-6-luna"})
            self.assertEqual(Path(result["backup"]).read_bytes(), before)
            self.assertEqual(team.read(path), {"model": "gpt-6-luna"})
            self.assertFalse(team.save(path, {"model": "gpt-6-luna"})["changed"])
            team.save(path, {}, reset=True)
            self.assertEqual(team.read(path), {})
            self.assertEqual(unrelated.read_text(), 'model = "user-choice"\n')

    def test_malformed_input_rejected_without_write(self):
        for raw in ('{"model":"a","model":"b"}', '{"max_concurrent":true}',
                    '{"roles":{"worker":{"instructions":""}}}', '{"service_tier":"fast"}',
                    '{"reasoning":[]}', '{"roles":{"critic":{"instructions":"Review","reasoning":{}}}}'):
            with self.assertRaises(team.SettingsError):
                team.parse(raw)

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(team.SettingsError, "unsafe_settings_path"):
                team.save(link / team.SETTINGS_NAME, {"model": "inherit"})
            self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
