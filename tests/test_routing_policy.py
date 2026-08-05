import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import routing_policy
from scripts.routing_policy import (
    APP_TASK_TRANSPORT,
    DEFAULT_ROOT,
    ELIGIBLE_NATIVE_FAILURE_CODES,
    LUNA_TRANSPORT,
    MAX_UPGRADE_REASON_CODES,
    ROUTINE_TASK_CLASSES,
    POLICY_AGENTS_RELATIVE,
    POLICY_RELATIVE,
    ROLE_DEFINITIONS,
    STANDARD_ROLE_DEFINITIONS,
    detect_ownership_conflicts,
    evaluate,
    evaluate_transport_failure,
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

    def test_valid_substantial_delegation_routes_to_bounded_role(self):
        result = evaluate(self.cases["valid_delegation"], ROOT)
        self.assertTrue(result["ok"])
        self.assertEqual(result["decision"], "delegate")
        self.assertEqual(result["route"], "luna_scout_fast")
        self.assertEqual(result["reasoning"], "medium")
        self.assertFalse(result["fallback"])
        self.assertEqual(result["transport"], LUNA_TRANSPORT)
        self.assertEqual(result["task_class"], "broad_mapping")
        self.assertEqual(result["lane_budget"], 2)

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
            "on_spawn_error": "evaluate_transport_failure",
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

    def _fallback_event(self, *, profile="fast"):
        request = dict(self.cases["valid_delegation"])
        request["profile"] = profile
        lane_id = next(iter(request["ownership"]))
        return {
            "routing_request": request,
            "fallback_authorization": {
                "authorized": True,
                "target": "codex_app_task",
                "scope": "this_lane_once",
                "lane_id": lane_id,
                "max_attempts": 1,
                "current_checkout": True,
            },
            "failure_code": "custom_role_rejected",
            "attempts_used": 0,
            "app_task_available": True,
            "project_context": {
                "current_checkout_root": str(ROOT),
                "app_project_root": str(ROOT),
            },
        }

    def test_eligible_native_failure_can_route_once_to_explicit_app_task(self):
        for profile in ("fast", "standard"):
            with self.subTest(profile=profile):
                event = self._fallback_event(profile=profile)
                result = evaluate_transport_failure(event, ROOT)
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["decision"], "create_codex_app_task")
                self.assertEqual(result["route"], "codex_app_task")
                self.assertEqual(result["transport"], APP_TASK_TRANSPORT)
                self.assertEqual(result["requested_profile"], profile)
                self.assertEqual(result["model_override"], None)
                self.assertTrue(result["authorization_consumed"])
                self.assertEqual(result["app_task_attempt_number"], 1)
                self.assertEqual(result["app_task_attempts_remaining"], 0)
                self.assertTrue(result["project_root_verified"])
                self.assertNotIn(str(ROOT), json.dumps(result))

    def test_app_task_fallback_never_bypasses_admission_or_replays(self):
        denied = self._fallback_event()
        denied["routing_request"] = dict(denied["routing_request"])
        denied["routing_request"]["provable"] = False
        result = evaluate_transport_failure(denied, ROOT)
        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "sol")
        self.assertFalse(result["fallback"])
        self.assertEqual(result["fallback_stage"], "pre_admission")
        self.assertIsNone(result["native_failure_code"])
        self.assertEqual(result["app_task_attempts_used"], 0)
        self.assertFalse(result["authorization_consumed"])
        self.assertIn("admission_not_approved", result["reason_codes"])
        self.assertIn("split_provable", result["admission_reason_codes"])

        replay = self._fallback_event()
        replay["attempts_used"] = 1
        result = evaluate_transport_failure(replay, ROOT)
        self.assertFalse(result["ok"])
        self.assertIn("fallback_attempt_exhausted", result["reason_codes"])
        self.assertEqual(result["fallback_stage"], "post_admission_transport")
        self.assertEqual(result["app_task_attempts_used"], 1)
        self.assertTrue(result["authorization_consumed"])

    def test_app_task_fallback_requires_exact_authorization_and_capability(self):
        cases = []
        missing = self._fallback_event(); missing["fallback_authorization"] = None; cases.append(("fallback_not_authorized", missing))
        wrong_lane = self._fallback_event(); wrong_lane["fallback_authorization"] = dict(wrong_lane["fallback_authorization"], lane_id="other_lane"); cases.append(("fallback_not_authorized", wrong_lane))
        bool_attempt = self._fallback_event(); bool_attempt["fallback_authorization"] = dict(bool_attempt["fallback_authorization"], max_attempts=True); cases.append(("fallback_not_authorized", bool_attempt))
        unavailable = self._fallback_event(); unavailable["app_task_available"] = False; cases.append(("app_task_unavailable", unavailable))
        ineligible = self._fallback_event(); ineligible["failure_code"] = "lane_timeout"; cases.append(("ineligible_transport_failure", ineligible))
        malformed = self._fallback_event(); malformed["attempts_used"] = True; cases.append(("malformed_fallback_event", malformed))
        for expected, event in cases:
            with self.subTest(expected=expected):
                result = evaluate_transport_failure(event, ROOT)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["route"], "sol")
                self.assertIn(expected, result["reason_codes"])

        unavailable_result = evaluate_transport_failure(unavailable, ROOT)
        self.assertEqual(unavailable_result["fallback_stage"], "post_admission_transport")
        self.assertEqual(unavailable_result["native_failure_code"], "custom_role_rejected")
        self.assertEqual(unavailable_result["app_task_attempts_used"], 1)
        self.assertTrue(unavailable_result["authorization_consumed"])

        ineligible_result = evaluate_transport_failure(ineligible, ROOT)
        self.assertFalse(ineligible_result["fallback"])
        self.assertEqual(ineligible_result["fallback_stage"], "post_admission_ineligible")
        self.assertIsNone(ineligible_result["native_failure_code"])

        malformed_result = evaluate_transport_failure(malformed, ROOT)
        self.assertFalse(malformed_result["fallback"])
        self.assertEqual(malformed_result["fallback_stage"], "fallback_validation")
        self.assertIsNone(malformed_result["native_failure_code"])

    def test_app_task_fallback_requires_matching_canonical_project_root(self):
        with tempfile.TemporaryDirectory() as other_root:
            mismatch = self._fallback_event()
            mismatch["project_context"] = dict(
                mismatch["project_context"],
                app_project_root=other_root,
            )
            result = evaluate_transport_failure(mismatch, ROOT)
        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "sol")
        self.assertIn("app_project_mismatch", result["reason_codes"])
        self.assertEqual(result["fallback_stage"], "post_admission_transport")
        self.assertEqual(result["app_task_attempts_used"], 1)
        self.assertTrue(result["authorization_consumed"])
        self.assertNotIn(other_root, json.dumps(result))

        missing = self._fallback_event()
        missing["project_context"] = None
        result = evaluate_transport_failure(missing, ROOT)
        self.assertFalse(result["ok"])
        self.assertIn("app_project_mismatch", result["reason_codes"])
        self.assertEqual(result["app_task_attempts_used"], 1)

        self.assertEqual(
            set(ELIGIBLE_NATIVE_FAILURE_CODES),
            {"custom_role_rejected", "custom_role_unavailable", "native_spawn_tool_unavailable", "native_spawn_transport_error"},
        )

    def test_routine_classes_and_failed_gate_route_directly_to_sol(self):
        for task_class in ROUTINE_TASK_CLASSES:
            request = dict(self.cases["direct_work"])
            request["task_class"] = task_class
            result = evaluate(request, ROOT)
            self.assertFalse(result["ok"], task_class)
            self.assertIn("routine_task_class", result["reason_codes"])
        for case_name in ("direct_work", "rejected_gate"):
            result = evaluate(self.cases[case_name], ROOT)
            self.assertFalse(result["ok"])
            self.assertEqual(result["route"], "sol")
            self.assertTrue(result["fallback"])
            self.assertTrue(
                "routine_task_class" in result["reason_codes"]
                or any(code.startswith("split_") for code in result["reason_codes"])
            )

    def test_classification_benefit_threshold_and_risk_review_fail_closed(self):
        base = dict(self.cases["valid_delegation"])
        mutations = (
            ("unsupported_task_class", lambda value: value.update(task_class="unknown")),
            ("unsupported_benefit_code", lambda value: value.update(benefit_code="cheap_model")),
            ("substantive_threshold_not_met", lambda value: value.update(substantive_work={"estimated_minutes": 19, "affected_files": 0, "distinct_surfaces": 4, "independent_checks": 0})),
            ("malformed_work_classification", lambda value: value.update(substantive_work={"estimated_minutes": 20})),
            ("unsupported_route_classification", lambda value: value.update(kind="worker")),
            ("contradictory_risk_classification", lambda value: value.update(work_band="high_risk")),
        )
        for code, mutate in mutations:
            request = json.loads(json.dumps(base))
            mutate(request)
            result = evaluate(request, ROOT)
            self.assertFalse(result["ok"], code)
            self.assertIn(code, result["reason_codes"])

        risk = dict(self.cases["rejected_gate"])
        risk["provable"] = True
        self.assertTrue(evaluate(risk, ROOT)["ok"])
        risk["risk_domains"] = []
        result = evaluate(risk, ROOT)
        self.assertFalse(result["ok"])
        self.assertIn("risk_domain_required", result["reason_codes"])

        legacy_boolean = dict(base)
        legacy_boolean["large_enough"] = True
        result = evaluate(legacy_boolean, ROOT)
        self.assertIn("unsupported_request_field", result["reason_codes"])

        unhashable_risk = dict(base)
        unhashable_risk["risk_domains"] = [{}]
        result = evaluate(unhashable_risk, ROOT)
        self.assertFalse(result["ok"])
        self.assertIn("malformed_work_classification", result["reason_codes"])

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
        analysis["task_class"] = "complex_analysis"
        analysis["substantive_work"] = {"estimated_minutes": 30, "affected_files": 0, "distinct_surfaces": 3, "independent_checks": 1}
        result = evaluate(analysis, ROOT)
        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "sol")
        self.assertIn("max_upgrade_reason_required", result["reason_codes"])

        analysis["max_upgrade_reason"] = "cross_cutting_risk"
        result = evaluate(analysis, ROOT)
        self.assertTrue(result["ok"])
        self.assertEqual(result["route"], "luna_max_fast")

    def test_routine_substantial_and_high_risk_total_lane_budgets(self):
        result = evaluate(self.cases["multiple_waves"], ROOT)
        self.assertTrue(result["ok"])
        self.assertEqual(result["lane_count"], 2)
        self.assertEqual(result["total_lane_count"], 2)
        self.assertEqual(result["max_concurrent_delegated_lanes"], 3)
        self.assertEqual(result["max_total_delegated_lanes"], 3)
        self.assertEqual(result["dependent_work"], "serialized")

        too_many = dict(self.cases["multiple_waves"])
        too_many["work_band"] = "routine"
        result = evaluate(too_many, ROOT)
        self.assertFalse(result["ok"])
        self.assertEqual(result["route"], "sol")
        self.assertIn("lane_budget_exceeded", result["reason_codes"])

        routine_third = dict(too_many)
        routine_third["lane_count"] = 3
        routine_third["total_lane_count"] = 3
        routine_third["third_lane_justification"] = "explicit_user_direction"
        routine_third["ownership"] = {
            "routine_a": ["tests/a.py"],
            "routine_b": ["tests/b.py"],
            "routine_c": ["tests/c.py"],
        }
        result = evaluate(routine_third, ROOT)
        self.assertIn("lane_budget_exceeded", result["reason_codes"])

        high = dict(self.cases["rejected_gate"])
        high["provable"] = True
        high["lane_count"] = 3
        high["total_lane_count"] = 3
        high["third_lane_justification"] = "high_risk"
        high["ownership"] = {
            "critic_a": ["src/a.py"],
            "critic_b": ["src/b.py"],
            "critic_c": ["src/c.py"],
        }
        result = evaluate(high, ROOT)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["lane_budget"], 3)

        missing_reason = dict(high)
        del missing_reason["third_lane_justification"]
        result = evaluate(missing_reason, ROOT)
        self.assertIn("third_lane_justification_required", result["reason_codes"])

        ordinary_third = dict(high)
        ordinary_third["work_band"] = "substantial"
        ordinary_third["risk_domains"] = []
        ordinary_third["task_class"] = "substantial_validation"
        ordinary_third["benefit_code"] = "parallel_latency"
        ordinary_third["kind"] = "tester"
        ordinary_third["substantive_work"] = {"estimated_minutes": 20, "affected_files": 0, "distinct_surfaces": 3, "independent_checks": 3}
        ordinary_third["third_lane_justification"] = "explicit_user_direction"
        result = evaluate(ordinary_third, ROOT)
        self.assertTrue(result["ok"], result)

    def test_evidence_packet_contract_is_exact_and_bounded(self):
        evidence = {
            "status": "completed",
            "files_or_surfaces": ["scripts/routing_policy.py"],
            "checks": [{"name": "routing unit tests", "status": "pass"}],
            "findings": [{"severity": "low", "code": "route_ok", "reference": "scripts/routing_policy.py"}],
            "risks": ["Runtime availability varies"],
            "confidence": "high",
            "recommendation": "accept",
        }
        self.assertTrue(validate_evidence(evidence))
        missing = dict(evidence)
        del missing["findings"]
        self.assertFalse(validate_evidence(missing))
        extra = dict(evidence)
        extra["next_action"] = "not part of v2"
        self.assertFalse(validate_evidence(extra))
        oversized = dict(evidence)
        oversized["risks"] = ["x" * 161]
        self.assertFalse(validate_evidence(oversized))
        too_many = dict(evidence)
        too_many["checks"] = [{"name": f"check {index}", "status": "pass"} for index in range(9)]
        self.assertFalse(validate_evidence(too_many))
        sensitive = dict(evidence)
        sensitive["risks"] = ["password=do-not-store"]
        self.assertFalse(validate_evidence(sensitive))
        identifier = dict(evidence)
        identifier["risks"] = ["task_id abc"]
        self.assertFalse(validate_evidence(identifier))
        invalid_enum = dict(evidence)
        invalid_enum["confidence"] = "certain"
        self.assertFalse(validate_evidence(invalid_enum))
        raw_log = dict(evidence)
        raw_log["risks"] = ["Traceback (most recent call last):"]
        self.assertFalse(validate_evidence(raw_log))
        sensitive_key = dict(evidence)
        sensitive_key["checks"] = [{"name": "tests", "status": "pass", "credentials": "none"}]
        self.assertFalse(validate_evidence(sensitive_key))
        unhashable_file = dict(evidence)
        unhashable_file["files_or_surfaces"] = [{}]
        self.assertFalse(validate_evidence(unhashable_file))
        over_two_kb = dict(evidence)
        over_two_kb["files_or_surfaces"] = [
            f"surfaces/{index}-" + "a" * 145 for index in range(12)
        ]
        self.assertFalse(validate_evidence(over_two_kb))

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
        for request in (None, {}, {"profile": []}, {"kind": "unknown"}, {"kind": "scout", "separate": True}):
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
            role = copy / ROLE_DEFINITIONS["scout"]["path"]
            role.write_text(role.read_text().replace("`status`", "`status_removed`", 1))
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
            destination = active / ("AGENTS.md" if relative == POLICY_AGENTS_RELATIVE else f"agents/{Path(relative).name}")
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
            destination = active / ("AGENTS.md" if relative == POLICY_AGENTS_RELATIVE else f"agents/{Path(relative).name}")
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
            *(definition["path"] for definition in ROLE_DEFINITIONS.values()),
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

        fallback = json.dumps(self._fallback_event(profile="standard"), separators=(",", ":"))
        completed = subprocess.run(
            [sys.executable, "scripts/routing_policy.py", "fallback", "--format", "json", "--request", fallback],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        fallback_result = json.loads(completed.stdout)
        self.assertEqual(fallback_result["decision"], "create_codex_app_task")
        self.assertEqual(fallback_result["requested_profile"], "standard")

        for raw in (
            '{"kind":"scout","kind":"worker"}',
            "[" * 10000 + "]" * 10000,
            "x" * (64 * 1024 + 1),
        ):
            if os.name == "nt" and len(raw) > 8000:
                output = io.StringIO()
                with redirect_stdout(output):
                    returncode = routing_policy.main(
                        ["route", "--format", "json", "--request", raw]
                    )
                result = json.loads(output.getvalue())
                self.assertNotEqual(returncode, 0)
            else:
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
            destination = active / ("AGENTS.md" if relative == POLICY_AGENTS_RELATIVE else f"agents/{Path(relative).name}")
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
            destination = active / ("AGENTS.md" if relative == POLICY_AGENTS_RELATIVE else f"agents/{Path(relative).name}")
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
