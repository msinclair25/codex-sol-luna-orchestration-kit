import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "m1-role-smoke-2026-08-02.json"


class M1LiveEvidenceTests(unittest.TestCase):
    def test_live_role_evidence_is_complete_and_privacy_safe(self):
        report = json.loads(EVIDENCE.read_text())
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["milestone"], "M1")
        self.assertEqual(report["outcome"], "accepted")
        self.assertEqual(report["launches"]["completed"], 5)
        self.assertEqual(report["launches"]["failed"], 0)
        self.assertEqual(report["launches"]["waves"], [3, 2])
        self.assertEqual(report["launches"]["observed_max_concurrency"], 3)

        expected = {
            "luna_scout_fast": "medium",
            "luna_worker_fast": "high",
            "luna_critic_fast": "high",
            "luna_tester_fast": "medium",
            "luna_max_fast": "max",
        }
        self.assertEqual({item["role"] for item in report["roles"]}, set(expected))
        for item in report["roles"]:
            self.assertEqual(item["model"], "gpt-5.6-luna")
            self.assertEqual(item["reasoning_effort"], expected[item["role"]])
            self.assertEqual(item["service_tier_requested"], "fast")
            self.assertEqual(item["service_tier_resolver"], "accepted")
            self.assertEqual(
                item["service_tier_probe_ref"],
                f"gpt-5.6-luna/{expected[item['role']]}/fast",
            )
            self.assertEqual(item["service_tier_session_field"], "unknown")
            self.assertTrue(item["completed"])
        max_role = next(item for item in report["roles"] if item["role"] == "luna_max_fast")
        self.assertEqual(max_role["max_upgrade_reason"], "genuine_ambiguity")

        self.assertEqual(report["session_source"]["service_tier_field_coverage"], "0_of_6")
        probes = report["service_tier_probe"]["combinations"]
        self.assertEqual(
            {item["ref"] for item in probes},
            {
                "gpt-5.6-luna/medium/fast",
                "gpt-5.6-luna/high/fast",
                "gpt-5.6-luna/max/fast",
            },
        )
        self.assertTrue(all(item["exit_status"] == 0 for item in probes))
        self.assertTrue(all(item["expected_reply_observed"] for item in probes))
        self.assertTrue(all(not item["unsupported_or_omitted_warning"] for item in probes))
        self.assertFalse(report["session_source"]["raw_session_identifiers_stored"])
        self.assertFalse(report["session_source"]["prompts_or_tool_content_stored"])
        rendered_keys = set()

        def collect_keys(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    rendered_keys.add(key)
                    collect_keys(item)
            elif isinstance(value, list):
                for item in value:
                    collect_keys(item)

        collect_keys(report)
        self.assertTrue(
            {"prompt", "source_code", "file_contents", "tool_arguments", "tool_output", "session_id"}.isdisjoint(rendered_keys)
        )


if __name__ == "__main__":
    unittest.main()
