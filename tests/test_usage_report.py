import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.usage_report import analyze, main, to_markdown


FIXTURES = Path(__file__).parent / "fixtures"


class UsageReportTests(unittest.TestCase):
    def _analyze_records(self, records):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            return analyze([str(path)])

    def test_root_and_fork_usage_settings_and_boundaries(self):
        report = analyze([str(FIXTURES)])

        self.assertEqual(report["runs"], 3)
        self.assertEqual(report["completed"], 3)
        self.assertEqual(report["incomplete"], 0)
        self.assertEqual(report["token_usage_runs"], 2)

        groups = {(item["role"], item["model"]): item for item in report["groups"]}
        root = groups[("root", "gpt-5.6-sol")]
        self.assertEqual(root["reasoning_effort"], "xhigh")
        self.assertEqual(root["service_tier"], "default")
        self.assertEqual(root["tokens"], {
            "input": 200,
            "cached_input": 40,
            "output": 50,
            "reasoning": 8,
            "total": 250,
        })
        self.assertEqual(root["duration_ms"], 8000)
        self.assertEqual(root["tool_calls"], 1)
        self.assertEqual(root["completed"], 1)  # one completed root run with two completed turns

        child = groups[("luna_max_fast", "gpt-5.6-luna")]
        self.assertEqual(child["reasoning_effort"], "max")
        self.assertEqual(child["service_tier"], "priority")
        self.assertEqual(child["tokens"], {
            "input": 50,
            "cached_input": 10,
            "output": 15,
            "reasoning": 3,
            "total": 65,
        })
        self.assertEqual(child["duration_ms"], 4000)
        self.assertEqual(child["tool_calls"], 1)

    def test_overlap_concurrency_and_parallelism(self):
        report = analyze([str(FIXTURES)])
        overall = report["overall"]

        # Root contributes [1000,1005] + [1010,1013], the child contributes
        # [1002,1006], and malformed contributes [1020,1021] (seconds).
        self.assertEqual(overall["active_time_ms"], 13000)
        self.assertEqual(overall["wall_time_ms"], 10000)
        self.assertEqual(overall["max_concurrency"], 2)
        self.assertAlmostEqual(overall["wall_span_overlap_ratio"], 1.3)

    def test_malformed_and_unrecognized_files_are_summarized_without_leaking(self):
        report = analyze([str(FIXTURES)])
        rendered = json.dumps(report, sort_keys=True) + to_markdown(report)

        self.assertTrue(any("malformed records" in warning for warning in report["warnings"]))
        self.assertTrue(any("unrecognized" in warning for warning in report["warnings"]))
        for secret in (
            "root-session-secret",
            "root-id-secret",
            "child-session-secret",
            "parent-thread-secret",
            "prompt argument secret",
            "tool arguments secret",
            "stdout secret",
            "child output secret",
            "/private/project/should-not-print",
            "unrecognized-id-secret",
        ):
            self.assertNotIn(secret, rendered)

    def test_since_filter_is_inclusive_and_empty_result_is_safe(self):
        report = analyze([str(FIXTURES)], since="2026-08-02")
        self.assertEqual(report["runs"], 0)
        self.assertEqual(report["overall"]["wall_time_ms"], 0)
        self.assertTrue(any("No recognized rollout sessions" in warning for warning in report["warnings"]))

    def test_json_cli_format(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = main([str(FIXTURES / "luna_child.jsonl"), "--format", "json"])
        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["runs"], 1)
        self.assertEqual(report["groups"][0]["role"], "luna_max_fast")
        self.assertNotIn("child-id-secret", output.getvalue())

    def test_role_label_alone_does_not_make_a_child(self):
        # Parent/fork metadata, not the role label, selects child baseline
        # accounting.  This synthetic run has a cumulative pre-turn token
        # count, so root accounting is observably different from a child delta.
        records = [
            {
                "timestamp": "2026-08-01T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "timestamp": "2026-08-01T10:00:00Z",
                    "agent_role": "luna_worker_fast",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_started",
                    "turn_id": "turn",
                    "started_at": 1000,
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 5,
                            "cached_input_tokens": 1,
                            "output_tokens": 1,
                            "reasoning_output_tokens": 0,
                            "total_tokens": 6,
                        }
                    },
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 10,
                            "cached_input_tokens": 2,
                            "output_tokens": 2,
                            "reasoning_output_tokens": 0,
                            "total_tokens": 12,
                        }
                    },
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": "turn",
                    "started_at": 1000,
                    "completed_at": 1001,
                    "duration_ms": 1000,
                },
            },
        ]
        report = self._analyze_records(records)
        self.assertEqual(report["groups"][0]["role"], "luna_worker_fast")
        self.assertEqual(report["groups"][0]["tokens"]["total"], 12)

    def test_root_completion_uses_last_turn(self):
        records = [
            {
                "timestamp": "2026-08-01T10:00:00Z",
                "type": "session_meta",
                "payload": {"timestamp": "2026-08-01T10:00:00Z"},
            },
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "done", "started_at": 1000},
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": "done",
                    "started_at": 1000,
                    "completed_at": 1001,
                    "duration_ms": 1000,
                },
            },
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "still-running", "started_at": 1002},
            },
        ]
        report = self._analyze_records(records)
        self.assertEqual(report["runs"], 1)
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["incomplete"], 1)
        self.assertEqual(report["overall"]["active_time_ms"], 1000)

    def test_child_without_task_boundary_does_not_inherit_parent_tokens(self):
        records = [
            {
                "timestamp": "2026-08-01T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "timestamp": "2026-08-01T10:00:00Z",
                    "agent_role": "luna_scout_fast",
                    "parent_thread_id": "private-parent-id",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 999999,
                            "cached_input_tokens": 888888,
                            "output_tokens": 777,
                            "reasoning_output_tokens": 66,
                            "total_tokens": 1000776,
                        }
                    },
                },
            },
        ]
        report = self._analyze_records(records)
        self.assertEqual(report["token_usage_runs"], 0)
        self.assertEqual(report["groups"][0]["tokens"]["total"], 0)
        self.assertTrue(any("safe child baseline" in item for item in report["warnings"]))

    def test_child_without_prefork_baseline_does_not_claim_tokens(self):
        records = [
            {
                "timestamp": "2026-08-01T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "timestamp": "2026-08-01T10:00:00Z",
                    "agent_role": "luna_worker_fast",
                    "forked_from_id": "private-root-id",
                },
            },
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "child", "started_at": 1000},
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 500000,
                            "cached_input_tokens": 400000,
                            "output_tokens": 500,
                            "reasoning_output_tokens": 50,
                            "total_tokens": 500500,
                        }
                    },
                },
            },
        ]
        report = self._analyze_records(records)
        self.assertEqual(report["token_usage_runs"], 0)
        self.assertEqual(report["overall"]["tokens"]["total"], 0)

    def test_malformed_event_types_and_huge_timestamps_do_not_crash(self):
        records = [
            {
                "timestamp": float("nan"),
                "type": "session_meta",
                "payload": {"timestamp": 10**30, "secondary_bad_timestamp": float("nan")},
            },
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn", "started_at": 1000},
            },
            {"type": "event_msg", "payload": {"type": {"not": "a string"}}},
            {
                "type": "response_item",
                "payload": {"type": {"not": "hashable"}, "call_id": "private-call-id"},
            },
        ]
        report = self._analyze_records(records)
        self.assertEqual(report["runs"], 1)
        self.assertEqual(report["overall"]["tool_calls"], 0)

    def test_root_without_token_snapshot_has_no_token_coverage(self):
        records = [
            {
                "timestamp": "2026-08-01T10:00:00Z",
                "type": "session_meta",
                "payload": {"timestamp": "2026-08-01T10:00:00Z"},
            },
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn", "started_at": 1000},
            },
        ]
        report = self._analyze_records(records)
        self.assertEqual(report["token_usage_runs"], 0)
        self.assertEqual(report["groups"][0]["token_usage_runs"], 0)


if __name__ == "__main__":
    unittest.main()
