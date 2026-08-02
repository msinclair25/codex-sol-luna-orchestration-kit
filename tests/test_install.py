import contextlib
import importlib.util
import io
import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from scripts import install
from scripts.routing_policy import verify_active_root

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.codex = self.home / ".codex"

    def tearDown(self):
        self.temp.cleanup()

    def test_dry_run_is_non_mutating_and_core_install_is_verifiable(self):
        plan = install.install(ROOT, self.codex, self.home, apply=False, with_usage=False)
        self.assertEqual(plan["status"], "dry-run")
        self.assertFalse(self.codex.exists())
        self.assertFalse((self.home / install.BACKUP_DIRECTORY).exists())
        plan = install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        self.assertEqual(plan["status"], "applied")
        self.assertTrue(plan["verification"]["ok"])
        receipt_path = Path(plan["receipt"])
        self.assertTrue(receipt_path.is_file())
        receipt = json.loads(receipt_path.read_text())
        self.assertTrue(receipt["verification"]["ok"])
        self.assertEqual(len(receipt["changes"]), 7)
        self.assertTrue(all(change["path"].startswith("codex-home/") for change in receipt["changes"]))
        self.assertTrue(receipt_path.is_relative_to(self.home / install.BACKUP_DIRECTORY))
        self.assertFalse((self.home / ".agents" / "skills" / "sol-luna-status").exists())
        report = verify_active_root(self.codex, ROOT, self.codex / "config.toml")
        self.assertTrue(report["ok"], report)

    def test_optional_usage_installs_pointer_and_resolves_kit_root(self):
        plan = install.install(ROOT, self.codex, self.home, apply=True, with_usage=True)
        self.assertEqual(plan["usage"], "create")
        destination = self.home / ".agents" / "skills" / "sol-luna-status"
        self.assertTrue((destination / ".sol-luna-kit-root").is_file())
        script = destination / "scripts" / "sol_luna_status.py"
        spec = importlib.util.spec_from_file_location("installed_status_test", script)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        previous = Path.cwd()
        os.chdir(self.base)
        try:
            self.assertEqual(module._resolve_root(None), ROOT.resolve())
        finally:
            os.chdir(previous)

    def test_nonempty_override_is_target_and_empty_override_does_not_suppress_agents(self):
        self.codex.mkdir()
        (self.codex / "AGENTS.md").write_text("user base\n")
        (self.codex / "AGENTS.override.md").write_text("user override\n")
        install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        self.assertEqual((self.codex / "AGENTS.md").read_text(), "user base\n")
        self.assertIn(install.AGENTS_START, (self.codex / "AGENTS.override.md").read_text())
        report = verify_active_root(self.codex, ROOT)
        self.assertTrue(report["ok"], report)

        empty = self.home / "empty-codex"
        empty.mkdir()
        (empty / "AGENTS.md").write_text("user base\n")
        (empty / "AGENTS.override.md").write_text("")
        install.install(ROOT, empty, self.home, apply=True, with_usage=False)
        self.assertIn(install.AGENTS_START, (empty / "AGENTS.md").read_text())
        self.assertEqual((empty / "AGENTS.override.md").read_text(), "")
        self.assertTrue(verify_active_root(empty, ROOT)["ok"])

    def test_conflicts_fail_closed_and_repeat_is_idempotent(self):
        self.codex.mkdir()
        roles = self.codex / "agents"
        roles.mkdir()
        (roles / "luna_scout_fast.toml").write_text("conflict\n")
        with self.assertRaises(install.InstallError):
            install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        first = (roles / "luna_scout_fast.toml").read_bytes()
        plan = install.install(ROOT, self.codex, self.home, apply=True, with_usage=False, approve_conflicts=True)
        self.assertEqual(plan["roles"][0]["action"], "conflict")
        self.assertNotEqual(first, (roles / "luna_scout_fast.toml").read_bytes())
        backup_count = len(list((self.home / install.BACKUP_DIRECTORY).iterdir()))
        second = install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        self.assertEqual(second["write_count"], 0)
        self.assertIsNone(second["backup"])
        self.assertEqual(len(list((self.home / install.BACKUP_DIRECTORY).iterdir())), backup_count)

    def test_transaction_rolls_back_on_write_failure(self):
        original = install._atomic_write
        calls = {"count": 0}

        def fail_once(path, data):
            calls["count"] += 1
            if calls["count"] == 4:
                raise OSError("injected")
            return original(path, data)

        install._atomic_write = fail_once
        try:
            with self.assertRaisesRegex(install.InstallError, "install_failed_rolled_back"):
                install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        finally:
            install._atomic_write = original
        self.assertFalse((self.codex / "AGENTS.md").exists())
        self.assertFalse((self.codex / "config.toml").exists())
        self.assertFalse((self.codex / "agents").exists() and any((self.codex / "agents").iterdir()))

    def test_config_merge_keeps_unrelated_table_and_requires_approval_for_conflicts(self):
        self.codex.mkdir()
        (self.codex / "config.toml").write_text("# keep\nmodel = \"other\"\n\n[other]\nvalue = 7\n")
        with self.assertRaises(install.InstallError):
            install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        before = (self.codex / "config.toml").read_bytes()
        install.install(ROOT, self.codex, self.home, apply=True, with_usage=False, approve_conflicts=True)
        after = (self.codex / "config.toml").read_text()
        self.assertIn("# keep", after)
        self.assertIn("[other]", after)
        self.assertIn("value = 7", after)
        self.assertNotEqual(before, (self.codex / "config.toml").read_bytes())

    def test_config_preserves_user_reasoning_and_same_named_unrelated_keys(self):
        self.codex.mkdir()
        (self.codex / "config.toml").write_text(
            "model = 'gpt-5.6-sol'\n"
            "model_reasoning_effort = \"medium\"\n\n"
            "[other]\n"
            "model = \"leave-me\"\n"
            "service_tier = \"fast\"\n"
            "\n[[skills.config]]\n"
            "path = \"/tmp/example/SKILL.md\"\n"
            "enabled = false\n"
        )
        install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        with (self.codex / "config.toml").open("rb") as handle:
            parsed = tomllib.load(handle)
        self.assertEqual(parsed["model_reasoning_effort"], "medium")
        self.assertEqual(parsed["other"], {"model": "leave-me", "service_tier": "fast"})
        self.assertEqual(parsed["skills"]["config"][0]["path"], "/tmp/example/SKILL.md")
        self.assertTrue(parsed["features"]["fast_mode"])
        self.assertEqual(parsed["agents"]["max_concurrent_threads_per_session"], 3)

    def test_forbidden_owned_config_keys_require_approval_and_are_removed(self):
        self.codex.mkdir()
        (self.codex / "config.toml").write_text(
            "service_tier = \"fast\"\n\n"
            "[agents]\n"
            "default_subagent_model = \"gpt-5.6-luna\"\n"
        )
        with self.assertRaises(install.InstallError):
            install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        install.install(
            ROOT,
            self.codex,
            self.home,
            apply=True,
            with_usage=False,
            approve_conflicts=True,
        )
        with (self.codex / "config.toml").open("rb") as handle:
            parsed = tomllib.load(handle)
        self.assertNotIn("service_tier", parsed)
        self.assertNotIn("default_subagent_model", parsed["agents"])

    def test_symlink_parent_is_refused_before_outside_write(self):
        outside = self.base / "outside"
        outside.mkdir()
        linked = self.home / "linked"
        linked.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(install.InstallError):
            install.install(ROOT, linked / "codex", self.home, apply=True, with_usage=False)
        self.assertFalse((outside / "codex").exists())

    def test_interactive_cli_applies_core_then_declines_optional_usage(self):
        output = io.StringIO()
        with mock.patch("builtins.input", side_effect=["yes", "no"]), contextlib.redirect_stdout(output):
            result = install.main([
                "--repo-root", str(ROOT),
                "--codex-home", str(self.codex),
                "--home", str(self.home),
            ])
        self.assertEqual(result, 0)
        self.assertTrue((self.codex / "config.toml").is_file())
        self.assertFalse((self.home / ".agents" / "skills" / "sol-luna-status").exists())
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(records[0]["status"], "preview")
        self.assertEqual(records[-1]["usage"], "declined")

    def test_noninteractive_apply_requires_explicit_usage_choice(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            result = install.main([
                "--repo-root", str(ROOT),
                "--codex-home", str(self.codex),
                "--home", str(self.home),
                "--apply",
            ])
        self.assertEqual(result, 2)
        self.assertIn("usage_choice_required", error.getvalue())
        self.assertFalse(self.codex.exists())

    def test_broad_or_external_install_roots_are_rejected(self):
        with self.assertRaisesRegex(install.InstallError, "unsafe_broad_path"):
            install._root_arg(Path.cwd().anchor)
        with self.assertRaisesRegex(install.InstallError, "codex_home_equals_home"):
            install.install(ROOT, self.home, self.home, apply=False, with_usage=False)
        external = self.base / "external" / ".codex"
        with self.assertRaisesRegex(install.InstallError, "codex_home_outside_home"):
            install.install(ROOT, external, self.home, apply=False, with_usage=False)

    def test_usage_pointer_refresh_is_scoped_and_explicit(self):
        install.install(ROOT, self.codex, self.home, apply=True, with_usage=True)
        pointer = self.home / ".agents" / "skills" / "sol-luna-status" / install.POINTER_NAME
        pointer.write_text(str(self.base / "old-checkout") + "\n")
        with self.assertRaisesRegex(install.InstallError, "usage_pointer_conflict"):
            install.install(ROOT, self.codex, self.home, apply=False, with_usage=True)
        plan = install.install(
            ROOT,
            self.codex,
            self.home,
            apply=True,
            with_usage=True,
            refresh_usage_pointer=True,
        )
        self.assertEqual(pointer.read_text(), str(ROOT.resolve()) + "\n")
        self.assertEqual(plan["changes"], [{"action": "replace", "path": "home/.agents/skills/sol-luna-status/.sol-luna-kit-root"}])


if __name__ == "__main__":
    unittest.main()
