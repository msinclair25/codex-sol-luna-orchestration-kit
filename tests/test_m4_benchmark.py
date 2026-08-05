import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

if os.name == "nt":
    raise unittest.SkipTest("retired M4 benchmark runner requires POSIX process and resource controls")

from benchmark.m4_single_pair import oracle
from scripts import run_m4_benchmark
from scripts import pilot_tool


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "m4-benchmark.v1.json"


REFERENCE_SOLUTION = r'''"""Reference candidate used only to validate the held-out oracle."""
from __future__ import annotations
import json
import re
import sys
from collections.abc import Mapping, Sequence

MAX_NAME_LENGTH = 64
MAX_ABS_DELTA = 1_000_000_000
NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")

class InventoryError(ValueError):
    pass

def _name(value):
    return isinstance(value, str) and NAME.fullmatch(value) is not None

def apply_operations(initial, operations):
    if not isinstance(initial, Mapping):
        raise InventoryError("initial")
    if not isinstance(operations, Sequence) or isinstance(operations, (str, bytes, bytearray)):
        raise InventoryError("operations")
    for sku, quantity in initial.items():
        if not _name(sku) or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise InventoryError("initial")
    validated = []
    seen = {}
    for operation in operations:
        if not isinstance(operation, Mapping) or set(operation) != {"id", "sku", "delta"}:
            raise InventoryError("operation")
        op_id, sku, delta = operation["id"], operation["sku"], operation["delta"]
        if not _name(op_id) or not _name(sku):
            raise InventoryError("name")
        if isinstance(delta, bool) or not isinstance(delta, int) or delta == 0 or abs(delta) > MAX_ABS_DELTA:
            raise InventoryError("delta")
        payload = (op_id, sku, delta)
        if op_id in seen:
            if seen[op_id] != payload:
                raise InventoryError("duplicate")
            continue
        seen[op_id] = payload
        validated.append(payload)
    result = dict(initial)
    for _, sku, delta in validated:
        quantity = result.get(sku, 0) + delta
        if quantity < 0:
            raise InventoryError("overdraw")
        result[sku] = quantity
    return dict(sorted(result.items()))

def main(argv=None):
    del argv
    request = json.load(sys.stdin)
    if not isinstance(request, dict) or set(request) != {"initial", "operations"}:
        raise InventoryError("request")
    result = apply_operations(request["initial"], request["operations"])
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"inventory error: {exc}", file=sys.stderr)
        raise SystemExit(1)
'''


def _arm(disposition="accepted", duration=1000, coverage="complete-full-workflow", weighted=100.0):
    return {
        "disposition": disposition,
        "duration_ms": duration,
        "usage": {"coverage": coverage, "weighted_usage": weighted},
    }


def _write_runtime(home: Path, *, control: bool = False) -> None:
    (home / "AGENTS.md").write_text("frozen instructions")
    (home / "agents").mkdir()
    reasoning = {
        "luna_scout_fast": "medium",
        "luna_worker_fast": "high",
        "luna_tester_fast": "medium",
    }
    sandboxes = {
        "luna_scout_fast": "read-only",
        "luna_worker_fast": "workspace-write",
        "luna_tester_fast": "workspace-write",
    }
    for role in run_m4_benchmark.REQUIRED_ROLES:
        effort = "max" if control else reasoning[role]
        (home / "agents" / f"{role}.toml").write_text(
            f'name = "{role}"\n'
            f'description = "role"\n'
            'model = "gpt-5.6-luna"\n'
            f'model_reasoning_effort = "{effort}"\n'
            'service_tier = "fast"\n'
            f'sandbox_mode = "{sandboxes[role]}"\n'
            'developer_instructions = "bounded"\n'
        )


