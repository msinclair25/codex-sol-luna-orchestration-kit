import copy
import json
import unittest

from tests.test_m5_plugin import _envelope, _event, _run_guard, _deny_code
from tests.test_team_settings import CATALOG


def event(model="gpt-6-luna"):
    old = _envelope()
    envelope = {"schema_version": 2, "role": "worker",
                "team": {"settings": {"model": model}, "catalog": CATALOG, "runtime_limit": 3, "active": 0},
                "ownership": old["routing_request"]["ownership"], "assignment": old["assignment"]}
    result = _event(envelope)
    result["model"] = "gpt-6-astra"
    result["tool_input"]["agent_type"] = "default"
    if model != "inherit":
        result["tool_input"].update(model=model, reasoning_effort="high" if model == "gpt-6-luna" else "low")
    return result


class TeamGuardTests(unittest.TestCase):
    def test_active_plus_pending_wave_cannot_exceed_limit(self):
        changed = event()
        envelope = json.loads(changed["tool_input"]["message"])
        envelope["team"]["active"] = 2
        envelope["ownership"]["second_lane"] = ["tests/isolated-test.py"]
        changed["tool_input"]["message"] = json.dumps(envelope)
        self.assertIn("team_wave_concurrency_limit", _deny_code(_run_guard(changed)))
        del envelope["ownership"]["second_lane"]
        changed["tool_input"]["message"] = json.dumps(envelope)
        self.assertEqual(_run_guard(changed).stdout, "")

    def test_root_choice_and_model_switch_are_independent(self):
        for model in ("gpt-6-luna", "gpt-6.1-sol", "inherit"):
            result = _run_guard(event(model))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "", result.stdout)

    def test_pinned_role_and_incorrect_model_are_denied(self):
        for field, value in (("agent_type", "luna_worker_fast"), ("model", "gpt-5.6-luna"), ("reasoning_effort", "ultra")):
            changed = event()
            changed["tool_input"][field] = value
            self.assertIn("team_spawn_mismatch", _deny_code(_run_guard(changed)))

    def test_overlap_is_denied(self):
        changed = event()
        envelope = json.loads(changed["tool_input"]["message"])
        envelope["ownership"]["second_lane"] = ["src"]
        changed["tool_input"]["message"] = json.dumps(envelope)
        self.assertIn("project_ownership_path_unsafe", _deny_code(_run_guard(changed)))

    def test_disabled_role_and_exhausted_concurrency_are_denied(self):
        for patch in ({"roles": {}}, {"max_concurrent": 0}):
            changed = event()
            envelope = json.loads(changed["tool_input"]["message"])
            envelope["team"]["settings"].update(patch)
            changed["tool_input"]["message"] = json.dumps(envelope)
            self.assertIn("team_launch_invalid", _deny_code(_run_guard(changed)))


if __name__ == "__main__":
    unittest.main()
