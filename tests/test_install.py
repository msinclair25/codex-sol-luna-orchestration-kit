import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from scripts import install
from scripts.routing_policy import POLICY_AGENTS_RELATIVE, POLICY_RELATIVE, verify_active_root

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
        self.assertEqual(len(receipt["changes"]), 8)
        self.assertTrue(all(change["path"].startswith("codex-home/") for change in receipt["changes"]))
        self.assertTrue(receipt_path.is_relative_to(self.home / install.BACKUP_DIRECTORY))
        self.assertFalse((self.home / ".agents" / "skills" / "sol-luna-status").exists())
        report = verify_active_root(self.codex, ROOT, self.codex / "config.toml")
        self.assertTrue(report["ok"], report)

    def test_dry_run_does_not_write_bytecode_to_source_checkout(self):
        checkout = self.base / "checkout"
        shutil.copytree(
            ROOT,
            checkout,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        environment = os.environ.copy()
        environment.pop("PYTHONDONTWRITEBYTECODE", None)
        environment.pop("PYTHONPYCACHEPREFIX", None)
        result = subprocess.run(
            [
                sys.executable,
                str(checkout / "scripts" / "install.py"),
                "--dry-run",
                "--without-usage",
                "--repo-root",
                str(checkout),
                "--codex-home",
                str(self.codex),
                "--home",
                str(self.home),
            ],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(checkout.rglob("*.pyc")), [])
        self.assertEqual(list(checkout.rglob("__pycache__")), [])

    def test_existing_destination_modes_are_preserved(self):
        self.codex.mkdir()
        agents = self.codex / "AGENTS.md"
        config = self.codex / "config.toml"
        agents.write_text("user instructions\n")
        config.write_text("model = \"gpt-5.6-sol\"\n")
        agents.chmod(0o755)
        config.chmod(0o644)

        install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)

        self.assertEqual(stat.S_IMODE(agents.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o644)

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

    def test_optional_usage_assets_are_hash_verified_without_blocking_core(self):
        checkout = self.base / "checkout"
        shutil.copytree(
            ROOT,
            checkout,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        status_script = checkout / ".agents" / "skills" / "sol-luna-status" / "scripts" / "sol_luna_status.py"
        status_script.write_text(status_script.read_text() + "\n# unexpected drift\n")

        core = install.install(checkout, self.codex, self.home, apply=False, with_usage=False)
        self.assertEqual(core["status"], "dry-run")
        with self.assertRaisesRegex(install.InstallError, "usage_source_integrity"):
            install.install(checkout, self.codex, self.home, apply=False, with_usage=True)

        manifest = checkout / install.USAGE_ASSET_MANIFEST
        status_script.write_bytes((ROOT / ".agents" / "skills" / "sol-luna-status" / "scripts" / "sol_luna_status.py").read_bytes())
        bool_schema = json.loads((ROOT / install.USAGE_ASSET_MANIFEST).read_text())
        bool_schema["schema_version"] = True
        manifest.write_text(json.dumps(bool_schema))
        with self.assertRaisesRegex(install.InstallError, "usage_source_integrity"):
            install.install(checkout, self.codex, self.home, apply=False, with_usage=True)

        manifest.write_text('{"schema_version":1,"assets":' + "[" * 1100 + "0" + "]" * 1100 + "}")
        with self.assertRaisesRegex(install.InstallError, "usage_source_integrity"):
            install.install(checkout, self.codex, self.home, apply=False, with_usage=True)

    def test_nonempty_override_is_target_and_empty_override_does_not_suppress_agents(self):
        self.codex.mkdir()
        (self.codex / "AGENTS.md").write_text("user base\n")
        (self.codex / "AGENTS.override.md").write_text("user override\n")
        install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        self.assertEqual((self.codex / "AGENTS.md").read_text(), "user base\n")
        self.assertIn(install.AGENTS_START, (self.codex / "AGENTS.override.md").read_text())
        report = verify_active_root(self.codex, ROOT)
        self.assertTrue(report["ok"], report)
        repeat = install.install(
            ROOT,
            self.codex,
            self.home,
            apply=True,
            with_usage=False,
            approve_agents_refresh=True,
        )
        self.assertEqual(repeat["agents"], "identical-managed")
        self.assertEqual(repeat["write_count"], 0)
        self.assertIsNone(repeat["backup"])

        empty = self.home / "empty-codex"
        empty.mkdir()
        (empty / "AGENTS.md").write_text("user base\n")
        (empty / "AGENTS.override.md").write_text("")
        install.install(ROOT, empty, self.home, apply=True, with_usage=False)
        self.assertIn(install.AGENTS_START, (empty / "AGENTS.md").read_text())
        self.assertEqual((empty / "AGENTS.override.md").read_text(), "")
        self.assertTrue(verify_active_root(empty, ROOT)["ok"])

    def test_known_exact_prior_policy_requires_explicit_safe_refresh(self):
        self.codex.mkdir()
        agents = self.codex / "AGENTS.md"
        prior_policy = b"# exact prior kit policy\n"
        known = frozenset({hashlib.sha256(prior_policy).hexdigest()})
        agents.write_bytes(prior_policy)

        with mock.patch.object(install, "KNOWN_EXACT_AGENTS_REVISIONS", known):
            with self.assertRaisesRegex(install.InstallError, "agents_known_revision_requires_refresh"):
                install.install(ROOT, self.codex, self.home, apply=False, with_usage=False)
            plan = install.install(
                ROOT,
                self.codex,
                self.home,
                apply=True,
                with_usage=False,
                approve_agents_refresh=True,
            )

        self.assertEqual(plan["agents"], "refresh-known-exact")
        self.assertEqual(agents.read_bytes(), (ROOT / POLICY_AGENTS_RELATIVE).read_bytes())
        self.assertTrue(plan["verification"]["ok"])

    def test_frozen_v021_policy_is_an_explicit_refresh_source(self):
        frozen_digest = hashlib.sha256((ROOT / "AGENTS.md").read_bytes()).hexdigest()
        self.assertIn(frozen_digest, install.KNOWN_EXACT_AGENTS_REVISIONS)

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

    def test_rollback_preserves_concurrent_edit_to_new_target(self):
        target = self.codex / "agents" / "luna_scout_fast.toml"
        original = install._atomic_write

        def edit_then_fail_receipt(path, data):
            result = original(path, data)
            if path == target:
                target.write_bytes(b"concurrent edit\n")
            if path.name == "install-receipt.json":
                raise OSError("injected receipt failure")
            return result

        install._atomic_write = edit_then_fail_receipt
        try:
            with self.assertRaisesRegex(install.InstallError, "install_failed_rollback_incomplete;backup="):
                install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        finally:
            install._atomic_write = original

        self.assertEqual(target.read_bytes(), b"concurrent edit\n")

    def test_rollback_preserves_concurrent_edit_to_preexisting_target_and_backup(self):
        self.codex.mkdir()
        target = self.codex / "agents" / "luna_scout_fast.toml"
        target.parent.mkdir()
        original_bytes = b"pre-existing role\n"
        target.write_bytes(original_bytes)
        original = install._atomic_write

        def edit_then_fail_receipt(path, data):
            result = original(path, data)
            if path == target:
                target.write_bytes(b"concurrent edit\n")
            if path.name == "install-receipt.json":
                raise OSError("injected receipt failure")
            return result

        install._atomic_write = edit_then_fail_receipt
        try:
            with self.assertRaisesRegex(install.InstallError, "install_failed_rollback_incomplete;backup="):
                install.install(
                    ROOT,
                    self.codex,
                    self.home,
                    apply=True,
                    with_usage=False,
                    approve_conflicts=True,
                )
        finally:
            install._atomic_write = original

        self.assertEqual(target.read_bytes(), b"concurrent edit\n")
        backup_roots = list((self.home / install.BACKUP_DIRECTORY).iterdir())
        self.assertEqual(len(backup_roots), 1)
        backup = backup_roots[0] / "codex-home" / "agents" / target.name
        self.assertEqual(backup.read_bytes(), original_bytes)

    def test_rollback_restores_unchanged_preexisting_target(self):
        self.codex.mkdir()
        target = self.codex / "agents" / "luna_scout_fast.toml"
        target.parent.mkdir()
        original_bytes = b"pre-existing role\n"
        target.write_bytes(original_bytes)
        original = install._atomic_write

        def fail_receipt(path, data):
            if path.name == "install-receipt.json":
                raise OSError("injected receipt failure")
            return original(path, data)

        install._atomic_write = fail_receipt
        try:
            with self.assertRaisesRegex(install.InstallError, "install_failed_rolled_back;backup="):
                install.install(
                    ROOT,
                    self.codex,
                    self.home,
                    apply=True,
                    with_usage=False,
                    approve_conflicts=True,
                )
        finally:
            install._atomic_write = original

        self.assertEqual(target.read_bytes(), original_bytes)

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

    def test_noninteractive_optional_failure_keeps_verified_core(self):
        destination = self.home / ".agents" / "skills" / "sol-luna-status"
        destination.mkdir(parents=True)
        conflicting = destination / "SKILL.md"
        conflicting.write_text("user-owned conflict\n")
        output = io.StringIO()
        error = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            result = install.main([
                "--repo-root", str(ROOT),
                "--codex-home", str(self.codex),
                "--home", str(self.home),
                "--apply",
                "--with-usage",
            ])

        self.assertEqual(result, 2)
        self.assertIn("usage_conflict", error.getvalue())
        self.assertEqual(conflicting.read_text(), "user-owned conflict\n")
        self.assertTrue(verify_active_root(self.codex, ROOT, self.codex / "config.toml")["ok"])
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(records[0]["phase"], "core")
        self.assertEqual(records[0]["status"], "preview")
        self.assertEqual(records[1]["phase"], "core")
        self.assertEqual(records[1]["status"], "applied")

    def test_noninteractive_core_and_optional_success_use_separate_transactions(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = install.main([
                "--repo-root", str(ROOT),
                "--codex-home", str(self.codex),
                "--home", str(self.home),
                "--apply",
                "--with-usage",
            ])

        self.assertEqual(result, 0)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [(record["phase"], record["status"]) for record in records],
            [
                ("core", "preview"),
                ("core", "applied"),
                ("optional-usage", "preview"),
                ("optional-usage", "applied"),
            ],
        )
        self.assertEqual(records[1]["write_count"], 8)
        self.assertEqual(records[3]["write_count"], 5)
        self.assertNotEqual(records[1]["receipt"], records[3]["receipt"])
        self.assertTrue(records[1]["verification"]["ok"])
        self.assertTrue(records[3]["verification"]["ok"])

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

    def test_standard_profile_installs_and_switches_safely(self):
        standard = install.install(
            ROOT,
            self.codex,
            self.home,
            apply=True,
            with_usage=False,
            luna_tier="standard",
        )
        self.assertEqual(standard["luna_tier"], "standard")
        self.assertTrue(standard["verification"]["ok"])
        scout = self.codex / "agents" / "luna_scout_standard.toml"
        self.assertTrue(scout.is_file())
        with scout.open("rb") as handle:
            standard_role = tomllib.load(handle)
        self.assertNotIn("service_tier", standard_role)
        self.assertFalse((self.codex / "agents" / "luna_scout_fast.toml").exists())
        self.assertTrue(verify_active_root(self.codex, ROOT, self.codex / "config.toml", "standard")["ok"])
        self.assertEqual(
            json.loads((self.codex / install.INSTALL_STATE_NAME).read_text())["kit_version"],
            "0.6.0",
        )

        switched = install.install(
            ROOT,
            self.codex,
            self.home,
            apply=True,
            with_usage=False,
            luna_tier="fast",
            update=True,
        )
        self.assertEqual(switched["mode"], "update")
        self.assertTrue(switched["verification"]["ok"])
        self.assertTrue((self.codex / "agents" / "luna_scout_fast.toml").is_file())
        state = json.loads((self.codex / install.INSTALL_STATE_NAME).read_text())
        self.assertEqual(state["active_luna_tier"], "fast")
        self.assertEqual(len(state["roles"]), 10)
        self.assertEqual(state["schema_version"], 2)
        self.assertEqual(state["update_phase"], "ready")

        restored = install.install(
            ROOT,
            self.codex,
            self.home,
            apply=True,
            with_usage=False,
            luna_tier="standard",
            update=True,
        )
        self.assertTrue(restored["verification"]["ok"])
        self.assertEqual(json.loads((self.codex / install.INSTALL_STATE_NAME).read_text())["active_luna_tier"], "standard")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = install.main([
                "--repo-root", str(ROOT),
                "--codex-home", str(self.codex),
                "--home", str(self.home),
                "--update",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue().splitlines()[-1])["luna_tier"], "standard")

    def test_doctor_migrates_legacy_state_and_resumes_pending_update(self):
        install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        state_path = self.codex / install.INSTALL_STATE_NAME
        legacy = json.loads(state_path.read_text())
        legacy["schema_version"] = 1
        legacy["kit_version"] = "0.4.0"
        legacy.pop("update_phase")
        state_path.write_text(json.dumps(legacy))

        outdated = install.doctor(ROOT, self.codex)
        self.assertEqual(outdated["health"], "roles-update-required")
        self.assertEqual(outdated["next_action"], "update-roles")
        role_path = self.codex / "agents" / "luna_scout_fast.toml"
        recorded_role = role_path.read_bytes()
        role_path.write_text("managed runtime drift\n")
        drifted_outdated = install.doctor(ROOT, self.codex)
        self.assertEqual(drifted_outdated["health"], "needs-attention")
        self.assertEqual(drifted_outdated["next_action"], "review-drift")
        role_path.write_bytes(recorded_role)
        pending = install.mark_update_pending(self.codex)
        self.assertEqual(pending["health"], "update-pending")
        stored = json.loads(state_path.read_text())
        self.assertEqual(stored["schema_version"], 2)
        self.assertEqual(stored["update_phase"], "package-refresh-requested")
        self.assertEqual(install.doctor(ROOT, self.codex)["next_action"], "retry-package-refresh")
        self.assertEqual(
            install.doctor(ROOT, self.codex)["next_message"],
            "The package refresh did not finish. Ask Sol/Luna setup to retry the update; no restart is needed yet.",
        )
        refreshed = install.mark_package_refreshed(self.codex)
        self.assertEqual(refreshed["next_action"], "restart-and-finish-update")
        self.assertEqual(install.doctor(ROOT, self.codex)["next_action"], "finish-update")
        self.assertEqual(
            install.doctor(ROOT, self.codex)["next_message"],
            "Restart Codex, begin a new task, and ask Sol/Luna setup to continue.",
        )

        updated = install.install(
            ROOT,
            self.codex,
            self.home,
            apply=True,
            with_usage=False,
            update=True,
        )
        self.assertTrue(updated["verification"]["ok"])
        ready = json.loads(state_path.read_text())
        self.assertEqual(ready["kit_version"], "0.6.0")
        self.assertEqual(ready["update_phase"], "ready")
        self.assertEqual(install.doctor(ROOT, self.codex)["health"], "healthy")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = install.main([
                "--repo-root", str(ROOT),
                "--codex-home", str(self.codex),
                "--home", str(self.home),
                "--doctor",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["next_action"], "none")

    def test_doctor_distinguishes_repository_workflow_only_and_invalid_state(self):
        repository = install.doctor(ROOT, self.codex)
        self.assertEqual(repository["health"], "not-installed")
        self.assertEqual(repository["mode"], "not-installed")
        self.assertIsNone(repository["luna_tier"])
        self.assertEqual(repository["next_action"], "install-if-desired")

        plugin = ROOT / "plugins" / "sol-luna-orchestration-kit"
        workflow = install.doctor(plugin, self.codex)
        self.assertEqual(workflow["health"], "workflow-only")
        self.assertEqual(workflow["mode"], "workflow-only")
        self.assertIsNone(workflow["luna_tier"])
        self.assertEqual(workflow["workflow_default_tier"], "fast")
        self.assertEqual(workflow["kit_version"], "0.6.0")

        malformed_plugin = self.base / "malformed-plugin"
        shutil.copytree(
            plugin,
            malformed_plugin,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (malformed_plugin / ".codex-plugin" / "plugin.json").write_text(
            '{"name":"wrong-plugin","version":"0.6.0"}\n'
        )
        malformed = install.doctor(malformed_plugin, self.codex)
        self.assertEqual(malformed["health"], "needs-attention")
        self.assertEqual(malformed["next_action"], "review-drift")
        self.assertFalse(malformed["ok"])

        self.codex.mkdir()
        (self.codex / install.INSTALL_STATE_NAME).write_text('{"schema_version":2}')
        invalid = install.doctor(ROOT, self.codex)
        self.assertEqual(invalid["health"], "needs-attention")
        self.assertFalse(invalid["ok"])

    def test_state_tracked_update_replaces_only_unchanged_managed_assets(self):
        install.install(ROOT, self.codex, self.home, apply=True, with_usage=False)
        checkout = self.base / "checkout"
        shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        source = checkout / "agents" / "v0.4" / "luna_scout_fast.toml"
        source.write_text(source.read_text() + "\n# compatible update\n")
        policy_path = checkout / POLICY_RELATIVE
        policy = json.loads(policy_path.read_text())
        policy["roles"]["luna_scout_fast"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        policy_path.write_text(json.dumps(policy, indent=2) + "\n")

        updated = install.install(
            checkout,
            self.codex,
            self.home,
            apply=True,
            with_usage=False,
            update=True,
        )
        actions = {role["name"]: role["action"] for role in updated["roles"]}
        self.assertEqual(actions["luna_scout_fast.toml"], "update-managed")
        self.assertEqual((self.codex / "agents" / "luna_scout_fast.toml").read_bytes(), source.read_bytes())

        (self.codex / "agents" / "luna_scout_fast.toml").write_text("user edit\n")
        with self.assertRaisesRegex(install.InstallError, "role_conflict_luna_scout_fast"):
            install.install(
                checkout,
                self.codex,
                self.home,
                apply=False,
                with_usage=False,
                update=True,
            )

    def test_update_requires_valid_state_and_cli_remembers_usage_choice(self):
        with self.assertRaisesRegex(install.InstallError, "update_state_missing"):
            install.install(ROOT, self.codex, self.home, apply=False, with_usage=False, update=True)

        install.install(ROOT, self.codex, self.home, apply=True, with_usage=True)
        role = self.codex / "agents" / "luna_scout_fast.toml"
        before_role = role.read_bytes()
        before_state = (self.codex / install.INSTALL_STATE_NAME).read_bytes()
        malformed_state = json.loads(before_state)
        malformed_state["schema_version"] = True
        (self.codex / install.INSTALL_STATE_NAME).write_text(json.dumps(malformed_state))
        with self.assertRaisesRegex(install.InstallError, "install_state_invalid"):
            install.install(ROOT, self.codex, self.home, apply=False, with_usage=False, update=True)
        (self.codex / install.INSTALL_STATE_NAME).write_bytes(before_state)
        preview_output = io.StringIO()
        with contextlib.redirect_stdout(preview_output):
            preview_result = install.main([
                "--repo-root", str(ROOT),
                "--codex-home", str(self.codex),
                "--home", str(self.home),
                "--dry-run",
                "--update",
                "--without-usage",
            ])
        self.assertEqual(preview_result, 0)
        preview = json.loads(preview_output.getvalue().splitlines()[-1])
        self.assertEqual(preview["mode"], "update")
        self.assertEqual(preview["status"], "dry-run")
        self.assertEqual(role.read_bytes(), before_role)
        self.assertEqual((self.codex / install.INSTALL_STATE_NAME).read_bytes(), before_state)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = install.main([
                "--repo-root", str(ROOT),
                "--codex-home", str(self.codex),
                "--home", str(self.home),
                "--update",
            ])
        self.assertEqual(result, 0)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(records[-1]["usage"], "identical")
        self.assertEqual(records[-1]["mode"], "update")


if __name__ == "__main__":
    unittest.main()