def _future_report(pilot_home: Path, benchmark_id: str = "m4-future-test") -> dict:
    verified = run_m4_benchmark.verify_benchmark(ROOT, CONFIG)
    return {
        "benchmark_id": benchmark_id,
        "config": {**verified["config"], "benchmark_id": benchmark_id},
        "pilot_home": pilot_home,
        "benchmark_config_sha256": verified["benchmark_config_sha256"],
        "fixture_manifest_sha256": verified["fixture_manifest_sha256"],
        "prompt_sha256": verified["prompt_sha256"],
        "oracle_sha256": verified["oracle_sha256"],
        "pilot_plan_sha256": verified["pilot_plan_sha256"],
        "repository": {"commit": "f" * 40, "branch": "test"},
        "codex": {"version": "codex-cli test"},
        "environment_matches": {"all-max-control": 8, "dynamic-v0.2.1": 8},
        "benchmark_config_path": CONFIG,
    }


class M4BenchmarkTests(unittest.TestCase):
    def test_retired_preflight_blocks_without_model_call(self):
        with mock.patch.object(run_m4_benchmark, "_codex_facts") as facts:
            result = run_m4_benchmark.preflight(ROOT, CONFIG, tempfile.mkdtemp(), codex_binary="codex")
        self.assertEqual(result["status"], "retired-non-retryable")
        self.assertEqual(result["model_calls_started"], 0)
        facts.assert_not_called()

    def test_command_uses_immutable_cli_transport_without_public_path_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            _write_runtime(home)
            command = run_m4_benchmark._codex_command("codex", home, Path("/private/ws"), Path("/private/capture/last"), "prompt", {"model": "gpt-5.6-sol", "model_reasoning_effort": "xhigh"})
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--strict-config", command)
        self.assertIn("features.fast_mode=true", command)
        self.assertTrue(any("trust_level=\"trusted\"" in item for item in command))
        self.assertTrue(any("model_reasoning_effort" in item for item in command))
        self.assertTrue(any("config_file" in item for item in command))

    def test_capability_contract_rejects_missing_flag(self):
        class Result:
            returncode = 0
            stdout = "codex exec sandbox login --json"
            stderr = ""
        with mock.patch.object(run_m4_benchmark.subprocess, "run", return_value=Result()):
            with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "codex_capability_missing"):
                run_m4_benchmark._codex_capabilities("codex", Path("/private/pilot"))

    def test_policy_files_fail_closed_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "runtime_agents_unreadable"):
                run_m4_benchmark._codex_command("codex", Path(directory), Path("/private/ws"), Path("/private/last"), "p", {"model": "gpt-5.6-sol", "model_reasoning_effort": "xhigh"})

    def test_prior_attempt_guard_reads_write_ahead_benchmark_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "br1-test"
            run.mkdir()
            (run / "run-state.jsonl").write_text('{"event":"run_created","benchmark_id":"m4-future"}\n')
            self.assertTrue(run_m4_benchmark._prior_attempt_exists(root, "m4-future"))
            self.assertFalse(run_m4_benchmark._prior_attempt_exists(root, "other"))

    def test_prior_attempt_guard_rejects_symlinked_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "br1-test"
            run.mkdir()
            target = root / "unrelated.json"
            target.write_text('{"benchmark_id":"other"}\n')
            (run / "run-state.jsonl").symlink_to(target)
            self.assertTrue(run_m4_benchmark._prior_attempt_exists(root, "m4-future"))

    def test_retirement_evidence_requires_incident_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "retired.json"
            evidence.write_text('{"benchmark_id":"m4-v0.2.1-single-pair-01","status":"retired-non-retryable","retry_allowed":false}')
            with mock.patch.object(run_m4_benchmark, "RETIREMENT_EVIDENCE", evidence):
                with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "retirement_evidence_drift"):
                    run_m4_benchmark.preflight(ROOT, CONFIG, Path(directory) / "missing", codex_binary="never")

    def test_runtime_role_contract_rejects_semantic_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            _write_runtime(home)
            role = home / "agents" / "luna_worker_fast.toml"
            role.write_text(role.read_text().replace('model = "gpt-5.6-luna"', 'model = "other"'))
            with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "runtime_role_unreadable"):
                run_m4_benchmark._codex_command(
                    "codex", home, Path("/private/ws"), Path("/private/last"),
                    "prompt", {"model": "gpt-5.6-sol", "model_reasoning_effort": "xhigh"},
                )

    def test_duplicate_json_keys_fail_closed_for_events_and_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            events = base / "events.jsonl"
            events.write_text('{"type":"thread.started","type":"turn.completed","thread_id":"root"}\n')
            with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "duplicate_json_key"):
                run_m4_benchmark._event_summary(events)
            session = base / "session.jsonl"
            session.write_text('{"type":"session_meta","payload":{"id":"a","id":"b"}}\n')
            with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "duplicate_json_key"):
                run_m4_benchmark._session_meta(session)

    def test_atomic_claim_is_private_and_nonretryable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claim = run_m4_benchmark._claim_benchmark(root, "m4-future")
            self.assertEqual(stat.S_IMODE(claim.stat().st_mode), 0o600)
            with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "prior_benchmark_attempt"):
                run_m4_benchmark._claim_benchmark(root, "m4-future")

    def test_journal_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("unchanged")
            journal = root / "journal"
            journal.symlink_to(target)
            with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "journal_unsafe"):
                run_m4_benchmark._journal_append(journal, {"event": "unsafe"})
            self.assertEqual(target.read_text(), "unchanged")

    def test_progress_rejects_path_like_or_unknown_messages(self):
        output = io.StringIO()
        with redirect_stderr(output):
            run_m4_benchmark._sanitized_progress("run /Users/private created")
            run_m4_benchmark._sanitized_progress("arm heartbeat all-max-control elapsed_seconds=30")
        self.assertEqual(output.getvalue(), "arm heartbeat all-max-control elapsed_seconds=30\n")

    def test_prompt_failure_after_run_creation_writes_terminal_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            pilot_home = Path(directory) / "pilot"
            pilot_home.mkdir(mode=0o700)
            report = _future_report(pilot_home, "m4-prompt-failure")
            with mock.patch.object(run_m4_benchmark, "_safe_file", side_effect=run_m4_benchmark.BenchmarkError("prompt_unreadable")):
                with self.assertRaises(run_m4_benchmark.BenchmarkError) as caught:
                    run_m4_benchmark.execute(report, ROOT, codex_binary="never")
            locator = caught.exception.locator
            self.assertEqual(set(locator), {"run_id", "terminal_receipt"})
            terminal = json.loads((pilot_home / "benchmark-runs" / locator["run_id"] / locator["terminal_receipt"]).read_text())
            self.assertEqual(terminal["failure_code"], "prompt_unreadable")
            self.assertEqual(terminal["model_calls_started"], 0)
            self.assertFalse(terminal["retry_allowed"])
            self.assertTrue(run_m4_benchmark._validate_terminal_receipt(terminal))

    def test_terminal_write_failure_never_masks_original_error(self):
        with tempfile.TemporaryDirectory() as directory:
            pilot_home = Path(directory) / "pilot"
            pilot_home.mkdir(mode=0o700)
            report = _future_report(pilot_home, "m4-terminal-write-failure")
            original = run_m4_benchmark.BenchmarkError("prompt_unreadable")
            with mock.patch.object(run_m4_benchmark, "_safe_file", side_effect=original), mock.patch.object(run_m4_benchmark, "_private_write", side_effect=OSError("disk")):
                with self.assertRaises(run_m4_benchmark.BenchmarkError) as caught:
                    run_m4_benchmark.execute(report, ROOT, codex_binary="never")
            self.assertIs(caught.exception, original)
            self.assertEqual(set(caught.exception.locator), {"run_id"})

    def test_public_preflight_filters_internal_and_path_like_runtime_fields(self):
        report = {
            "ok": True,
            "codex": {
                "version": "/private/secret/codex",
                "_executable_path": "/private/secret/codex",
                "executable_sha256": "a" * 64,
                "logins": {"control": True, "dynamic": True},
                "sandbox_smoke": True,
                "capabilities": {"fingerprint": "b" * 16, "required": {"secret": "/private/path"}},
            },
        }
        public = run_m4_benchmark._public_preflight(report)
        rendered = json.dumps(public)
        self.assertNotIn("/private", rendered)
        self.assertNotIn("_executable_path", rendered)
        self.assertEqual(public["codex"]["version"], "unavailable")

    def test_timeout_is_write_ahead_terminal_and_does_not_start_arm_two(self):
        with tempfile.TemporaryDirectory() as directory:
            pilot_home = Path(directory) / "pilot"
            pilot_home.mkdir(mode=0o700)
            report = _future_report(pilot_home, "m4-timeout")

            def timed_out(*args, **kwargs):
                del args, kwargs
                journals = list((pilot_home / "benchmark-runs").glob("br1-*/run-state.jsonl"))
                records = [json.loads(line) for line in journals[0].read_text().splitlines()]
                self.assertEqual(records[-1]["event"], "arm_launching")
                self.assertEqual(records[-1]["model_calls_started"], 1)
                return {"arm": "all-max-control", "disposition": "abandoned", "timed_out": True}

            with mock.patch.object(run_m4_benchmark, "_arm_result", side_effect=timed_out) as arm_result:
                with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "arm_timeout") as caught:
                    run_m4_benchmark.execute(report, ROOT, codex_binary="never")
            self.assertEqual(arm_result.call_count, 1)
            locator = caught.exception.locator
            terminal = json.loads((pilot_home / "benchmark-runs" / locator["run_id"] / locator["terminal_receipt"]).read_text())
            self.assertEqual(terminal["status"], "timed-out")
            self.assertEqual(terminal["active_arm"], "all-max-control")
            self.assertEqual(terminal["completed_arms"], [])
            self.assertEqual(terminal["model_calls_started"], 1)

    def test_mid_pair_runtime_identity_change_stops_before_model_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            pilot_home = Path(directory) / "pilot"
            pilot_home.mkdir(mode=0o700)
            report = _future_report(pilot_home, "m4-identity-drift")
            report["codex"] = {
                "version": "codex-cli before",
                "executable_sha256": "a" * 64,
                "capabilities": {"fingerprint": "b" * 16},
            }
            version = mock.Mock(returncode=0, stdout="codex-cli after\n")
            with mock.patch.object(run_m4_benchmark.subprocess, "run", return_value=version), mock.patch.object(run_m4_benchmark, "_codex_executable_sha256", return_value="a" * 64), mock.patch.object(run_m4_benchmark, "_arm_result") as arm_result:
                with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "codex_identity_drift") as caught:
                    run_m4_benchmark.execute(report, ROOT, codex_binary="codex")
            arm_result.assert_not_called()
            locator = caught.exception.locator
            terminal = json.loads((pilot_home / "benchmark-runs" / locator["run_id"] / locator["terminal_receipt"]).read_text())
            self.assertEqual(terminal["model_calls_started"], 0)
            self.assertEqual(terminal["failure_code"], "codex_identity_drift")

    def test_main_error_never_reuses_a_stale_locator(self):
        output = io.StringIO()
        with mock.patch.object(run_m4_benchmark, "preflight", side_effect=run_m4_benchmark.BenchmarkError("preflight_failed")), redirect_stdout(output):
            code = run_m4_benchmark.main(["--pilot-home", "/private/tmp/missing"])
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertNotIn("run_id", result)
        self.assertNotIn("terminal_receipt", result)

    def test_frozen_config_fixture_and_baselines_verify(self):
        result = run_m4_benchmark.verify_benchmark(ROOT, CONFIG)
        self.assertTrue(result["ok"])
        self.assertEqual(result["arm_timeout_seconds"], 900)
        self.assertEqual(result["total_model_timeout_seconds"], 1800)
        self.assertEqual(result["pilot_plan_sha256"], "bd053dab372dd576e94252be6c2cec0c77d5083198d34b62630b3db4e28b060e")
        self.assertFalse(result["automatic_promotion"])
        self.assertTrue(result["directional_only"])

    def test_benchmark_config_is_pinned_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "m4-benchmark.v1.json"
            value = json.loads(CONFIG.read_text())
            value["weighted_usage_reduction_target"] = 0
            changed.write_text(json.dumps(value))
            with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "benchmark_config_drift"):
                run_m4_benchmark.verify_benchmark(ROOT, changed)

    def test_seed_fails_and_reference_solution_passes_oracle(self):
        seed = oracle.evaluate(ROOT / "benchmark" / "m4_single_pair" / "fixture")
        self.assertFalse(seed["ok"])
        self.assertEqual(seed["checks"], 14)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "inventory.py").write_text(REFERENCE_SOLUTION)
            result = oracle.evaluate(workspace)
        self.assertEqual(result, {"ok": True, "checks": 14, "passed": 14, "failed": 0})

    def test_workspace_copy_is_identical_and_scope_is_inventory_only(self):
        verified = run_m4_benchmark.verify_benchmark(ROOT, CONFIG)
        config = verified["config"]
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            run_m4_benchmark._copy_fixture(ROOT, config, workspace)
            before = run_m4_benchmark._workspace_state(workspace)
            self.assertFalse(run_m4_benchmark._scope_ok(before, dict(before), ["inventory.py"]))
            (workspace / "inventory.py").write_text(REFERENCE_SOLUTION)
            after = run_m4_benchmark._workspace_state(workspace)
            self.assertTrue(run_m4_benchmark._scope_ok(before, after, ["inventory.py"]))
            (workspace / "extra.txt").write_text("not allowed")
            self.assertFalse(run_m4_benchmark._scope_ok(before, run_m4_benchmark._workspace_state(workspace), ["inventory.py"]))

    def test_event_summary_is_structural_and_redacts_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(
                json.dumps({"type": "thread.started", "thread_id": "secret-thread"}) + "\n"
                + json.dumps({"type": "item.completed", "item": {"text": "secret prompt"}}) + "\n"
                + json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1}}) + "\n"
            )
            summary = run_m4_benchmark._event_summary(path)
        rendered = json.dumps(summary)
        self.assertTrue(summary["ok"])
        self.assertNotIn("secret prompt", rendered)
        self.assertEqual(summary["root_thread_id"], "secret-thread")
        self.assertEqual(summary["types"]["turn.completed"], 1)

    def test_event_summary_requires_single_started_and_completed_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(json.dumps({"type": "turn.completed"}) + "\n")
            self.assertFalse(run_m4_benchmark._event_summary(path)["ok"])
            path.write_text(
                json.dumps({"type": "thread.started", "thread_id": "root"}) + "\n"
                + json.dumps({"type": "thread.started", "thread_id": "root"}) + "\n"
                + json.dumps({"type": "turn.completed"}) + "\n"
            )
            self.assertFalse(run_m4_benchmark._event_summary(path)["ok"])

    def test_session_attribution_requires_exact_root_and_three_children(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)

            def session(name, payload):
                path = base / f"{name}.jsonl"
                path.write_text(json.dumps({"type": "session_meta", "payload": payload}) + "\n")
                return path

            paths = [session("root", {"id": "root"})]
            paths.extend(
                session(role, {"id": role, "parent_thread_id": "root", "agent_role": role})
                for role in run_m4_benchmark.REQUIRED_ROLES
            )
            correlated, ok = run_m4_benchmark._correlated_sessions(paths, "root", False)
            self.assertTrue(ok)
            self.assertEqual(correlated, paths)
            extra = session("extra", {"id": "extra"})
            self.assertFalse(run_m4_benchmark._correlated_sessions(paths + [extra], "root", False)[1])
            self.assertFalse(run_m4_benchmark._correlated_sessions(paths, "root", True)[1])
            with paths[0].open("a") as handle:
                handle.write(json.dumps({"type": "session_meta", "payload": {"id": "root"}}) + "\n")
            self.assertFalse(run_m4_benchmark._correlated_sessions(paths, "root", False)[1])

    def test_workspace_state_fails_closed_on_large_output(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "inventory.py").write_bytes(
                b"x" * (run_m4_benchmark.MAX_WORKSPACE_FILE_BYTES + 1)
            )
            self.assertIn("__unsafe__", run_m4_benchmark._workspace_state(workspace))

    def test_weighted_usage_requires_every_expected_run(self):
        expected = {
            "root": {"model": "gpt-5.6-sol", "reasoning_effort": "xhigh", "service_tier": "default"},
            "luna_scout_fast": {"model": "gpt-5.6-luna", "reasoning_effort": "medium", "service_tier": "fast"},
            "luna_worker_fast": {"model": "gpt-5.6-luna", "reasoning_effort": "high", "service_tier": "fast"},
            "luna_tester_fast": {"model": "gpt-5.6-luna", "reasoning_effort": "medium", "service_tier": "fast"},
        }
        groups = []
        for role, runtime in expected.items():
            groups.append({
                "role": role, "model": runtime["model"],
                "reasoning_effort": runtime["reasoning_effort"],
                "service_tier": "unknown" if role != "root" else "default",
                "runs": 1, "completed": 1, "token_usage_runs": 1,
                "tokens": {"total": 100},
            })
        report = {"groups": groups, "runs": 4, "completed": 4, "token_usage_runs": 4}
        rate_card = json.loads((ROOT / "config" / "rate-card.v1.json").read_text())
        result = run_m4_benchmark._weighted_usage(report, expected, rate_card)
        self.assertEqual(result["coverage"], "complete-full-workflow")
        self.assertEqual(result["total_tokens"], 400)
        self.assertEqual(result["weighted_usage"], 850.0)
        report["token_usage_runs"] = 3
        result = run_m4_benchmark._weighted_usage(report, expected, rate_card)
        self.assertEqual(result["coverage"], "unknown")
        self.assertIsNone(result["weighted_usage"])

    def test_comparison_is_directional_and_never_promotes(self):
        config = run_m4_benchmark.verify_benchmark(ROOT, CONFIG)["config"]
        promising = run_m4_benchmark._comparison(config, {
            "all-max-control": _arm(duration=1000, weighted=100),
            "dynamic-v0.2.1": _arm(duration=1100, weighted=70),
        })
        self.assertEqual(promising["status"], "dynamic-promising-human-review")
        self.assertFalse(promising["automatic_promotion"])
        retained = run_m4_benchmark._comparison(config, {
            "all-max-control": _arm(duration=1000, weighted=100),
            "dynamic-v0.2.1": _arm(duration=1300, weighted=95),
        })
        self.assertEqual(retained["status"], "keep-all-max")
        unknown = run_m4_benchmark._comparison(config, {
            "all-max-control": _arm(),
            "dynamic-v0.2.1": _arm(coverage="unknown", weighted=None),
        })
        self.assertEqual(unknown["status"], "inconclusive")

    def test_codex_timeout_terminates_process_and_captures_privately(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            fake = base / "fake-codex"
            fake.write_text("#!/bin/sh\nsleep 30\n")
            fake.chmod(0o700)
            codex_home = base / "codex-home"
            workspace = base / "workspace"
            capture = base / "capture"
            for path in (codex_home, workspace, capture):
                path.mkdir(mode=0o700)
            result = run_m4_benchmark._run_codex(str(fake), codex_home, workspace, "prompt", capture, 1)
            self.assertTrue(result["timed_out"])
            for name in ("events.jsonl", "stderr.log", "last-message.txt"):
                self.assertEqual(stat.S_IMODE((capture / name).stat().st_mode), 0o600)

    def test_noninteractive_command_requires_explicit_model_approval(self):
        report = {
            "ok": True,
            "benchmark_id": "m4-v0.2.1-single-pair-01",
            "benchmark_config_sha256": "a" * 64,
            "fixture_manifest_sha256": "b" * 64,
            "prompt_sha256": "c" * 64,
            "oracle_sha256": "d" * 64,
            "pilot_plan_id": "m4-v0.2.1-window-02",
            "pilot_plan_sha256": "e" * 64,
            "repository": {"commit": "f" * 40, "branch": "test", "dirty": False, "origin_match": True},
            "codex": {"version": "codex-cli test", "logins": {"control": True, "dynamic": True}},
            "environment_matches": {"all-max-control": 8, "dynamic-v0.2.1": 8},
            "registered_count": 0,
            "terminal_count": 0,
            "model_calls_started": 0,
            "arm_timeout_seconds": 900,
            "total_model_timeout_seconds": 1800,
            "automatic_promotion": False,
            "directional_only": True,
            "benchmark_config_path": CONFIG,
            "config": {},
            "pilot_home": Path("/private/tmp/pilot"),
        }
        output = io.StringIO()
        with mock.patch.object(run_m4_benchmark, "preflight", return_value=report), mock.patch.object(run_m4_benchmark, "execute") as execute, redirect_stdout(output):
            code = run_m4_benchmark.main(["--pilot-home", "/private/tmp/pilot"])
        self.assertEqual(code, 4)
        execute.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "approval-required")

    def test_codex_preflight_requires_real_network_disabled_sandbox_smoke(self):
        completed = [
            mock.Mock(returncode=0, stdout="codex-cli test\n"),
            mock.Mock(returncode=0, stdout="sandbox help\n"),
            mock.Mock(returncode=0, stdout=""),
            mock.Mock(returncode=0, stdout="logged in\n"),
            mock.Mock(returncode=0, stdout="logged in\n"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            fake_codex = Path(directory) / "codex"
            fake_codex.write_text("#!/bin/sh\nexit 0\n")
            fake_codex.chmod(0o700)
            with mock.patch.object(run_m4_benchmark.subprocess, "run", side_effect=completed) as run:
                result = run_m4_benchmark._codex_facts(str(fake_codex), Path("/private/tmp/pilot"))
        self.assertTrue(result["sandbox_smoke"])
        smoke_command = run.call_args_list[2].args[0]
        self.assertEqual(smoke_command[0], str(fake_codex.resolve()))
        self.assertIn(":workspace", smoke_command)
        self.assertIn("--sandbox-state-disable-network", smoke_command)
        self.assertEqual(smoke_command[-1], "/usr/bin/true")

    def test_offline_two_arm_execution_writes_one_private_directional_receipt(self):
        fake_source = f'''#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if args and args[0] == "sandbox":
    separator = args.index("--")
    command = args[separator + 1:]
    os.execv(command[0], command)

solution = {REFERENCE_SOLUTION!r}
Path("inventory.py").write_text(solution)
last = Path(args[args.index("--output-last-message") + 1])
last.write_text("completed")
home = Path(os.environ["CODEX_HOME"])
control = "control" in home.parts
if control:
    # Keep the directional latency assertion deterministic on busy CI hosts.
    time.sleep(0.05)
sessions = home / "sessions" / "2026" / "08" / "03"
sessions.mkdir(parents=True, exist_ok=True)

def write(name, records):
    (sessions / (name + ".jsonl")).write_text("".join(json.dumps(row) + "\\n" for row in records))

write("root", [
    {{"timestamp":"2026-08-03T00:00:00Z","type":"session_meta","payload":{{"id":"root","timestamp":"2026-08-03T00:00:00Z"}}}},
    {{"type":"event_msg","payload":{{"type":"thread_settings_applied","thread_settings":{{"model":"gpt-5.6-sol","reasoning_effort":"xhigh","service_tier":"default"}}}}}},
    {{"type":"event_msg","payload":{{"type":"task_started","turn_id":"root-turn","started_at":1000}}}},
    {{"type":"event_msg","payload":{{"type":"token_count","info":{{"total_token_usage":{{"total_tokens":100}}}}}}}},
    {{"type":"event_msg","payload":{{"type":"task_complete","turn_id":"root-turn","started_at":1000,"completed_at":1001,"duration_ms":1000}}}},
])
reasoning = {{"luna_scout_fast":"medium","luna_worker_fast":"high","luna_tester_fast":"medium"}}
for index, role in enumerate(("luna_scout_fast","luna_worker_fast","luna_tester_fast"), 1):
    effort = "max" if control else reasoning[role]
    final = 110 if control else 60
    write(role, [
        {{"timestamp":"2026-08-03T00:00:00Z","type":"session_meta","payload":{{"id":role,"parent_thread_id":"root","agent_role":role,"timestamp":"2026-08-03T00:00:00Z"}}}},
        {{"type":"event_msg","payload":{{"type":"token_count","info":{{"total_token_usage":{{"total_tokens":10}}}}}}}},
        {{"type":"event_msg","payload":{{"type":"thread_settings_applied","thread_settings":{{"model":"gpt-5.6-luna","reasoning_effort":effort,"service_tier":"priority"}}}}}},
        {{"type":"event_msg","payload":{{"type":"task_started","turn_id":role,"started_at":1000 + index}}}},
        {{"type":"event_msg","payload":{{"type":"token_count","info":{{"total_token_usage":{{"total_tokens":final}}}}}}}},
        {{"type":"event_msg","payload":{{"type":"task_complete","turn_id":role,"started_at":1000 + index,"completed_at":1001 + index,"duration_ms":1000}}}},
    ])
print(json.dumps({{"type":"thread.started","thread_id":"root"}}))
print(json.dumps({{"type":"turn.completed","usage":{{"input_tokens":1}}}}))
'''
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            pilot_home = base / "pilot"
            pilot_tool.setup_environments(
                ROOT / "config" / "m4-pilot.v1.json", ROOT, pilot_home, apply=True,
            )
            fake = base / "fake-codex"
            fake.write_text(fake_source)
            fake.chmod(0o700)
            verified = run_m4_benchmark.verify_benchmark(ROOT, CONFIG)
            verified_config = {**verified["config"], "benchmark_id": "m4-future-test"}
            preflight = {
                "config": verified_config,
                "pilot_home": pilot_home,
                "benchmark_config_sha256": verified["benchmark_config_sha256"],
                "fixture_manifest_sha256": verified["fixture_manifest_sha256"],
                "prompt_sha256": verified["prompt_sha256"],
                "oracle_sha256": verified["oracle_sha256"],
                "pilot_plan_sha256": verified["pilot_plan_sha256"],
                "repository": {"commit": "f" * 40, "branch": "test"},
                "codex": {"version": "codex-cli test"},
                "environment_matches": {"all-max-control": 8, "dynamic-v0.2.1": 8},
                "benchmark_config_path": CONFIG,
            }
            starts_before = (ROOT / ".sol-luna" / "starts").exists()
            receipt, receipt_path = run_m4_benchmark.execute(preflight, ROOT, codex_binary=str(fake))
            self.assertEqual(receipt["comparison"]["status"], "dynamic-promising-human-review")
            self.assertEqual(
                {arm: row["disposition"] for arm, row in receipt["arms"].items()},
                {"all-max-control": "accepted", "dynamic-v0.2.1": "accepted"},
            )
            self.assertTrue(run_m4_benchmark.validate_receipt(receipt))
            self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)
            self.assertEqual((ROOT / ".sol-luna" / "starts").exists(), starts_before)
            self.assertFalse(receipt["comparison"]["automatic_promotion"])

    def test_execute_rejects_existing_output_root_outside_pilot_home(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            pilot_home = base / "pilot"
            outside = base / "outside"
            pilot_home.mkdir(mode=0o700)
            outside.mkdir(mode=0o700)
            report = {
                "config": {**run_m4_benchmark.verify_benchmark(ROOT, CONFIG)["config"], "benchmark_id": "m4-future-test"},
                "pilot_home": pilot_home,
                "benchmark_config_path": CONFIG,
            }
            with self.assertRaisesRegex(run_m4_benchmark.BenchmarkError, "output_root_unsafe"):
                run_m4_benchmark.execute(report, ROOT, output_root=outside)

    def test_receipt_validation_rejects_paths_and_promotion(self):
        arms = {
            arm: {"arm": arm, "disposition": "accepted", "duration_ms": 1, "acceptance": {}, "usage": {}}
            for arm in run_m4_benchmark.ARMS
        }
        receipt = {
            "schema_version": 1,
            "benchmark_id": "m4-v0.2.1-single-pair-01",
            "run_id": "br1-0123456789abcdef",
            "origin": "unsigned-local-audit",
            "started_at": "2026-08-02T00:00:00Z",
            "closed_at": "2026-08-02T00:01:00Z",
            "toolkit": {},
            "integrity": {},
            "limits": {},
            "arms": arms,
            "comparison": {"status": "keep-all-max", "directional_only": True, "automatic_promotion": False, "human_review_required": True},
            "artifacts_retained_private": True,
        }
        self.assertTrue(run_m4_benchmark.validate_receipt(receipt))
        receipt["comparison"]["automatic_promotion"] = True
        self.assertFalse(run_m4_benchmark.validate_receipt(receipt))
        receipt["comparison"]["automatic_promotion"] = False
        receipt["toolkit"]["path"] = str(Path.home() / "secret")
        self.assertFalse(run_m4_benchmark.validate_receipt(receipt))


if __name__ == "__main__":
    unittest.main()
