import tempfile
import unittest
from pathlib import Path
from scripts import team_receipts as receipts


def payload():
    return {"role": "critic", "requested_model": "gpt-6.1-sol", "requested_reasoning": "high",
            "observed_model": None, "observed_reasoning": None, "root_model": None,
            "runtime_provenance": "unknown", "outcome": "accepted", "checks": ["pass"],
            "total_tokens": None, "token_provenance": "unknown"}


class TeamReceiptsTests(unittest.TestCase):
    def test_unknown_runtime_and_usage_stay_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            receipts.record(root, payload())
            report = receipts.status(root)
            self.assertEqual(report["accepted"], 1)
            self.assertEqual(report["runtime_observed"], 0)
            self.assertIsNone(report["total_tokens"])
            self.assertIsNone(report["billed_cost"])

    def test_any_root_model_with_attributed_runtime_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            value = payload()
            value.update(root_model="gpt-6-astra", observed_model="gpt-6.1-sol", observed_reasoning="high",
                         runtime_provenance="runtime_metadata", total_tokens=123, token_provenance="attributed_runtime_usage")
            receipts.record(root, value)
            report = receipts.status(root)
            self.assertEqual(report["total_tokens"], 123)
            self.assertIsNone(report["whole_workflow_usage"])
            (root / ".sol-luna/team-receipts/bad.json").write_text('{}')
            self.assertIsNone(receipts.status(root)["total_tokens"])

    def test_invalid_evidence_never_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            for change in ({"observed_model": "gpt-6.1-sol"}, {"checks": ["fail"]},
                           {"total_tokens": 12}, {"prompt": "private"}):
                with self.assertRaises(ValueError):
                    receipts.record(root, {**payload(), **change})
            self.assertFalse((root / ".sol-luna").exists())


if __name__ == "__main__":
    unittest.main()
