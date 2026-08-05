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
from scripts.receipt_tool import build_routine_record, close_receipt


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
    def _routine_record(
        self,
        *,
        recorded_on="2026-08-04",
        useful=True,
        outcome="completed",
        check_statuses=("pass",),
        routing_policy="routing-policy.v1.5",
        role_kind="tester",
        task_class="substantial_validation",
        benefit_code="parallel_latency",
    ):
        record = build_routine_record(
            routing_policy=routing_policy,
            profile="fast",
            role_kind=role_kind,
            task_class=task_class,
            benefit_code=benefit_code,
            useful=useful,
            outcome=outcome,
            checks=[
                {"name": f"acceptance-{index}", "status": status}
                for index, status in enumerate(check_statuses, 1)
            ],
        )
        record["recorded_on"] = recorded_on
        return record

    def _write_routine_records(self, workspace, records, *, legacy=None):
        metadata = workspace / ".sol-luna"
        if not metadata.exists():
            metadata.mkdir(mode=0o700)
        records_dir = metadata / "routine-records"
        records_dir.mkdir(mode=0o700)
        for index, record in enumerate(records, 1):
            path = records_dir / f"record-{index}.json"
            path.write_text(json.dumps(record, separators=(",", ":")))
            os.chmod(path, 0o600)
        if legacy is not None:
            path = records_dir / "legacy.json"
            path.write_text(json.dumps(legacy, separators=(",", ":")))
            os.chmod(path, 0o600)
        return records_dir

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
        (base / ".git").mkdir()
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
            [sys.executable, str(script), "--root", str(ROOT), "--workspace-root", str(base), "--receipts-dir", str(receipts), "--session-root", str(sessions), *extra],
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
        self.assertEqual(report["luna_profile"]["tier"], None)
        self.assertEqual(report["luna_profile"]["provenance"], "not-inferred")
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

    def test_missing_optional_routine_receipts_are_valid_and_usage_stays_unknown(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        (base / ".git").mkdir()
        receipts = base / "missing-receipts"
        sessions = base / "sessions"
        sessions.mkdir()
        report, rendered = self._json(base, receipts, sessions)
        self.assertEqual(report["routine_records"]["optional_missing"], True)
        self.assertEqual(report["routine_records"]["collection"], "ready-no-records")
        self.assertEqual(report["routine_records"]["invalid"], 0)
        self.assertEqual(report["routine_records"]["usage_attribution"], "unknown")
        self.assertIsNone(report["routine_records"]["total_tokens"])
        self.assertNotIn("invalid_routine_records_observed", report["warnings"])
        self.assertNotIn("create a validated milestone receipt", report["routing_recommendation"])
        self.assertNotIn("0 (unknown)", rendered)

        metadata = base / ".sol-luna"
        metadata.mkdir(mode=0o700)
        unsafe_records = metadata / "routine-records"
        unsafe_records.mkdir()
        os.chmod(unsafe_records, 0o755)
        report, _ = self._json(
            base,
            receipts,
            sessions,
            "--routine-records-dir",
            str(unsafe_records),
        )
        self.assertEqual(report["routine_records"]["optional_missing"], False)
        self.assertEqual(report["routine_records"]["invalid"], 1)
        self.assertEqual(report["routine_records"]["collection"], "partial")
        self.assertIn("invalid_routine_records_observed", report["warnings"])

        records = metadata / "routine-records"
        unsafe_records.rmdir()
        records.mkdir(mode=0o700)
        record = build_routine_record(
            routing_policy="routing-policy.v1.5",
            profile="fast",
            role_kind="tester",
            task_class="substantial_validation",
            benefit_code="parallel_latency",
            useful=True,
            outcome="completed",
            checks=[{"name": "acceptance-1", "status": "pass"}],
        )
        path = records / "record.json"
        path.write_text(json.dumps(record))
        os.chmod(path, 0o600)
        report, _ = self._json(
            base,
            receipts,
            sessions,
            "--routine-records-dir",
            str(records),
        )
        self.assertEqual(report["mode"], "minimal-records")
        self.assertEqual(report["routine_records"]["observed"], 1)
        self.assertEqual(report["routine_records"]["collection"], "active")
        self.assertEqual(report["routine_records"]["completed"], 1)
        self.assertEqual(report["routine_records"]["check_pass"], 1)
        self.assertEqual(report["delegation_quality"]["spawn_precision"], 1.0)
        self.assertIsNone(report["routine_records"]["total_tokens"])
        summary = self._run(
            base,
            receipts,
            sessions,
            "--routine-records-dir",
            str(records),
        )
        self.assertEqual(summary.returncode, 0)
        self.assertIn("Metrics: 1 delegated outcome in the last 30 days", summary.stdout)
        self.assertIn("Delegation: 1/1 accepted as useful", summary.stdout)

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
        for label in ("Health:", "Version:", "Metrics:", "Delegation:", "Trend:", "Next:"):
            self.assertIn(label, first.stdout)
        self.assertNotIn("## M4 pilot", first.stdout)
        detail = self._run(base, receipts, sessions, "--detail")
        self.assertEqual(detail.returncode, 0)
        for section in ("Installation", "Current project metrics", "Current receipts and usage", "Current drift and provenance"):
            self.assertIn(f"## {section}", detail.stdout)
        self.assertNotIn("M4", detail.stdout)
        historical = self._run(base, receipts, sessions, "--historical")
        self.assertIn("## Retired M4 pilot", historical.stdout)
        self.assertIn("retired and non-retryable", historical.stdout)
        for secret in ("root-id-secret", "root-session-secret", "child-id-secret", "child-session-secret", str(base), str(ROOT)):
            self.assertNotIn(secret, first.stdout)
            self.assertNotIn(secret, detail.stdout)

    def test_summary_reports_healthy_and_pending_installation_plainly(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / ".git").mkdir()
            home = base / "home"
            home.mkdir()
            codex = home / ".codex"
            installer.install(ROOT, codex, home, apply=True, with_usage=False)
            receipts = base / "missing-receipts"
            sessions = base / "sessions"
            sessions.mkdir()

            healthy = self._run(base, receipts, sessions)
            self.assertEqual(healthy.returncode, 0, healthy.stderr)
            self.assertIn("Health: Healthy", healthy.stdout)
            self.assertIn("Version: 0.6.1 · Fast", healthy.stdout)
            self.assertIn("Metrics: Ready; no dated delegated outcomes", healthy.stdout)
            self.assertIn("Next: No lifecycle action needed; no policy change suggested.", healthy.stdout)

            installer.mark_update_pending(codex)
            pending = self._run(base, receipts, sessions)
            self.assertEqual(pending.returncode, 0, pending.stderr)
            self.assertIn("Health: Update pending", pending.stdout)
            self.assertIn("The package refresh did not finish", pending.stdout)
            self.assertIn("no restart is needed yet", pending.stdout)

            installer.mark_package_refreshed(codex)
            refreshed = self._run(base, receipts, sessions)
            self.assertIn("Restart Codex, begin a new task", refreshed.stdout)

            malformed = json.loads((codex / installer.INSTALL_STATE_NAME).read_text())
            malformed["schema_version"] = True
            (codex / installer.INSTALL_STATE_NAME).write_text(json.dumps(malformed))
            invalid = self._run(base, receipts, sessions)
            self.assertEqual(invalid.returncode, 0, invalid.stderr)
            self.assertIn("Health: Needs attention", invalid.stdout)

    def test_plugin_workflow_status_observes_separate_active_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / ".git").mkdir()
            records = self._write_routine_records(base, [self._routine_record()])
            sessions = base / "sessions"
            sessions.mkdir()
            receipts = base / "missing-receipts"
            plugin = ROOT / "plugins" / "sol-luna-orchestration-kit"
            script = plugin / "skills" / "sol-luna-status" / "scripts" / "sol_luna_status.py"
            completed = subprocess.run(
                [
                    sys.executable, str(script), "--root", str(plugin),
                    "--workspace-root", str(base),
                    "--receipts-dir", str(receipts), "--session-root", str(sessions),
                    "--as-of", "2026-08-04",
                ],
                cwd=base,
                env={**os.environ, "HOME": str(base / "home"), "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Health: Workflow-only", completed.stdout)
            self.assertIn("Version: 0.6.1 · Workflow-only · Fast workflow routing default", completed.stdout)
            self.assertIn("1 delegated outcome in the last 30 days", completed.stdout)
            self.assertIn("Full roles are not installed", completed.stdout)

    def test_unsafe_or_missing_workspace_reports_metrics_unavailable_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            sessions = base / "sessions"
            sessions.mkdir()
            receipts = base / "receipts"
            for unsafe in ("/", str(Path.home()), tempfile.gettempdir(), str(base)):
                completed = subprocess.run(
                    [
                        sys.executable, str(SCRIPT), "--root", str(ROOT),
                        "--workspace-root", unsafe, "--receipts-dir", str(receipts),
                        "--session-root", str(sessions), "--format", "json",
                    ],
                    cwd=ROOT,
                    env={**os.environ, "HOME": str(base / "home"), "PYTHONDONTWRITEBYTECODE": "1"},
                    text=True,
                    capture_output=True,
                    timeout=30,
                )
                report = json.loads(completed.stdout)
                self.assertEqual(report["workspace"]["status"], "unavailable", unsafe)
                self.assertEqual(report["routine_records"]["collection"], "unavailable", unsafe)
                self.assertIsNone(report["routine_records"]["observed"], unsafe)

            project = base / "project"
            project.mkdir()
            (project / ".git").mkdir()
            linked = base / "linked-project"
            linked.symlink_to(project, target_is_directory=True)
            self.assertIsNone(STATUS._safe_workspace_candidate(linked))

    def test_windows_legacy_and_policy_cohorts_are_deterministic(self):
        current = [self._routine_record(recorded_on="2026-08-04") for _ in range(10)]
        previous = [self._routine_record(recorded_on="2026-07-05") for _ in range(10)]
        other_policy = [
            self._routine_record(
                recorded_on="2026-08-04", useful=False, outcome="failed",
                check_statuses=("fail",), routing_policy="routing-policy.v1.6",
            )
            for _ in range(10)
        ]
        legacy = {
            "schema_version": 1,
            "version": "routine-delegation-record.v1",
            "spawn": {"decision": "delegate", "useful": False},
            "outcome": "failed",
            "checks": [{"name": "legacy", "status": "fail"}],
            "usage": {"attribution": "unknown", "total_tokens": None},
        }
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / ".git").mkdir()
            records = self._write_routine_records(base, current + previous + other_policy, legacy=legacy)
            sessions = base / "sessions"
            sessions.mkdir()
            report, _ = self._json(
                base, base / "receipts", sessions,
                "--routine-records-dir", str(records), "--as-of", "2026-08-04",
            )
            routine = report["routine_records"]
            self.assertEqual(routine["current_window"]["start"], "2026-07-06")
            self.assertEqual(routine["previous_window"]["end"], "2026-07-05")
            self.assertEqual(routine["current_window"]["observed"], 10)
            self.assertEqual(routine["previous_window"]["observed"], 10)
            self.assertEqual(routine["legacy_lifetime_count"], 1)
            self.assertEqual(routine["v2_lifetime_count"], 30)
            self.assertEqual(len(routine["cohorts"]), 2)
            self.assertEqual(report["optimization_advisor"]["primary_code"], "no_issue_detected")
            self.assertEqual(report["optimization_advisor"]["trend"], "comparable-observational-windows")

    def test_advisor_sample_and_review_threshold_boundaries(self):
        rules = STATUS._advisor_rules(ROOT)
        self.assertIsNotNone(rules)
        good = lambda: self._routine_record()

        self.assertEqual(
            STATUS._evaluate_advisor([good() for _ in range(9)], [], rules)["primary_code"],
            "insufficient_evidence",
        )
        at_usefulness = [self._routine_record(useful=index < 7) for index in range(10)]
        self.assertEqual(STATUS._evaluate_advisor(at_usefulness, [], rules)["primary_code"], "no_issue_detected")
        below_usefulness = [self._routine_record(useful=index < 6) for index in range(10)]
        self.assertIn("review_spawn_precision", STATUS._evaluate_advisor(below_usefulness, [], rules)["recommendation_codes"])

        at_failure = [self._routine_record(outcome="failed" if index == 0 else "completed") for index in range(10)]
        self.assertNotIn("review_failure_rate", STATUS._evaluate_advisor(at_failure, [], rules)["recommendation_codes"])
        above_failure = [self._routine_record(outcome="failed" if index < 2 else "completed") for index in range(10)]
        self.assertIn("review_failure_rate", STATUS._evaluate_advisor(above_failure, [], rules)["recommendation_codes"])

        at_check = [self._routine_record(check_statuses=("fail" if index == 0 else "pass",)) for index in range(10)]
        self.assertNotIn("review_check_failures", STATUS._evaluate_advisor(at_check, [], rules)["recommendation_codes"])
        above_check = [self._routine_record(check_statuses=("fail" if index < 2 else "pass",)) for index in range(10)]
        self.assertIn("review_check_failures", STATUS._evaluate_advisor(above_check, [], rules)["recommendation_codes"])

        previous_nine = [good() for _ in range(9)]
        previous_ten = [good() for _ in range(10)]
        self.assertEqual(STATUS._evaluate_advisor([good() for _ in range(10)], previous_nine, rules)["trend"], "insufficient-comparable-prior-evidence")
        self.assertEqual(STATUS._evaluate_advisor([good() for _ in range(10)], previous_ten, rules)["trend"], "comparable-observational-windows")

        group = [
            self._routine_record(
                role_kind="critic", task_class="independent_risk_review",
                benefit_code="independent_risk_review", outcome="failed" if index == 0 else "completed",
            )
            for index in range(5)
        ] + [good() for _ in range(5)]
        result = STATUS._evaluate_advisor(group, [], rules)
        self.assertTrue(any(
            finding.get("scope") == "role_kind" and finding.get("value") == "critic"
            for finding in result["findings"]
        ))
        self.assertFalse(result["automatic_policy_change"])
        self.assertTrue(result["human_approval_required"])

    def test_lifecycle_precedes_advisor_and_status_makes_no_prohibited_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / ".git").mkdir()
            records = self._write_routine_records(
                base,
                [
                    self._routine_record(
                        useful=False, outcome="failed", check_statuses=("fail",)
                    )
                    for _ in range(10)
                ],
            )
            home = base / "home"
            home.mkdir()
            codex = home / ".codex"
            installer.install(ROOT, codex, home, apply=True, with_usage=False)
            installer.mark_update_pending(codex)
            sessions = base / "sessions"
            sessions.mkdir()
            result = self._run(
                base, base / "receipts", sessions,
                "--routine-records-dir", str(records), "--as-of", "2026-08-04",
            )
            self.assertIn("The package refresh did not finish", result.stdout)
            self.assertNotIn("review observations before", result.stdout)
            lowered = result.stdout.lower()
            for prohibited in ("savings", "caused by", "automatic promotion", "automatically mutate"):
                self.assertNotIn(prohibited, lowered)

    def test_duplicate_routine_json_and_file_permissions_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / ".git").mkdir()
            records = self._write_routine_records(base, [])
            duplicate = records / "duplicate.json"
            duplicate.write_text('{"schema_version":2,"schema_version":2}')
            os.chmod(duplicate, 0o600)
            loose = records / "loose.json"
            loose.write_text(json.dumps(self._routine_record()))
            os.chmod(loose, 0o644)
            sessions = base / "sessions"
            sessions.mkdir()
            report, rendered = self._json(
                base, base / "receipts", sessions,
                "--routine-records-dir", str(records), "--as-of", "2026-08-04",
            )
            self.assertEqual(report["routine_records"]["invalid"], 2)
            self.assertEqual(report["routine_records"]["collection"], "partial")
            self.assertNotIn(str(base), rendered)

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
        self.assertEqual(report["luna_profile"]["tier"], "standard")
        self.assertEqual(report["luna_profile"]["provenance"], "install-state")
        self.assertTrue(report["luna_profile"]["installed"])

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
        self.assertIsNone(fallback["luna_profile"]["tier"])
        self.assertEqual(fallback["luna_profile"]["provenance"], "not-inferred")
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

        home = base / "home"
        home.mkdir()
        codex = home / ".codex"
        installer.install(ROOT, codex, home, apply=True, with_usage=False)
        state_path = codex / installer.INSTALL_STATE_NAME
        state = json.loads(state_path.read_text())
        state["kit_version"] = "0.5.0"
        state_path.write_text(json.dumps(state))
        (codex / "agents" / "luna_scout_fast.toml").write_text("managed runtime drift\n")
        stale_and_drifted, _ = self._json(base, receipts, sessions)
        self.assertEqual(stale_and_drifted["lifecycle"]["state"], "needs-attention")
        self.assertEqual(stale_and_drifted["lifecycle"]["next_action"], "review-drift")

        invalid = self._run(base, receipts, sessions, "--budget", "0", "--format", "json")
        self.assertEqual(invalid.returncode, 2)
        self.assertNotIn("Traceback", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
