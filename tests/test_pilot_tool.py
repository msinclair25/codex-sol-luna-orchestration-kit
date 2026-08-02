import copy
import json
import os
import shutil
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts import pilot_tool
from scripts.receipt_tool import close_receipt


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "config" / "m4-pilot.v1.json"
FIXTURE = ROOT / "tests" / "fixtures" / "receipt_accepted.json"


class PilotToolTests(unittest.TestCase):
    def _isolated_repo(self):
        temporary = tempfile.TemporaryDirectory()
        base = Path(temporary.name)
        repo = base / "repo"
        repo.mkdir()
        plan = json.loads(PLAN.read_text())
        sources = {"config/m4-pilot.v1.json", "config-snippet.toml"}
        for policy in plan["policies"].values():
            sources.update(policy[key] for key in ("policy_path", "agents_path", "config_path", "rate_card_path"))
            sources.update(entry["path"] for entry in policy["roles"].values())
        for relative in sorted(sources):
            source = ROOT / relative
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        return temporary, base, repo, repo / "config" / "m4-pilot.v1.json"

    def _setup(self):
        temporary, base, repo, plan = self._isolated_repo()
        pilot_home = base / "pilot"
        result = pilot_tool.setup_environments(plan, repo, pilot_home, apply=True)
        self.assertTrue(result["ok"])
        return temporary, base, repo, plan, pilot_home

    def _payload(self, start, plan, *, disposition="accepted", complete_usage=False, wrong_policy=False):
        payload = json.loads(FIXTURE.read_text())
        payload.pop("receipt_id", None)
        payload.update({
            "project_id": "codex-sol-luna-orchestration-kit",
            "codex_task_id": start["codex_task_id"],
            "milestone_id": start["milestone_id"],
            "family": start["family"],
            "size_risk_band": start["size_risk_band"],
            "started_at": start["started_at"],
            "closed_at": self._closed_at(start["started_at"], 100 if start["arm"] == "all-max-control" else 110),
            "disposition": disposition,
            "accepted_by": "sol" if disposition == "accepted" else None,
            "user_confirmation": True if disposition == "accepted" else None,
        })
        expected = start["expected"]
        hashes = payload["repository"]["hashes"]
        hashes.update({
            "agents": expected["agents_sha256"],
            "policy": ("0" * 64) if wrong_policy else expected["policy_sha256"],
            "config": expected["config_sha256"],
            "rate_card": expected["rate_card_sha256"],
            "roles": expected["roles"],
        })
        payload["repository"].update({
            "base_commit": plan["source_commit"],
            "bundle_version": expected["bundle_version"],
            "rate_card_version": "rate-card.v1",
        })
        payload["delegated_lanes"] = [{
            "lane_id": f"lane-{start['slot_id']}",
            "role": "luna_scout_fast",
            "reasoning": "max" if start["arm"] == "all-max-control" else "medium",
            "tier": "fast",
            "attempts": 1,
            "retries": 0,
            "escalation": {"target": None, "reason": None},
            "max_reason": None,
            "outcome": "completed",
            "useful": True,
        }]
        payload["acceptance_checks"] = [
            {"id": check_id, "result": "pass", "evidence_refs": [f"test:{start['slot_id']}"], "provenance": ["local:test"]}
            for check_id in start["acceptance_check_ids"]
        ]
        if complete_usage:
            weighted = 100.0 if start["arm"] == "all-max-control" else 70.0
            payload["usage"] = {
                "coverage": "complete-full-workflow",
                "provenance": "usage_reporter",
                "total_tokens": int(weighted),
                "weighted_usage": weighted,
                "source_refs": [f"session:{start['slot_id']}"],
                "rate_card_version": "rate-card.v1",
            }
        return payload

    @staticmethod
    def _closed_at(started_at, seconds):
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        return (started + timedelta(seconds=seconds)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _read_starts(starts_dir):
        return [json.loads(path.read_text()) for path in sorted(starts_dir.glob("*.json"))]

    def test_checked_in_plan_and_schemas_are_strict_and_coherent(self):
        result = pilot_tool.verify_plan(PLAN, ROOT)
        self.assertTrue(result["ok"])
        self.assertEqual(result["sample_size"], 10)
        self.assertEqual(result["family_count"], 5)
        self.assertEqual(result["arm_counts"], {"all-max-control": 5, "dynamic-v0.2.1": 5})
        for name, artifact in (
            ("m4-pilot-plan.v1.schema.json", json.loads(PLAN.read_text())),
            ("pilot-start.v1.schema.json", None),
        ):
            schema = json.loads((ROOT / "schemas" / name).read_text())
            self.assertFalse(schema["additionalProperties"])
            if artifact is not None:
                self.assertEqual(set(schema["required"]), set(artifact))

    def test_malformed_plan_types_fail_closed_without_tracebacks(self):
        mutations = (
            ("minimum_families", []),
            ("kill_criteria", {}),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                temporary, _, repo, plan_path = self._isolated_repo()
                try:
                    plan = json.loads(plan_path.read_text())
                    plan[key] = value
                    plan_path.write_text(json.dumps(plan))
                    with self.assertRaises(pilot_tool.PilotError):
                        pilot_tool.verify_plan(plan_path, repo)
                finally:
                    temporary.cleanup()
        temporary, _, repo, plan_path = self._isolated_repo()
        self.addCleanup(temporary.cleanup)
        plan = json.loads(plan_path.read_text())
        plan["checkpoints"]["required_dispositions"] = {}
        plan_path.write_text(json.dumps(plan))
        with self.assertRaisesRegex(pilot_tool.PilotError, "checkpoint_value"):
            pilot_tool.verify_plan(plan_path, repo)

    def test_setup_is_dry_run_idempotent_private_and_mode_strict(self):
        temporary, base, repo, plan = self._isolated_repo()
        self.addCleanup(temporary.cleanup)
        pilot_home = base / "pilot"
        dry = pilot_tool.setup_environments(plan, repo, pilot_home, apply=False)
        self.assertEqual(dry["status"], "dry-run")
        self.assertEqual(dry["write_count"], 16)
        self.assertFalse(pilot_home.exists())
        applied = pilot_tool.setup_environments(plan, repo, pilot_home, apply=True)
        self.assertEqual(applied["write_count"], 16)
        self.assertFalse(applied["credentials_copied"])
        self.assertFalse(applied["sessions_copied"])
        verified = pilot_tool.verify_environments(plan, repo, pilot_home)
        self.assertTrue(verified["ok"])
        self.assertEqual({arm: row["matches"] for arm, row in verified["arms"].items()}, {"all-max-control": 8, "dynamic-v0.2.1": 8})
        for path in pilot_home.rglob("*"):
            if path.is_file():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertNotIn(path.name, {"auth.json", "credentials.json"})
        self.assertFalse(any(path.name in {"sessions", "skills"} for path in pilot_home.rglob("*")))
        repeated = pilot_tool.setup_environments(plan, repo, pilot_home, apply=True)
        self.assertEqual(repeated["write_count"], 0)

    def test_setup_rejects_broad_destination_conflict_and_symlink(self):
        temporary, base, repo, plan = self._isolated_repo()
        self.addCleanup(temporary.cleanup)
        with self.assertRaisesRegex(pilot_tool.PilotError, "unsafe_pilot_home"):
            pilot_tool.setup_environments(plan, repo, repo, apply=False)
        with self.assertRaisesRegex(pilot_tool.PilotError, "unsafe_pilot_home"):
            pilot_tool.setup_environments(plan, repo, repo / "nested-pilot", apply=False)
        ordinary_codex_home = base / "ordinary" / ".codex"
        ordinary_codex_home.mkdir(parents=True)
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(ordinary_codex_home)}):
            with self.assertRaisesRegex(pilot_tool.PilotError, "unsafe_pilot_home"):
                pilot_tool.setup_environments(plan, repo, ordinary_codex_home / "nested-pilot", apply=False)
            with self.assertRaisesRegex(pilot_tool.PilotError, "unsafe_pilot_home"):
                pilot_tool.setup_environments(plan, repo, ordinary_codex_home.parent / ".CODEX" / "nested-pilot", apply=False)
            with self.assertRaisesRegex(pilot_tool.PilotError, "unsafe_pilot_home"):
                pilot_tool.setup_environments(plan, repo, ordinary_codex_home.parent, apply=False)
        with self.assertRaisesRegex(pilot_tool.PilotError, "unsafe_pilot_home"):
            pilot_tool.setup_environments(plan, repo, repo.parent / repo.name.upper() / "nested-pilot", apply=False)
        with self.assertRaisesRegex(pilot_tool.PilotError, "unsafe_pilot_home"):
            pilot_tool.setup_environments(plan, repo, Path.home() / ".CODEX" / "nested-pilot", apply=False)
        pilot_home = base / "pilot"
        pilot_tool.setup_environments(plan, repo, pilot_home, apply=True)
        config = pilot_home / "dynamic" / ".codex" / "config.toml"
        config.chmod(0o644)
        with self.assertRaisesRegex(pilot_tool.PilotError, "environment_conflict"):
            pilot_tool.setup_environments(plan, repo, pilot_home, apply=True)
        config.chmod(0o600)
        role = pilot_home / "dynamic" / ".codex" / "agents" / "luna_scout_fast.toml"
        role.unlink()
        os.symlink(ROOT / "agents" / "luna_scout_fast.toml", role)
        with self.assertRaisesRegex(pilot_tool.PilotError, "environment_destination_unsafe"):
            pilot_tool.setup_environments(plan, repo, pilot_home, apply=True)

    def test_registration_is_ordered_idempotent_and_environment_bound(self):
        temporary, base, repo, plan_path, pilot_home = self._setup()
        self.addCleanup(temporary.cleanup)
        starts = base / "starts"
        with self.assertRaisesRegex(pilot_tool.PilotError, "start_out_of_order"):
            pilot_tool.register_start(plan_path, repo, pilot_home, starts, "m4-02", "milestone-02", "task-02", "2026-08-02T20:45:00Z")
        result = pilot_tool.register_start(plan_path, repo, pilot_home, starts, "m4-01", "milestone-01", "task-01", "2026-08-02T20:45:00Z")
        self.assertFalse(result["idempotent"])
        repeated = pilot_tool.register_start(plan_path, repo, pilot_home, starts, "m4-01", "milestone-01", "task-01", "2026-08-02T20:45:00Z")
        self.assertTrue(repeated["idempotent"])
        with self.assertRaisesRegex(pilot_tool.PilotError, "prior_window_blocked"):
            pilot_tool.register_start(plan_path, repo, pilot_home, starts, "m4-02", "milestone-02", "task-02", "2026-08-02T20:48:00Z")
        with self.assertRaisesRegex(pilot_tool.PilotError, "start_time"):
            pilot_tool.register_start(plan_path, repo, pilot_home, starts, "m4-02", "milestone-02", "task-02", "2099-01-01T00:00:00Z")
        self.assertEqual(stat.S_IMODE(starts.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((starts / "m4-01.json").stat().st_mode), 0o600)
        start_schema = json.loads((ROOT / "schemas" / "pilot-start.v1.schema.json").read_text())
        self.assertEqual(set(start_schema["required"]), set(json.loads((starts / "m4-01.json").read_text())))
        renamed = starts / "renamed.json"
        (starts / "m4-01.json").rename(renamed)
        with self.assertRaisesRegex(pilot_tool.PilotError, "start_filename_drift"):
            pilot_tool.summarize_pilot(plan_path, repo, starts, base / "receipts", pilot_home, "2026-08-03T00:01:00Z")

    def test_status_pending_overdue_terminal_and_policy_drift(self):
        temporary, base, repo, plan_path, pilot_home = self._setup()
        self.addCleanup(temporary.cleanup)
        starts_dir = base / "starts"
        receipts_dir = base / "receipts"
        ready = pilot_tool.summarize_pilot(plan_path, repo, starts_dir, receipts_dir, pilot_home, "2026-08-02T20:45:00Z")
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["receipt_coverage"], "not-started")
        unverified = pilot_tool.summarize_pilot(plan_path, repo, starts_dir, receipts_dir, None, "2026-08-02T20:45:00Z")
        self.assertEqual(unverified["state"], "setup-unverified")
        pilot_tool.register_start(plan_path, repo, pilot_home, starts_dir, "m4-01", "milestone-01", "task-01", "2026-08-02T20:45:00Z")
        pending = pilot_tool.summarize_pilot(plan_path, repo, starts_dir, receipts_dir, pilot_home, "2026-08-09T20:44:59Z")
        self.assertEqual(pending["pending_count"], 1)
        self.assertEqual(pending["receipt_coverage_fraction"], 0.0)
        overdue = pilot_tool.summarize_pilot(plan_path, repo, starts_dir, receipts_dir, pilot_home, "2026-08-09T20:45:00Z")
        self.assertEqual(overdue["state"], "blocked")
        start = self._read_starts(starts_dir)[0]
        plan = json.loads(plan_path.read_text())
        close_receipt(self._payload(start, plan), receipts_dir)
        terminal = pilot_tool.summarize_pilot(plan_path, repo, starts_dir, receipts_dir, pilot_home, "2026-08-09T20:45:00Z")
        self.assertEqual(terminal["terminal_count"], 1)
        self.assertEqual(terminal["receipt_coverage"], "in-progress")
        self.assertEqual(terminal["receipt_coverage_fraction"], 1.0)

        temporary2, base2, repo2, plan_path2, pilot_home2 = self._setup()
        try:
            starts2, receipts2 = base2 / "starts", base2 / "receipts"
            pilot_tool.register_start(plan_path2, repo2, pilot_home2, starts2, "m4-01", "milestone-01", "task-01", "2026-08-02T20:45:00Z")
            bad_start = self._read_starts(starts2)[0]
            close_receipt(self._payload(bad_start, json.loads(plan_path2.read_text()), wrong_policy=True), receipts2)
            bad = pilot_tool.summarize_pilot(plan_path2, repo2, starts2, receipts2, pilot_home2, "2026-08-02T20:47:00Z")
            self.assertEqual(bad["state"], "blocked")
            self.assertIn("receipt_policy_drift", bad["errors"])
        finally:
            temporary2.cleanup()

    def test_complete_window_compares_only_terminal_attributed_evidence(self):
        temporary, base, repo, plan_path, pilot_home = self._setup()
        self.addCleanup(temporary.cleanup)
        starts_dir, receipts_dir = base / "starts", base / "receipts"
        plan = json.loads(plan_path.read_text())
        dispositions = ("accepted", "rejected", "abandoned")
        for index, slot in enumerate(plan["slots"]):
            started = datetime(2026, 8, 2, 20, 42, tzinfo=timezone.utc) + timedelta(minutes=index * 2)
            timestamp = started.strftime("%Y-%m-%dT%H:%M:%SZ")
            pilot_tool.register_start(plan_path, repo, pilot_home, starts_dir, slot["slot_id"], f"milestone-{index + 1:02d}", f"task-{index + 1:02d}", timestamp, receipts_dir)
            start = self._read_starts(starts_dir)[-1]
            close_receipt(self._payload(start, plan, disposition=dispositions[index % 3], complete_usage=True), receipts_dir)
        report = pilot_tool.summarize_pilot(plan_path, repo, starts_dir, receipts_dir, pilot_home, "2026-08-02T21:05:00Z")
        self.assertTrue(report["ok"])
        self.assertEqual(report["state"], "checkpoint-ready")
        self.assertEqual(report["receipt_coverage"], "complete")
        self.assertEqual(report["receipt_coverage_fraction"], 1.0)
        self.assertEqual(report["comparison"]["status"], "observed")
        self.assertAlmostEqual(report["comparison"]["weighted_usage_reduction"], 0.3)
        self.assertTrue(report["comparison"]["weighted_usage_target_met"])
        self.assertTrue(report["comparison"]["latency_noninferior"])
        self.assertTrue(report["comparison"]["quality_noninferior"])
        self.assertTrue(report["comparison"]["spawn_precision_target_met"])
        self.assertTrue(report["comparison"]["required_dispositions_observed"])
        self.assertFalse(report["comparison"]["automatic_promotion"])
        self.assertEqual(report["comparison"]["promotion_status"], "human-review-required")

    def test_atomic_write_never_overwrites_an_existing_record(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "registry" / "m4-01.json"
            pilot_tool._atomic_write(target, b"first\n")
            with self.assertRaisesRegex(pilot_tool.PilotError, "destination_exists"):
                pilot_tool._atomic_write(target, b"second\n")
            self.assertEqual(target.read_bytes(), b"first\n")

    def test_complete_window_without_required_dispositions_stays_partial(self):
        temporary, base, repo, plan_path, pilot_home = self._setup()
        self.addCleanup(temporary.cleanup)
        starts, receipts = base / "starts", base / "receipts"
        plan = json.loads(plan_path.read_text())
        for index, slot in enumerate(plan["slots"]):
            started = datetime(2026, 8, 2, 20, 42, tzinfo=timezone.utc) + timedelta(minutes=index * 2)
            timestamp = started.strftime("%Y-%m-%dT%H:%M:%SZ")
            pilot_tool.register_start(plan_path, repo, pilot_home, starts, slot["slot_id"], f"accepted-{index + 1:02d}", f"accepted-task-{index + 1:02d}", timestamp, receipts)
            start = self._read_starts(starts)[-1]
            close_receipt(self._payload(start, plan, disposition="accepted", complete_usage=True), receipts)
        report = pilot_tool.summarize_pilot(plan_path, repo, starts, receipts, pilot_home, "2026-08-02T21:05:00Z")
        self.assertEqual(report["state"], "checkpoint-ready")
        self.assertEqual(report["comparison"]["status"], "partial")
        self.assertFalse(report["comparison"]["required_dispositions_observed"])
        self.assertEqual(report["comparison"]["promotion_status"], "evidence-incomplete-human-review")
        self.assertFalse(report["comparison"]["automatic_promotion"])

    def test_receipt_join_rejects_wrong_source_checks_future_and_late(self):
        cases = ("project", "commit", "checks", "future", "late")
        for case in cases:
            with self.subTest(case=case):
                temporary, base, repo, plan_path, pilot_home = self._setup()
                try:
                    starts, receipts = base / "starts", base / "receipts"
                    pilot_tool.register_start(plan_path, repo, pilot_home, starts, "m4-01", "milestone-01", "task-01", "2026-08-02T20:45:00Z", receipts)
                    start = self._read_starts(starts)[0]
                    payload = self._payload(start, json.loads(plan_path.read_text()))
                    as_of = "2026-08-02T21:05:00Z"
                    expected = {
                        "project": "receipt_start_drift",
                        "commit": "receipt_policy_drift",
                        "checks": "receipt_check_drift",
                        "future": "receipt_from_future",
                        "late": "receipt_after_deadline",
                    }[case]
                    if case == "project":
                        payload["project_id"] = "another-project"
                    elif case == "commit":
                        payload["repository"]["base_commit"] = "0" * 40
                    elif case == "checks":
                        payload["acceptance_checks"].append({"id": "unplanned-check", "result": "pass", "evidence_refs": ["test:extra"], "provenance": ["local:test"]})
                    elif case == "future":
                        payload["closed_at"] = "2026-08-02T21:06:00Z"
                    else:
                        payload["closed_at"] = "2026-08-09T20:46:00Z"
                        as_of = "2026-08-09T20:47:00Z"
                    close_receipt(payload, receipts)
                    report = pilot_tool.summarize_pilot(plan_path, repo, starts, receipts, pilot_home, as_of)
                    self.assertEqual(report["state"], "blocked")
                    self.assertIn(expected, report["errors"])
                    self.assertIn("receipt-or-attribution-integrity-failure", report["kill_criteria_triggered"])
                finally:
                    temporary.cleanup()

    def test_kill_criteria_block_status_and_later_registration(self):
        temporary, base, repo, plan_path, pilot_home = self._setup()
        self.addCleanup(temporary.cleanup)
        starts, receipts = base / "starts", base / "receipts"
        pilot_tool.register_start(plan_path, repo, pilot_home, starts, "m4-01", "milestone-01", "task-01", "2026-08-02T20:45:00Z", receipts)
        start = self._read_starts(starts)[0]
        payload = self._payload(start, json.loads(plan_path.read_text()), disposition="rejected")
        payload["risks"] = [
            {"code": "security", "severity": "medium", "status": "mitigated"},
            {"code": "validation", "severity": "high", "status": "open"},
        ]
        close_receipt(payload, receipts)
        report = pilot_tool.summarize_pilot(plan_path, repo, starts, receipts, pilot_home, "2026-08-02T21:05:00Z")
        self.assertFalse(report["ok"])
        self.assertEqual(report["state"], "blocked")
        self.assertEqual(report["kill_criteria_triggered"], ["critical-or-high-defect-regression", "privacy-or-security-failure"])
        self.assertFalse(report["next_slot_eligible"])
        with self.assertRaisesRegex(pilot_tool.PilotError, "prior_window_blocked"):
            pilot_tool.register_start(plan_path, repo, pilot_home, starts, "m4-02", "milestone-02", "task-02", "2026-08-02T20:48:00Z", receipts)


if __name__ == "__main__":
    unittest.main()
