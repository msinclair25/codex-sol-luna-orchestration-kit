import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.routing_policy import (
    DEFAULT_ROOT,
    LUNA_TRANSPORT,
    MAX_UPGRADE_REASON_CODES,
    POLICY_AGENTS_RELATIVE,
    POLICY_RELATIVE,
    ROLE_DEFINITIONS,
    STANDARD_ROLE_DEFINITIONS,
    detect_ownership_conflicts,
    evaluate,
    validate_evidence,
    verify_active_root,
    verify_contract,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "routing_cases.json"


class RoutingPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(FIXTURES.read_text())

    def test_contract_matches_dynamic_runtime(self):
        report = verify_contract(ROOT)
        self.assertTrue(report["ok"])
        self.assertTrue(report["runtime_root_match"])
        self.assertTrue(report["runtime_agents_match"])
        self.assertTrue(report["runtime_config_match"])
        self.assertEqual(report["role_matches"], 5)

        standard = verify_contract(ROOT, "standard")
        self.assertTrue(standard["ok"], standard)
        self.assertEqual(standard["profile"], "standard")
        self.assertEqual(standard["role_matches"], 5)

    def test_role_reasoning_and_tier_table_is_dynamic(self):
        expected = {
            "luna_scout_fast": ("medium", "fast", "read-only"),
            "luna_worker_fast": ("high", "fast", "workspace-write"),
            "luna_critic_fast": ("high", "fast", "read-only"),
            "luna_tester_fast": ("medium", "fast", "workspace-write"),
            "luna_max_fast": ("max", "fast", "read-only"),
        }
        for definition in ROLE_DEFINITIONS.values():
            self.assertEqual(
                (definition["reasoning"], definition["service_tier"], definition["sandbox_mode"]),
                expected[definition["role"]],
            )
        self.assertTrue(all(role["service_tier"] == "standard" for role in STANDARD_ROLE_DEFINITIONS.values()))
        self.assertTrue(all(role["service_tier_configured"] is False for role in STANDARD_ROLE_DEFINITIONS.values()))

    def test_valid_delegation_routes_to_routine_role(self):
        result = evaluate(self.cases["valid_delegation"], ROOT)
        self.assertTrue(result["ok"])
        self.assertEqual(result["decision"], "delegate")
        self.assertEqual(result["route"], "luna_scout_fast")
        self.assertEqual(result["reasoning"], "medium")
        self.assertFalse(result["fallback"])
        self.assertEqual(result["transport"], LUNA_TRANSPORT)

        request = dict(self.cases["valid_delegation"])
        request["profile"] = "standard"
        standard = evaluate(request, ROOT)
        self.assertTrue(standard["ok"], standard)
        self.assertEqual(standard["route"], "luna_scout_standard")
        self.assertEqual(standard["service_tier"], "standard")
        self.assertEqual(standard["profile"], "standard")

        unsupported = dict(request)
        unsupported["profile"] = "priority-plus"
        denied = evaluate(unsupported, ROOT)
        self.assertFalse(denied["ok"])
        self.assertIn("unsupported_profile", denied["reason_codes"])

    def test_context_free_transport_is_explicit_and_history_forks_fail_closed(self):
        allowed = dict(self.cases["valid_delegation"])
        result = evaluate(allowed, ROOT)
        self.assertTrue(result["ok"])
        self.assertEqual(result["transport"], {
            "fork_turns": "none",
            "history_inherited": False,
            "assignment": "self-contained",
            "nested_delegation": False,
            "on_spawn_error": "sol",
            "retry_spawn": False,
        })

        omitted = dict(allowed)
        del omitted["fork_turns"]
        result = evaluate(omitted, ROOT)
        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "sol")
        self.assertIn("fork_turns_required", result["reason_codes"])

        for history_fork in ("all", "1", 1, None):
            rejected = dict(allowed)
            rejected["fork_turns"] = history_fork
            result = evaluate(rejected, ROOT)
            self.assertFalse(result["ok"], history_fork)
            self.assertEqual(result["route"], "sol")
            self.assertIn("split_tier_appropriate", result["reason_codes"])

    def test_failed_gate_routes_directly_to_sol(self):
        for case_name in ("direct_work", "rejected_gate"):
            result = evaluate(self.cases[case_name], ROOT)
            self.assertFalse(result["ok"])
            self.assertEqual(result["route"], "sol")
            self.assertTrue(result["fallback"])
            self.assertTrue(any(code.startswith("split_") for code in result["reason_codes"]))

    def test_max_upgrade_requires_enumerated_reason_and_uses_max(self):
        result = evaluate(self.cases["reasoning_upgrade"], ROOT)
        self.assertTrue(result["ok"])
        self.assertEqual(result["route"], "luna_max_fast")
        self.assertEqual(result["reasoning"], "max")
        self.assertIn(result["max_upgrade_reason"], MAX_UPGRADE_REASON_CODES)

        rejected = dict(self.cases["reasoning_upgrade"])
        rejected["max_upgrade_reason"] = "made_up_reason"
        result = evaluate(rejected, ROOT)
        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "sol")
        self.assertIn("unsupported_max_upgrade_reason", result["reason_codes"])

        analysis = dict(self.cases["valid_delegation"])
        analysis["kind"] = "analysis"
        result = evaluate(analysis, ROOT)
        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "sol")
        self.assertIn("max_upgrade_reason_required", result["reason_codes"])

        analysis["max_upgrade_reason"] = "cross_cutting_risk"
        result = evaluate(analysis, ROOT)
        self.assertTrue(result["ok"])
        self.assertEqual(result["route"], "luna_max_fast")

    def test_only_simultaneously_active_lanes_are_capped(self):
        result = evaluate(self.cases["multiple_waves"], ROOT)
        self.assertTrue(result["ok"])
        self.assertEqual(result["lane_count"], 2)
        self.assertEqual(result["wave_count"], 12)
        self.assertEqual(result["max_concurrent_delegated_lanes"], 3)
        self.assertEqual(result["processing"], "waves")
        self.assertEqual(result["dependent_work"], "serialized")

        too_many = dict(self.cases["multiple_waves"])
        too_many["lane_count"] = 4
        result = evaluate(too_many, ROOT)
        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "sol")
        self.assertIn("unsupported_concurrency", result["reason_codes"])

    def test_evidence_packet_contract_is_exact_and_bounded(self):
        evidence = {
            "scope": "routing policy review",
            "files_or_surfaces": ["scripts/routing_policy.py"],
            "commands_or_checks": ["python3 -m unittest discover"],
            "assumptions": ["runtime hashes are current"],
            "failures": [],
            "risks": ["Codex availability varies by account"],
            "confidence": "high",
            "recommendation": "run the static verifier",
        }
        self.assertTrue(validate_evidence(evidence))
        missing = dict(evidence)
        del missing["failures"]
        self.assertFalse(validate_evidence(missing))
        extra = dict(evidence)
        extra["next_action"] = "not part of v1"
        self.assertFalse(validate_evidence(extra))

    def test_exact_and_prefix_ownership_conflicts_are_rejected(self):
        exact = detect_ownership_conflicts({"a": ["src/app.py"], "b": ["src/app.py"]})
        prefix = detect_ownership_conflicts({"a": ["src"], "b": ["src/app.py"]})
        self.assertEqual(exact[0]["relation"], "exact")
        self.assertEqual(prefix[0]["relation"], "prefix")
        result = evaluate(self.cases["overlapping_ownership"], ROOT)
        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "sol")
        self.assertIn("split_isolated", result["reason_codes"])

    def test_malformed_and_unsupported_requests_fail_closed(self):
        for request in (None, {}, {"kind": "unknown"}, {"kind": "scout", "separate": True}):
            result = evaluate(request, ROOT)
            self.assertFalse(result["ok"])
            self.assertEqual(result["route"], "sol")
            self.assertTrue(result["fallback"])

        result = evaluate(self.cases["malformed_input"], ROOT)
        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "sol")
        self.assertIn("unsafe_ownership_path", result["reason_codes"])

    def test_sensitive_ownership_is_rejected(self):
        for path in (
            ".env",
            ".env.example",
            ".git/config",
            "keys/server.pem",
            "secrets.json",
            "access_token.txt",
            "password.txt",
            "private_api_key.json",
            "id_rsa",
            ".netrc",
            "audit.log",
            "customer_records.json",
            "production.db",
        ):
            request = dict(self.cases["valid_delegation"])
            request["ownership"] = {"scout": [path]}
            result = evaluate(request, ROOT)
            self.assertFalse(result["ok"], path)
            self.assertEqual(result["route"], "sol")
            self.assertIn("sensitive_ownership_path", result["reason_codes"], path)

    def test_existing_symlink_component_is_rejected(self):
        temporary, copy = self._copy_runtime()
        outside = Path(temporary.name) / "outside"
        outside.mkdir()
        try:
            os.symlink(outside, copy / "linked")
            request = dict(self.cases["valid_delegation"])
            request["ownership"] = {"scout": ["linked/spec.md"]}
            result = evaluate(request, copy)
            self.assertFalse(result["ok"])
            self.assertEqual(result["route"], "sol")
            self.assertIn("unsafe_ownership_path", result["reason_codes"])
        finally:
            temporary.cleanup()

    def test_coordinated_semantic_role_edit_is_detected(self):
        temporary, copy = self._copy_runtime()
        try:
            role = copy / "agents" / "luna_scout_fast.toml"
            role.write_text(role.read_text().replace("`scope`", "`scope_removed`", 1))
            policy_path = copy / POLICY_RELATIVE
            policy = json.loads(policy_path.read_text())
            digest = hashlib.sha256(role.read_bytes()).hexdigest()
            policy["roles"]["luna_scout_fast"]["sha256"] = digest
            policy_path.write_text(json.dumps(policy, indent=2) + "\n")
            report = verify_contract(copy)
            self.assertFalse(report["ok"])
            self.assertIn("role_semantic_contract", report["errors"])
        finally:
            temporary.cleanup()

    def test_unknown_contract_and_role_keys_fail_closed(self):
        temporary, copy = self._copy_runtime()
        try:
            policy_path = copy / POLICY_RELATIVE
            policy = json.loads(policy_path.read_text())
            policy["unexpected"] = True
            policy_path.write_text(json.dumps(policy, indent=2) + "\n")
            report = verify_contract(copy)
            self.assertFalse(report["ok"])
            self.assertIn("unknown_contract_key", report["errors"])
        finally:
            temporary.cleanup()

        temporary, copy = self._copy_runtime()
        try:
            policy_path = copy / POLICY_RELATIVE
            policy = json.loads(policy_path.read_text())
            policy["roles"]["luna_scout_fast"]["unexpected"] = True
            policy_path.write_text(json.dumps(policy, indent=2) + "\n")
            report = verify_contract(copy)
            self.assertFalse(report["ok"])
            self.assertIn("unknown_role_key", report["errors"])
        finally:
            temporary.cleanup()

    def test_contract_json_is_bounded_strict_and_fail_closed(self):
        for raw in (
            '{"schema_version":1,"schema_version":1}',
            "[" * 10000 + "]" * 10000,
            "x" * (64 * 1024 + 1),
        ):
            temporary, copy = self._copy_runtime()
            try:
                (copy / POLICY_RELATIVE).write_text(raw)
                report = verify_contract(copy)
                self.assertFalse(report["ok"])
                self.assertTrue(
                    any(error in report["errors"] for error in ("policy_unreadable", "contract_not_object"))
                )
            finally:
                temporary.cleanup()

    def test_config_semantics_are_checked_after_hash_update(self):
        temporary, copy = self._copy_runtime()
        try:
            snippet = copy / "config-snippet.toml"
            snippet.write_text(snippet.read_text().replace('model = "gpt-5.6-sol"', 'model = "gpt-5.6-luna"', 1))
            policy_path = copy / POLICY_RELATIVE
            policy = json.loads(policy_path.read_text())
            policy["runtime"]["config_snippet_sha256"] = hashlib.sha256(snippet.read_bytes()).hexdigest()
            policy_path.write_text(json.dumps(policy, indent=2) + "\n")
            report = verify_contract(copy)
            self.assertFalse(report["ok"])
            self.assertIn("runtime_config_drift", report["errors"])
        finally:
            temporary.cleanup()

    def test_active_root_comparison_does_not_require_snippet(self):
        temporary, copy = self._copy_runtime()
        active = Path(temporary.name) / "active"
        for relative in (POLICY_AGENTS_RELATIVE, *(d["path"] for d in ROLE_DEFINITIONS.values())):
            source = copy / relative
            destination = active / ("AGENTS.md" if relative == POLICY_AGENTS_RELATIVE else relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        try:
            report = verify_active_root(active, ROOT)
            self.assertTrue(report["ok"])
            self.assertTrue(report["active_root_match"])
            self.assertEqual(report["role_matches"], 5)
            (active / "agents" / "luna_worker_fast.toml").write_text(
                (active / "agents" / "luna_worker_fast.toml").read_text() + "\n# drift\n"
            )
            report = verify_active_root(active, ROOT)
            self.assertFalse(report["ok"])
            self.assertFalse(report["active_root_match"])
            self.assertIn("active_role_drift", report["errors"])
        finally:
            temporary.cleanup()

    def test_active_root_can_validate_sanitized_installed_config(self):
        temporary, copy = self._copy_runtime()
        active = Path(temporary.name) / "active"
        for relative in (POLICY_AGENTS_RELATIVE, *(d["path"] for d in ROLE_DEFINITIONS.values())):
            source = copy / relative
            destination = active / ("AGENTS.md" if relative == POLICY_AGENTS_RELATIVE else relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        active_config = Path(temporary.name) / "config.toml"
        shutil.copyfile(ROOT / "config-snippet.toml", active_config)
        try:
            report = verify_active_root(active, ROOT, active_config)
            self.assertTrue(report["ok"])
            self.assertTrue(report["active_config_checked"])
            self.assertTrue(report["active_config_match"])
            active_config.write_text(
                active_config.read_text().replace(
                    'model_reasoning_effort = "xhigh"',
                    'model_reasoning_effort = "xhigh"\nservice_tier = "default"',
                    1,
                )
            )
            report = verify_active_root(active, ROOT, active_config)
            self.assertFalse(report["ok"])
            self.assertFalse(report["active_config_match"])
            self.assertIn("active_config_drift", report["errors"])
        finally:
            temporary.cleanup()

    def _copy_runtime(self):
        temporary = tempfile.TemporaryDirectory()
        copy = Path(temporary.name) / "root"
        for relative in (
            POLICY_AGENTS_RELATIVE,
            "config-snippet.toml",
            POLICY_RELATIVE,
            "agents/luna_critic_fast.toml",
            "agents/luna_max_fast.toml",
            "agents/luna_scout_fast.toml",
            "agents/luna_tester_fast.toml",
            "agents/luna_worker_fast.toml",
        ):
            source = ROOT / relative
            destination = copy / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        return temporary, copy

    def test_runtime_hash_and_settings_drift_fail_closed(self):
        temporary, copy = self._copy_runtime()
        try:
            agents = copy / POLICY_AGENTS_RELATIVE
            agents.write_text(agents.read_text() + "\n# drift\n")
            report = verify_contract(copy)
            self.assertFalse(report["ok"])
            self.assertFalse(report["runtime_agents_match"])
            self.assertIn("runtime_agents_drift", report["errors"])
        finally:
            temporary.cleanup()

        temporary, copy = self._copy_runtime()
        try:
            snippet = copy / "config-snippet.toml"
            snippet.write_text(snippet.read_text().replace("max_concurrent_threads_per_session = 3", "max_concurrent_threads_per_session = 4"))
            report = verify_contract(copy)
            self.assertFalse(report["ok"])
            self.assertFalse(report["runtime_config_match"])
            self.assertIn("runtime_config_drift", report["errors"])
        finally:
            temporary.cleanup()

    def test_cli_reports_dynamic_root_match(self):
        environment = dict(__import__("os").environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "scripts/routing_policy.py", "verify", "--format", "json"]
        completed = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertTrue(report["runtime_root_match"])

    def test_route_cli_is_strict_bounded_and_nonzero_on_fallback(self):
        valid = json.dumps(self.cases["valid_delegation"], separators=(",", ":"))
        command = [sys.executable, "scripts/routing_policy.py", "route", "--format", "json", "--request", valid]
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["ok"])

        for raw in (
            '{"kind":"scout","kind":"worker"}',
            "[" * 10000 + "]" * 10000,
            "x" * (64 * 1024 + 1),
        ):
            completed = subprocess.run(
                [sys.executable, "scripts/routing_policy.py", "route", "--format", "json", "--request", raw],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            result = json.loads(completed.stdout)
            self.assertFalse(result["ok"])
            self.assertEqual(result["route"], "sol")

        temporary, copy = self._copy_runtime()
        try:
            agents = copy / POLICY_AGENTS_RELATIVE
            agents.write_text(agents.read_text() + "\n# drift\n")
            completed = subprocess.run(
                [sys.executable, "scripts/routing_policy.py", "verify", "--root", str(copy), "--format", "json"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(json.loads(completed.stdout)["ok"])
        finally:
            temporary.cleanup()

    def test_active_root_cli_reports_pass_and_drift(self):
        temporary, copy = self._copy_runtime()
        active = Path(temporary.name) / "active"
        for relative in (POLICY_AGENTS_RELATIVE, *(d["path"] for d in ROLE_DEFINITIONS.values())):
            source = copy / relative
            destination = active / ("AGENTS.md" if relative == POLICY_AGENTS_RELATIVE else relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            command = [sys.executable, "scripts/routing_policy.py", "active-root", "--root", str(ROOT), "--active-root", str(active), "--format", "json"]
            completed = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(json.loads(completed.stdout)["active_root_match"])
            (active / "AGENTS.md").write_text((active / "AGENTS.md").read_text() + "\n# drift\n")
            completed = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(json.loads(completed.stdout)["active_root_match"])
        finally:
            temporary.cleanup()

    def test_active_root_accepts_exact_managed_override_and_rejects_duplicate_markers(self):
        temporary, copy = self._copy_runtime()
        active = Path(temporary.name) / "active"
        for relative in (POLICY_AGENTS_RELATIVE, *(d["path"] for d in ROLE_DEFINITIONS.values())):
            source = copy / relative
            destination = active / ("AGENTS.md" if relative == POLICY_AGENTS_RELATIVE else relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        start = b"# >>> sol-luna-orchestration-kit managed block >>>\n"
        end = b"# <<< sol-luna-orchestration-kit managed block <<<\n"
        try:
            policy_agents = (copy / POLICY_AGENTS_RELATIVE).read_bytes()
            (active / "AGENTS.override.md").write_bytes(b"user override\n" + start + policy_agents + end)
            report = verify_active_root(active, copy)
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["active_agents_path"], "AGENTS.override.md")
            (active / "AGENTS.override.md").write_bytes(
                (active / "AGENTS.override.md").read_bytes() + start + policy_agents + end
            )
            report = verify_active_root(active, copy)
            self.assertFalse(report["ok"])
            self.assertIn("active_agents_drift", report["errors"])
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
