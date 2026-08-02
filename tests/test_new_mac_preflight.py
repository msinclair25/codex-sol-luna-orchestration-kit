import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import new_mac_preflight


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_FACTS = {
    "origin": "github.com/msinclair25/codex-sol-luna-orchestration-kit",
    "head": "a" * 40,
    "branch": "codex/m4-pilot-protocol",
    "clean": True,
}


class NewMacPreflightTests(unittest.TestCase):
    def _host_patches(self):
        return (
            mock.patch.object(new_mac_preflight.platform, "system", return_value="Darwin"),
            mock.patch.object(new_mac_preflight.platform, "machine", return_value="arm64"),
            mock.patch.object(new_mac_preflight, "_version", side_effect=lambda name, _: f"{name} version 1.0"),
            mock.patch.object(new_mac_preflight, "_repository_facts", return_value=dict(REPOSITORY_FACTS)),
        )

    def test_repository_origin_allowlist_is_exact(self):
        accepted = (
            "https://github.com/msinclair25/codex-sol-luna-orchestration-kit",
            "https://github.com/msinclair25/codex-sol-luna-orchestration-kit.git",
            "ssh://git@github.com/msinclair25/codex-sol-luna-orchestration-kit.git",
            "git@github.com:msinclair25/codex-sol-luna-orchestration-kit.git",
        )
        for value in accepted:
            with self.subTest(value=value):
                self.assertEqual(
                    new_mac_preflight._canonical_repository(value),
                    new_mac_preflight.EXPECTED_REPOSITORY,
                )
        for value in (
            "https://github.com/another/codex-sol-luna-orchestration-kit.git",
            "https://example.com/msinclair25/codex-sol-luna-orchestration-kit.git",
            "file:///tmp/codex-sol-luna-orchestration-kit",
        ):
            with self.subTest(value=value):
                self.assertIsNone(new_mac_preflight._canonical_repository(value))

    def test_dry_run_is_non_mutating_and_reports_zero_model_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            pilot_home = Path(directory) / "nested" / "pilot"
            patches = self._host_patches()
            with patches[0], patches[1], patches[2], patches[3]:
                result = new_mac_preflight.prepare(ROOT, pilot_home, apply=False)
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "dry-run-ready")
            self.assertEqual(result["pilot"]["write_count"], 16)
            self.assertFalse(pilot_home.exists())
            self.assertEqual(result["safety"]["model_runs_started_by_preflight"], 0)
            self.assertEqual(result["safety"]["measured_starts_registered_by_preflight"], 0)
            self.assertFalse(result["safety"]["ordinary_codex_home_targeted"])

    def test_apply_creates_only_verified_isolated_roots_and_stops_before_slot_one(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ordinary_codex_home = base / "ordinary" / ".codex"
            ordinary_codex_home.mkdir(parents=True)
            sentinel = ordinary_codex_home / "sentinel.txt"
            sentinel.write_text("unchanged\n")
            sentinel.chmod(0o600)
            pilot_home = base / "dedicated" / "m4-v0.2.1-window-01"
            starts_existed_before = (ROOT / ".sol-luna" / "starts").exists()
            patches = self._host_patches()
            with (
                mock.patch.dict(os.environ, {"CODEX_HOME": str(ordinary_codex_home)}),
                patches[0],
                patches[1],
                patches[2],
                patches[3],
            ):
                result = new_mac_preflight.prepare(ROOT, pilot_home, apply=True)
            self.assertEqual(result["status"], "ready-for-separate-login-and-unmeasured-smoke")
            self.assertEqual(result["pilot"]["write_count"], 16)
            self.assertEqual(
                {arm: row["matches"] for arm, row in result["pilot"]["environment"]["arms"].items()},
                {"all-max-control": 8, "dynamic-v0.2.1": 8},
            )
            self.assertEqual(result["pilot"]["registered_count"], 0)
            self.assertEqual(result["pilot"]["terminal_count"], 0)
            self.assertEqual(result["safety"]["model_runs_started_by_preflight"], 0)
            self.assertEqual(sentinel.read_text(), "unchanged\n")
            self.assertEqual(stat.S_IMODE(sentinel.stat().st_mode), 0o600)
            self.assertEqual(
                (ROOT / ".sol-luna" / "starts").exists(),
                starts_existed_before,
            )

    def test_non_macos_and_existing_start_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(new_mac_preflight.platform, "system", return_value="Linux"):
                with self.assertRaisesRegex(new_mac_preflight.PreflightError, "macos_required"):
                    new_mac_preflight.prepare(ROOT, Path(directory) / "pilot", apply=False)
            fake_repo = Path(directory) / "repo"
            starts = fake_repo / ".sol-luna" / "starts"
            starts.mkdir(parents=True)
            (starts / "m4-01.json").write_text("{}\n")
            with self.assertRaisesRegex(new_mac_preflight.PreflightError, "measured_starts_present"):
                new_mac_preflight._ensure_no_measured_starts(fake_repo)

    def test_apply_rejects_pilot_home_nested_inside_codex_home(self):
        with tempfile.TemporaryDirectory() as directory:
            ordinary_codex_home = Path(directory) / "ordinary" / ".codex"
            ordinary_codex_home.mkdir(parents=True)
            patches = self._host_patches()
            with (
                mock.patch.dict(os.environ, {"CODEX_HOME": str(ordinary_codex_home)}),
                patches[0],
                patches[1],
                patches[2],
                patches[3],
            ):
                with self.assertRaisesRegex(new_mac_preflight.pilot_tool.PilotError, "unsafe_pilot_home"):
                    new_mac_preflight.prepare(
                        ROOT,
                        ordinary_codex_home / "nested-pilot",
                        apply=True,
                    )
            self.assertEqual(list(ordinary_codex_home.iterdir()), [])

    def test_case_variant_codex_home_alias_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            ordinary_codex_home = Path(directory) / "ordinary" / ".codex"
            ordinary_codex_home.mkdir(parents=True)
            patches = self._host_patches()
            with (
                mock.patch.dict(os.environ, {"CODEX_HOME": str(ordinary_codex_home)}),
                patches[0],
                patches[1],
                patches[2],
                patches[3],
            ):
                with self.assertRaisesRegex(new_mac_preflight.pilot_tool.PilotError, "unsafe_pilot_home"):
                    new_mac_preflight.prepare(
                        ROOT,
                        ordinary_codex_home.parent / ".CODEX" / "nested-pilot",
                        apply=True,
                    )
            self.assertEqual(list(ordinary_codex_home.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
