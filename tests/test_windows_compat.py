import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import install
from scripts.receipt_tool import build_routine_record, close_receipt, close_routine_record
from scripts.verify_control_bundle import verify


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / ".agents" / "skills" / "sol-luna-status" / "scripts" / "sol_luna_status.py"
FIXTURE = ROOT / "tests" / "fixtures" / "receipt_accepted.json"


class NativeWindowsCompatibilityTests(unittest.TestCase):
    """Happy-path integration checks intentionally runnable on windows-latest."""

    def test_install_update_doctor_and_project_metrics_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            home.mkdir()
            codex_home = home / ".codex"

            installed = install.install(
                ROOT,
                codex_home,
                home,
                apply=True,
                with_usage=True,
                luna_tier="fast",
            )
            self.assertTrue(installed["verification"]["ok"], installed)
            self.assertEqual(install.mark_update_pending(codex_home)["next_action"], "refresh-package-and-restart")
            self.assertEqual(install.mark_package_refreshed(codex_home)["next_action"], "restart-and-finish-update")
            updated = install.install(
                ROOT,
                codex_home,
                home,
                apply=True,
                with_usage=True,
                luna_tier="standard",
                update=True,
                refresh_usage_pointer=True,
            )
            self.assertTrue(updated["verification"]["ok"], updated)
            diagnosis = install.doctor(ROOT, codex_home)
            self.assertTrue(diagnosis["ok"], diagnosis)
            self.assertEqual(diagnosis["luna_tier"], "standard")

            workspace = base / "project"
            workspace.mkdir()
            (workspace / ".git").mkdir()
            routine = build_routine_record(
                routing_policy="routing-policy.v1.5",
                profile="standard",
                role_kind="tester",
                task_class="substantial_validation",
                benefit_code="parallel_latency",
                useful=True,
                outcome="completed",
                checks=[{"name": "acceptance-1", "status": "pass"}],
                total_tokens=100,
            )
            routine_result = close_routine_record(
                routine,
                workspace / ".sol-luna" / "routine-records",
            )
            self.assertTrue(routine_result["ok"])
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload.pop("receipt_id", None)
            receipt_result = close_receipt(payload, workspace / ".sol-luna" / "receipts")
            self.assertFalse(receipt_result["idempotent"])

            environment = {
                **os.environ,
                "HOME": str(home),
                "USERPROFILE": str(home),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    str(STATUS),
                    "--root",
                    str(ROOT),
                    "--workspace-root",
                    str(workspace),
                    "--active-root",
                    str(codex_home),
                    "--active-config",
                    str(codex_home / "config.toml"),
                    "--format",
                    "json",
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["workspace"]["status"], "available")
            self.assertEqual(report["routine_records"]["collection"], "active")
            self.assertEqual(report["routine_records"]["observed"], 1)
            self.assertTrue(report["drift"]["active_runtime"])

    def test_plugin_sync_apply_works_in_an_isolated_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "checkout"
            shutil.copytree(
                ROOT,
                checkout,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            mirror = checkout / "plugins" / "sol-luna-orchestration-kit" / "scripts" / "lifecycle.py"
            mirror.write_text(mirror.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "scripts/sync_plugin.py", "--apply"],
                cwd=checkout,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertTrue(report["ok"], report)
            self.assertEqual(
                (checkout / "scripts" / "lifecycle.py").read_bytes(),
                mirror.read_bytes(),
            )

    def test_windows_hook_and_quick_setup_assets_are_bundled(self):
        plugin = ROOT / "plugins" / "sol-luna-orchestration-kit"
        hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        command = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["commandWindows"]
        self.assertEqual(command, 'py -3 "%PLUGIN_ROOT%\\scripts\\pre_tool_use_guard.py"')
        self.assertTrue((plugin / "scripts" / "windows_setup.ps1").is_file())
        self.assertTrue((plugin / "scripts" / "setup.py").is_file())
        self.assertTrue((plugin / "scripts" / "platform_fs.py").is_file())

    @unittest.skipUnless(os.name == "nt", "native junction behavior is Windows-specific")
    def test_windows_junctions_fail_closed_in_sync_and_bundle_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            checkout = base / "checkout"
            shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
            outside = base / "outside"
            outside.mkdir()
            (outside / "borrowed.json").write_text("{}\n", encoding="utf-8")

            source_junction = checkout / "profiles" / "junction"
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(source_junction), str(outside)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            synced = subprocess.run(
                [sys.executable, "scripts/sync_plugin.py"],
                cwd=checkout,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(synced.returncode, 1, synced.stdout)
            self.assertIn("source_invalid", synced.stdout)

            bundle = base / "bundle"
            shutil.copytree(ROOT / "control-bundles" / "all-max-v1", bundle)
            bundle_junction = bundle / "files" / "junction"
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(bundle_junction), str(outside)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            report = verify(bundle)
            self.assertFalse(report["ok"])
            self.assertEqual(report["mismatches"]["unexpected_files"], 1)


if __name__ == "__main__":
    unittest.main()
