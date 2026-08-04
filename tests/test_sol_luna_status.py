import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import install as installer
from scripts import pilot_tool
from scripts.receipt_tool import close_receipt


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "sol-luna-status"
SCRIPT = SKILL / "scripts" / "sol_luna_status.py"
FIXTURES = ROOT / "tests" / "fixtures"


def _load_status_module():
    spec = importlib.util.spec_from_file_location("sol_luna_status_test_module", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("status_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


STATUS = _load_status_module()


class SolLunaStatusTests(unittest.TestCase):
    def _payload(self, task_id="root-id-secret", profile="fast"):
        value = json.loads((FIXTURES / "receipt_accepted.json").read_text())
        value["codex_task_id"] = task_id
        value["started_at"] = "2026-08-01T10:00:00Z"
        value["closed_at"] = "2026-08-01T10:05:00Z"
        value["root_runtime"] = {
            "model": "gpt-5.6-sol",
            "reasoning": "xhigh",
            "service_tier": "standard",
            "service_tier_provenance": "global-unset-standard",
        }
        value["delegated_lanes"] = [{
            "lane_id": "status-child",
            "role": "luna_max_fast",
            "reasoning": "max",
            "tier": "fast",
            "attempts": 1,
            "retries": 0,
            "escalation": {"target": "luna_max_fast", "reason": "genuine_ambiguity"},
            "max_reason": "genuine_ambiguity",
            "outcome": "completed",
            "useful": True,
        }]
        if profile == "standard":
            value["repository"]["hashes"]["roles"] = {
                role.replace("_fast", "_standard"): digest
                for role, digest in value["repository"]["hashes"]["roles"].items()
            }
            lane = value["delegated_lanes"][0]
            lane["role"] = "luna_max_standard"
            lane["tier"] = "standard"
            lane["escalation"]["target"] = "luna_max_standard"
        return value

    def _workspace(self, *, task_id="root-id-secret", child_records=None, root_records=None, unrelated=False, profile="fast", payload=None, include_child=True):
        temporary = tempfile.TemporaryDirectory()
        base = Path(temporary.name)
        receipts = base / "receipts"
        sessions = base / "sessions"
        sessions.mkdir()
        close_receipt(payload or self._payload(task_id, profile), receipts)
        if root_records is None:
            root_records = [json.loads(line) for line in (FIXTURES / "root.jsonl").read_text().splitlines()]
        if child_records is None and include_child:
            child_records = [json.loads(line) for line in (FIXTURES / "luna_child.jsonl").read_text().splitlines()]
        if child_records is None:
            child_records = []
        root_records = copy.deepcopy(root_records)
        child_records = copy.deepcopy(child_records)
        if profile == "standard" and child_records:
            child_records[0]["payload"]["agent_role"] = "luna_max_standard"
            for item in child_records:
                settings = item.get("payload", {}).get("thread_settings")
                if isinstance(settings, dict) and settings.get("model") == "gpt-5.6-luna":
                    settings["service_tier"] = "standard"
        for item in [*root_records, *child_records]:
            item.setdefault("schema_version", 1)
        root_text = "\n".join(json.dumps(item, separators=(",", ":")) for item in root_records) + "\n"
        (sessions / "root.jsonl").write_text(root_text)
        if child_records:
            child_text = "\n".join(json.dumps(item, separators=(",", ":")) for item in child_records) + "\n"
            (sessions / "child.jsonl").write_text(child_text)
        if unrelated:
            records = [json.loads(line) for line in (FIXTURES / "root.jsonl").read_text().splitlines()]
            for item in records:
                item["schema_version"] = 1
            records[0]["payload"]["session_id"] = "unrelated-session-secret"
            records[0]["payload"]["id"] = "unrelated-id-secret"
            (sessions / "unrelated.jsonl").write_text("\n".join(json.dumps(item, separators=(",", ":")) for item in records) + "\n")
        return temporary, base, receipts, sessions

    def _run(self, base, receipts, sessions, *extra, script=SCRIPT):
        environment = dict(os.environ)
        environment["HOME"] = str(base / "home")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(script), "--root", str(ROOT), "--receipts-dir", str(receipts), "--session-root", str(sessions), *extra],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
        )

    def _json(self, base, receipts, sessions, *extra, script=SCRIPT):
        completed = self._run(base, receipts, sessions, *extra, "--format", "json", script=script)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        return json.loads(completed.stdout), completed.stdout

    def test_attributed_workflow_weighting_receipts_timing_and_budget(self):
        temporary, base, receipts, sessions = self._workspace(unrelated=True)
        self.addCleanup(temporary.cleanup)
        report, rendered = self._json(base, receipts, sessions, "--budget", "825")
        self.assertEqual(report["mode"], "session+receipts")
        self.assertEqual(report["session_probe"]["status"], "pass")
        self.assertEqual(report["session_probe"]["selected_count"], 2)
        self.assertEqual(report["usage"]["observed_total_tokens"], 315)
        self.assertEqual(report["usage"]["estimated_weighted_usage"], 412.5)
        self.assertEqual(report["usage"]["fast_multiplier"], 2.5)
        self.assertIsNone(report["usage"]["billed_usage"])
        self.assertEqual(report["receipts"]["accepted_count"], 1)
        self.assertEqual(report["receipts"]["receipt_coverage"], "not-applicable")
        self.assertEqual(report["receipts"]["receipt_coverage_reason"], "m4_terminal_retirement")
        self.assertEqual(report["pilot"]["state"], "retired-non-retryable")
        self.assertIsNone(report["pilot"]["next_slot"])
        self.assertFalse(report["pilot"]["next_slot_eligible"])
        self.assertEqual(report["pilot"]["comparison"]["status"], "retired-no-comparison")
        self.assertEqual(report["milestone"]["id"], "m2-receipts")
        self.assertEqual(report["milestone"]["scope"], "latest-terminal-after-m4-retirement")
        self.assertEqual(report["latest_accepted_outcome"]["milestone_id"], "m2-receipts")
        self.assertEqual(report["timing"]["time_to_verified_outcome_ms"], 300000)
        self.assertEqual(report["budget"]["warning_threshold"], 50)
        self.assertEqual(report["budget"]["remaining"], 412.5)
        self.assertEqual(report["budget"]["variance"], -0.5)
        self.assertEqual(report["budget"]["burn_rate"], 4950.0)
        self.assertEqual(report["delegation_quality"]["lane_count"], 1)
        self.assertEqual(report["delegation_quality"]["spawn_precision"], 1.0)
        for secret in ("root-id-secret", "root-session-secret", "child-id-secret", "child-session-secret", str(base), str(ROOT)):
            self.assertNotIn(secret, rendered)

    def test_parent_thread_only_child_is_joined(self):
        child = [json.loads(line) for line in (FIXTURES / "luna_child.jsonl").read_text().splitlines()]
        child[0]["payload"].pop("forked_from_id", None)
        child[0]["payload"]["parent_thread_id"] = "root-id-secret"
        temporary, base, receipts, sessions = self._workspace(child_records=child)
        self.addCleanup(temporary.cleanup)
        report, _ = self._json(base, receipts, sessions)
        self.assertEqual(report["mode"], "session+receipts")
        self.assertEqual(report["session_probe"]["child_count"], 1)

    def test_standard_profile_receipt_session_and_usage_are_automatic(self):
        temporary, base, receipts, sessions = self._workspace(profile="standard")
        self.addCleanup(temporary.cleanup)
        report, _ = self._json(base, receipts, sessions)
        self.assertEqual(report["mode"], "session+receipts")
        self.assertEqual(report["luna_profile"], {"tier": "standard", "provenance": "latest-receipt"})
        self.assertEqual(report["session_probe"]["status"], "pass")
        self.assertEqual(report["usage"]["observed_total_tokens"], 315)
        self.assertEqual(report["usage"]["estimated_weighted_usage"], 315.0)
        self.assertEqual(report["delegation_quality"]["max_count"], 1)
        child_group = next(group for group in report["usage"]["groups"] if group["role"] == "luna_max_standard")
        self.assertEqual(child_group["service_tier"], "standard")

    def test_app_task_transport_is_counted_without_claiming_native_child(self):
        payload = self._payload()
        payload["delegated_lanes"][0]["transport"] = {
            "requested": "native_luna_subagent",
            "used": "codex_app_task",
            "native_failure": "custom_role_rejected",
            "fallback_authorized": True,
            "fallback_attempts": 1,
            "fallback_outcome": "completed",
            "task_ref": "ct1-" + "c" * 64,
        }
        temporary, base, receipts, sessions = self._workspace(payload=payload, include_child=False)
        self.addCleanup(temporary.cleanup)
        report, rendered = self._json(base, receipts, sessions)
        quality = report["delegation_quality"]
        self.assertEqual(report["session_probe"]["status"], "pass")
        self.assertEqual(report["session_probe"]["child_count"], 0)
        self.assertEqual(quality["native_transport_failure_count"], 1)
        self.assertEqual(quality["app_task_fallback_count"], 1)
        self.assertEqual(quality["app_task_fallback_completed_count"], 1)
        self.assertEqual(quality["app_task_fallback_failed_count"], 0)
        self.assertEqual(quality["app_task_fallback_unavailable_count"], 0)
        self.assertEqual(quality["sol_after_transport_failure_count"], 0)
        self.assertNotIn(payload["delegated_lanes"][0]["transport"]["task_ref"], rendered)

    def test_capability_failures_fall_back_without_zero_usage(self):
        cases = {}

        child_no_baseline = [json.loads(line) for line in (FIXTURES / "luna_child.jsonl").read_text().splitlines()]
        last_start = max(i for i, item in enumerate(child_no_baseline) if item.get("payload", {}).get("type") == "task_started")
        child_no_baseline = [item for i, item in enumerate(child_no_baseline) if not (i < last_start and item.get("payload", {}).get("type") == "token_count")]
        cases["missing_child_baseline"] = {"child_records": child_no_baseline}

        wrong_runtime = [json.loads(line) for line in (FIXTURES / "luna_child.jsonl").read_text().splitlines()]
        for item in wrong_runtime:
            if item.get("payload", {}).get("type") == "thread_settings_applied":
                item["payload"]["thread_settings"]["reasoning_effort"] = "high"
        cases["runtime_mismatch"] = {"child_records": wrong_runtime}

        wrong_schema = [json.loads(line) for line in (FIXTURES / "root.jsonl").read_text().splitlines()]
        wrong_schema[0]["schema_version"] = 2
        cases["schema_mismatch"] = {"root_records": wrong_schema}
        cases["task_mismatch"] = {"task_id": "different-task"}

        for name, options in cases.items():
            with self.subTest(name=name):
                temporary, base, receipts, sessions = self._workspace(**options)
                try:
                    report, _ = self._json(base, receipts, sessions)
                    self.assertEqual(report["mode"], "receipt-only")
                    self.assertEqual(report["usage"]["status"], "unknown")
                    self.assertIsNone(report["usage"]["observed_total_tokens"])
                    self.assertIsNone(report["usage"]["estimated_weighted_usage"])
                    self.assertIsNone(report["timing"]["time_to_verified_outcome_ms"])
                    self.assertIsNone(report["budget"]["consumed"])
                finally:
                    temporary.cleanup()

    def test_incomplete_token_snapshots_and_unversioned_records_fail_closed(self):
        missing_dimension = [json.loads(line) for line in (FIXTURES / "root.jsonl").read_text().splitlines()]
        for item in missing_dimension:
            usage = item.get("payload", {}).get("info", {}).get("total_token_usage")
            if isinstance(usage, dict):
                usage.pop("input_tokens", None)
        inconsistent_total = copy.deepcopy(missing_dimension)
        for item in inconsistent_total:
            usage = item.get("payload", {}).get("info", {}).get("total_token_usage")
            if isinstance(usage, dict):
                usage["input_tokens"] = 1

        for name, records in (("missing_dimension", missing_dimension), ("inconsistent_total", inconsistent_total)):
            with self.subTest(name=name):
                temporary, base, receipts, sessions = self._workspace(root_records=records)
                try:
                    report, _ = self._json(base, receipts, sessions)
                    self.assertEqual(report["mode"], "receipt-only")
                    self.assertEqual(report["usage"]["status"], "unknown")
                    self.assertIsNone(report["usage"]["observed_total_tokens"])
                    self.assertEqual(report["session_probe"]["schema_status"], "failed")
                finally:
                    temporary.cleanup()

        temporary, base, receipts, sessions = self._workspace()
        self.addCleanup(temporary.cleanup)
        path = sessions / "root.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        for item in records:
            item.pop("schema_version", None)
        path.write_text("\n".join(json.dumps(item, separators=(",", ":")) for item in records) + "\n")
        report, _ = self._json(base, receipts, sessions)
        self.assertEqual(report["mode"], "receipt-only")
        self.assertEqual(report["usage"]["status"], "unknown")
        self.assertEqual(report["session_probe"]["schema_status"], "failed")

    def test_malformed_duplicate_oversize_extra_child_and_symlink_fail_closed(self):
        temporary, base, receipts, sessions = self._workspace()
        self.addCleanup(temporary.cleanup)
        with (sessions / "duplicate.jsonl").open("w") as handle:
            handle.write('{"type":"session_meta","type":"session_meta"}\n')
        report, rendered = self._json(base, receipts, sessions)
        self.assertEqual(report["mode"], "receipt-only")
        self.assertIn("session_file_unrecognized", report["warnings"])
        self.assertNotIn(str(sessions), rendered)

        (sessions / "duplicate.jsonl").unlink()
        (sessions / "oversize.jsonl").write_bytes(b"x" * (STATUS.MAX_FILE_BYTES + 1))
        report, _ = self._json(base, receipts, sessions)
        self.assertEqual(report["mode"], "receipt-only")
        self.assertIn("session_scan_bounded", report["warnings"])

        (sessions / "oversize.jsonl").unlink()
        extra = (sessions / "extra.jsonl")
        records = [json.loads(line) for line in (FIXTURES / "luna_child.jsonl").read_text().splitlines()]
        for item in records:
            item["schema_version"] = 1
        text = "\n".join(json.dumps(item, separators=(",", ":")) for item in records) + "\n"
        extra.write_text(text.replace("child-session-secret", "extra-session-secret").replace("child-id-secret", "extra-id-secret"))
        report, _ = self._json(base, receipts, sessions)
        self.assertEqual(report["mode"], "receipt-only")
        self.assertEqual(report["session_probe"]["reason"], "runtime_or_lane_mismatch")

        extra.unlink()
        linked = sessions / "linked.jsonl"
        os.symlink(sessions / "root.jsonl", linked)
        report, _ = self._json(base, receipts, sessions)
        self.assertEqual(report["mode"], "receipt-only")
        self.assertIn("unsafe_session_path", report["warnings"])

    def test_budget_thresholds_and_unknown(self):
        expected = ((1000, None, "below-50"), (825, 50, "warning-50"), (550, 75, "warning-75"), (450, 90, "warning-90"), (400, 90, "over"))
        for limit, threshold, status in expected:
            with self.subTest(limit=limit):
                result = STATUS._budget(limit, 412.5, 300000)
                self.assertEqual(result["warning_threshold"], threshold)
                self.assertEqual(result["status"], status)
        unknown = STATUS._budget(1000, None, None)
        self.assertEqual(unknown["status"], "unknown")
        self.assertIsNone(unknown["remaining"])

    def test_rate_card_rejects_missing_weight_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            card = json.loads((ROOT / "config" / "rate-card.v1.json").read_text())
            card["weights"]["model"] = {}
            (root / "config" / "rate-card.v1.json").write_text(json.dumps(card))
            parsed, warnings = STATUS._rate_card(root)
            self.assertEqual(parsed, {})
            self.assertEqual(warnings, ["rate_card_drift"])

            for key in ("owner", "provenance"):
                malformed = json.loads((ROOT / "config" / "rate-card.v1.json").read_text())
                malformed.pop(key)
                (root / "config" / "rate-card.v1.json").write_text(json.dumps(malformed))
                parsed, warnings = STATUS._rate_card(root)
                self.assertEqual(parsed, {}, key)
                self.assertEqual(warnings, ["rate_card_drift"], key)

            malformed = json.loads((ROOT / "config" / "rate-card.v1.json").read_text())
            malformed["weights"]["service_tier"]["fast"] = 0.5
            (root / "config" / "rate-card.v1.json").write_text(json.dumps(malformed))
            parsed, warnings = STATUS._rate_card(root)
            self.assertEqual(parsed, {})
            self.assertEqual(warnings, ["rate_card_drift"])

    def test_markdown_is_deterministic_complete_and_private(self):
        temporary, base, receipts, sessions = self._workspace()
        self.addCleanup(temporary.cleanup)
        first = self._run(base, receipts, sessions)
        second = self._run(base, receipts, sessions)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(first.stdout, second.stdout)
        for section in ("Milestone", "Receipts", "M4 pilot", "Session capability probe", "Usage", "Timing", "Delegation and quality", "Budget", "Drift and freshness", "Provenance and unknowns", "Routing recommendation"):
            self.assertIn(f"## {section}", first.stdout)
        report, _ = self._json(base, receipts, sessions)
        self.assertEqual(first.stdout.count(report["routing_recommendation"]), 1)
        for secret in ("root-id-secret", "root-session-secret", "child-id-secret", "child-session-secret", str(base), str(ROOT)):
            self.assertNotIn(secret, first.stdout)

    def test_global_layout_works_with_explicit_root(self):
        temporary, base, receipts, sessions = self._workspace()
        self.addCleanup(temporary.cleanup)
        global_skill = base / "home" / ".codex" / "skills" / "sol-luna-status"
        shutil.copytree(SKILL, global_skill)
        report, _ = self._json(base, receipts, sessions, script=global_skill / "scripts" / "sol_luna_status.py")
        self.assertEqual(report["mode"], "session+receipts")

    def test_standard_profile_active_drift_check(self):
        temporary, base, receipts, sessions = self._workspace()
        self.addCleanup(temporary.cleanup)
        home = base / "profile-home"
        home.mkdir()
        codex = home / ".codex"
        installer.install(
            ROOT,
            codex,
            home,
            apply=True,
            with_usage=False,
            luna_tier="standard",
        )
        report, _ = self._json(
            base,
            receipts,
            sessions,
            "--active-root", str(codex),
            "--active-config", str(codex / "config.toml"),
        )
        self.assertTrue(report["drift"]["routing_contract"])
        self.assertTrue(report["drift"]["active_runtime"])
        self.assertEqual(report["luna_profile"], {"tier": "standard", "provenance": "install-state"})

        state_path = codex / installer.INSTALL_STATE_NAME
        malformed = json.loads(state_path.read_text())
        malformed["schema_version"] = True
        state_path.write_text(json.dumps(malformed))
        self.assertIsNone(STATUS._install_state_tier(codex))
        malformed["schema_version"] = 1
        malformed["active_luna_tier"] = []
        state_path.write_text(json.dumps(malformed))
        fallback, _ = self._json(
            base,
            receipts,
            sessions,
            "--active-root", str(codex),
            "--active-config", str(codex / "config.toml"),
        )
        self.assertEqual(fallback["luna_profile"], {"tier": "fast", "provenance": "latest-receipt"})
        self.assertNotIn("status_report_failed", fallback["warnings"])

    def test_pilot_registry_drives_coverage_deadline_and_recommendation(self):
        temporary, base, receipts, sessions = self._workspace()
        self.addCleanup(temporary.cleanup)
        pilot_home = base / "pilot"
        starts = base / "starts"
        pilot_tool.setup_environments(ROOT / "config" / "m4-pilot.v1.json", ROOT, pilot_home, apply=True)
        ready, _ = self._json(
            base,
            receipts,
            sessions,
            "--allow-retired-m4-audit",
            "--plan", str(ROOT / "config" / "m4-pilot.v1.json"),
            "--pilot-home", str(pilot_home),
            "--starts-dir", str(starts),
            "--as-of", "2026-08-02T23:45:00Z",
        )
        self.assertEqual(ready["pilot"]["state"], "ready")
        self.assertFalse(ready["drift"]["active_runtime"])
        self.assertIn("historical M4 audit only", ready["routing_recommendation"])
        pilot_tool.register_start(
            ROOT / "config" / "m4-pilot.v1.json",
            ROOT,
            pilot_home,
            starts,
            "m4-01",
            "milestone-01",
            "task-01",
            "2026-08-02T23:45:00Z",
        )
        pending, _ = self._json(
            base,
            receipts,
            sessions,
            "--allow-retired-m4-audit",
            "--plan", str(ROOT / "config" / "m4-pilot.v1.json"),
            "--pilot-home", str(pilot_home),
            "--starts-dir", str(starts),
            "--as-of", "2026-08-03T00:14:59Z",
        )
        self.assertEqual(pending["pilot"]["state"], "in-progress")
        self.assertEqual(pending["receipts"]["receipt_coverage"], "in-progress")
        self.assertEqual(pending["pilot"]["next_slot"]["slot_id"], "m4-02")
        overdue, _ = self._json(
            base,
            receipts,
            sessions,
            "--allow-retired-m4-audit",
            "--plan", str(ROOT / "config" / "m4-pilot.v1.json"),
            "--pilot-home", str(pilot_home),
            "--starts-dir", str(starts),
            "--as-of", "2026-08-03T00:15:00Z",
        )
        self.assertEqual(overdue["pilot"]["state"], "blocked")
        self.assertIn("historical M4 audit only", overdue["routing_recommendation"])

    def test_retired_m4_blocks_default_restart_but_explicit_plan_remains_audit_capable(self):
        retirement = STATUS._m4_retirement(ROOT)
        self.assertIsNotNone(retirement)
        summary = STATUS._retired_m4_summary(retirement)
        self.assertEqual(summary["state"], "retired-non-retryable")
        self.assertIsNone(summary["next_slot"])
        self.assertFalse(summary["next_slot_eligible"])
        self.assertEqual(summary["comparison"]["promotion_status"], "blocked-terminal-retirement")
        self.assertIn("do not restart or promote", STATUS._recommendation({"errors": []}, False, None, {}, summary))

        missing = STATUS._blocked_m4_retirement_summary()
        self.assertEqual(missing["state"], "retirement-evidence-unavailable")
        self.assertIsNone(missing["next_slot"])
        self.assertFalse(missing["next_slot_eligible"])
        self.assertIn(
            "do not register, restart, promote, or launch",
            STATUS._recommendation({"errors": []}, False, None, {}, missing),
        )

        temporary, base, receipts, sessions = self._workspace()
        self.addCleanup(temporary.cleanup)
        still_retired, _ = self._json(
            base,
            receipts,
            sessions,
            "--plan", str(ROOT / "config" / "m4-pilot.v1.json"),
            "--as-of", "2026-08-02T23:43:28Z",
        )
        self.assertEqual(still_retired["pilot"]["state"], "retired-non-retryable")
        self.assertIsNone(still_retired["pilot"]["next_slot"])

        audit, _ = self._json(
            base,
            receipts,
            sessions,
            "--allow-retired-m4-audit",
            "--plan", str(ROOT / "config" / "m4-pilot.v1.json"),
            "--as-of", "2026-08-02T23:43:28Z",
        )
        self.assertTrue(audit["pilot"]["audit_only"])
        self.assertEqual(audit["pilot"]["state"], "setup-unverified")
        self.assertEqual(audit["pilot"]["next_slot"]["slot_id"], "m4-01")
        self.assertFalse(audit["pilot"]["next_slot_eligible"])
        self.assertIn("historical M4 audit only", audit["routing_recommendation"])

    def test_active_drift_changes_recommendation_and_invalid_args_are_nonzero(self):
        temporary, base, receipts, sessions = self._workspace()
        self.addCleanup(temporary.cleanup)
        missing_active = base / "missing-active"
        report, _ = self._json(base, receipts, sessions, "--active-root", str(missing_active), "--active-config", str(missing_active / "config.toml"))
        self.assertFalse(report["drift"]["active_runtime"])
        self.assertTrue(report["routing_recommendation"].startswith("direct Sol"))

        invalid = self._run(base, receipts, sessions, "--budget", "0", "--format", "json")
        self.assertEqual(invalid.returncode, 2)
        self.assertNotIn("Traceback", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
