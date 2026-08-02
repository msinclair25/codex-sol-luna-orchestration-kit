import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.receipt_tool import (
    MAX_INPUT_BYTES,
    TOP_KEYS,
    _canonical,
    close_receipt,
    summarize,
    validate_paths,
    validate_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class ReceiptToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payloads = {
            name: json.loads((FIXTURES / f"receipt_{name}.json").read_text())
            for name in ("accepted", "rejected", "abandoned")
        }

    def test_valid_dispositions_and_accepted_by_condition(self):
        for name, payload in self.payloads.items():
            body = dict(payload)
            body["receipt_id"] = "mr1-" + hashlib.sha256(_canonical(payload)).hexdigest()
            result = validate_receipt(body)
            self.assertTrue(result["ok"], (name, result))
        invalid = dict(self.payloads["rejected"])
        invalid["receipt_id"] = "mr1-" + hashlib.sha256(_canonical(invalid)).hexdigest()
        invalid["accepted_by"] = "sol"
        self.assertFalse(validate_receipt(invalid)["ok"])

    def test_close_is_deterministic_idempotent_and_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            receipts = Path(directory) / "receipts"
            first = close_receipt(self.payloads["accepted"], receipts)
            second = close_receipt(self.payloads["accepted"], receipts)
            self.assertEqual(first["receipt_id"], second["receipt_id"])
            self.assertFalse(first["idempotent"])
            self.assertTrue(second["idempotent"])
            output = receipts / (first["receipt_id"] + ".json")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(receipts.stat().st_mode), 0o700)
            altered = dict(self.payloads["accepted"])
            altered["closed_at"] = "2026-08-02T10:06:00Z"
            self.assertNotEqual(close_receipt(altered, receipts)["receipt_id"], first["receipt_id"])
            collision_dir = Path(directory) / "collision"
            collision_dir.mkdir(mode=0o700)
            collision_target = collision_dir / (first["receipt_id"] + ".json")
            collision_target.write_bytes(b"different-bytes\n")
            os.chmod(collision_target, 0o600)
            with self.assertRaises(Exception):
                close_receipt(self.payloads["accepted"], collision_dir)

            os.chmod(output, 0o644)
            with self.assertRaises(Exception):
                close_receipt(self.payloads["accepted"], receipts)

    def test_malformed_enum_types_fail_closed_without_traceback(self):
        malformed = json.loads(json.dumps(self.payloads["accepted"]))
        malformed["delegated_lanes"][0]["role"] = []
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            source.write_text(json.dumps(malformed))
            command = [sys.executable, "scripts/receipt_tool.py", "close", "--input", str(source), "--receipts-dir", str(Path(directory) / "receipts")]
            completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(completed.stderr, "")
            self.assertNotIn("Traceback", completed.stdout)
            self.assertLess(len(completed.stdout), 256)

    def test_schema_and_validator_required_fields_are_synchronized(self):
        schema = json.loads((ROOT / "schemas" / "milestone-receipt.v1.schema.json").read_text())
        self.assertEqual(set(schema["required"]), TOP_KEYS)
        self.assertEqual(set(schema["properties"]["repository"]["properties"]["hashes"]["properties"]["roles"]["required"]), {"luna_scout_fast", "luna_worker_fast", "luna_critic_fast", "luna_tester_fast", "luna_max_fast"})
        self.assertEqual(set(schema["properties"]["usage"]["required"]), {"coverage", "provenance", "total_tokens", "weighted_usage", "source_refs", "rate_card_version"})
        lane_properties = schema["properties"]["delegated_lanes"]["items"]["properties"]
        exact_reasons = {"genuine_ambiguity", "cross_cutting_risk", "failed_high_attempt", "high_impact_adversarial_review", None}
        self.assertEqual(set(lane_properties["max_reason"]["enum"]), exact_reasons)
        self.assertEqual(set(lane_properties["escalation"]["properties"]["reason"]["enum"]), exact_reasons)

    def test_validation_rejects_shape_time_hash_enum_negative_and_oversize(self):
        mutations = (
            ("extra", lambda value: value.update(extra=True)),
            ("time", lambda value: value.update(closed_at="2026-08-01T00:00:00Z")),
            ("hash", lambda value: value["repository"]["hashes"].update(agents="0")),
            ("enum", lambda value: value.update(disposition="unknown")),
            ("negative", lambda value: value.update(rework_count=-1)),
            ("array", lambda value: value.update(risks=["none"] * 33)),
        )
        for name, mutate in mutations:
            value = json.loads(json.dumps(self.payloads["accepted"]))
            mutate(value)
            value["receipt_id"] = "mr1-" + hashlib.sha256(_canonical({k: v for k, v in value.items() if k != "receipt_id"})).hexdigest()
            self.assertFalse(validate_receipt(value)["ok"], name)
        oversized = json.loads(json.dumps(self.payloads["accepted"]))
        oversized["project_id"] = "a" * 200
        with self.assertRaises(Exception):
            close_receipt(oversized, Path(tempfile.mkdtemp()) / "receipts")

    def test_privacy_duplicate_deep_and_oversized_inputs_fail(self):
        private = json.loads(json.dumps(self.payloads["accepted"]))
        private["acceptance_checks"][0]["evidence_refs"] = ["prompt"]
        private["prompt"] = "secret"
        private["receipt_id"] = "mr1-" + hashlib.sha256(_canonical({k: v for k, v in private.items() if k != "receipt_id"})).hexdigest()
        self.assertFalse(validate_receipt(private)["ok"])
        nested = json.loads(json.dumps(self.payloads["accepted"]))
        nested["acceptance_checks"][0]["tool_output"] = "redacted"
        nested["receipt_id"] = "mr1-" + hashlib.sha256(_canonical({k: v for k, v in nested.items() if k != "receipt_id"})).hexdigest()
        self.assertEqual(validate_receipt(nested), {"ok": False, "error": "forbidden_privacy_key"})
        credential = json.loads(json.dumps(self.payloads["accepted"]))
        credential["acceptance_checks"][0]["evidence_refs"] = ["sk-abcdefghijklmnop"]
        credential["receipt_id"] = "mr1-" + hashlib.sha256(_canonical({k: v for k, v in credential.items() if k != "receipt_id"})).hexdigest()
        self.assertEqual(validate_receipt(credential), {"ok": False, "error": "credential_like_value"})
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for raw in (
            '{"schema_version":1,"schema_version":1}',
            "{" + "\"a\":{" * 10000 + "null" + "}" * 10000,
            "x" * (MAX_INPUT_BYTES + 1),
        ):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "input.json"
                path.write_text(raw)
                command = [sys.executable, "scripts/receipt_tool.py", "close", "--input", str(path), "--receipts-dir", str(Path(directory) / "receipts")]
                completed = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True)
                self.assertNotEqual(completed.returncode, 0)

    def test_symlink_input_and_output_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.json"
            source.write_text(json.dumps(self.payloads["accepted"]))
            link = root / "input-link.json"
            os.symlink(source, link)
            with self.assertRaises(Exception):
                from scripts.receipt_tool import _read_input
                _read_input(link)
            receipts = root / "receipts"
            receipts.mkdir(mode=0o700)
            outside = root / "outside"
            outside.write_text("x")
            receipt_id = "mr1-" + hashlib.sha256(_canonical(self.payloads["accepted"])).hexdigest()
            os.symlink(outside, receipts / (receipt_id + ".json"))
            with self.assertRaises(Exception):
                close_receipt(self.payloads["accepted"], receipts)

    def test_summary_accepted_numerator_and_unknown_then_known_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            receipts = Path(directory) / "receipts"
            close_receipt(self.payloads["accepted"], receipts)
            close_receipt(self.payloads["rejected"], receipts)
            unknown = summarize(receipts)
            self.assertEqual(unknown["accepted_numerator_observed"], 1)
            self.assertEqual(unknown["usage"]["coverage"], "unknown")
            self.assertEqual(unknown["receipt_coverage_reason"], "no_start_registry")
            complete_receipts = Path(directory) / "complete"
            complete_a = dict(self.payloads["accepted"])
            complete_a["usage"] = {"coverage": "complete-full-workflow", "provenance": "usage_reporter", "total_tokens": 10, "weighted_usage": 2.0, "source_refs": ["usage:1"], "rate_card_version": "rate-card.v1"}
            complete_r = dict(self.payloads["rejected"])
            complete_r["family"] = complete_a["family"]
            complete_r["size_risk_band"] = complete_a["size_risk_band"]
            complete_r["usage"] = {"coverage": "complete-full-workflow", "provenance": "usage_reporter", "total_tokens": 20, "weighted_usage": 3.0, "source_refs": ["usage:2"], "rate_card_version": "rate-card.v1"}
            close_receipt(complete_a, complete_receipts)
            close_receipt(complete_r, complete_receipts)
            known = summarize(complete_receipts)
            self.assertEqual(known["usage"]["total_weighted_usage"], 5.0)
            self.assertEqual(known["usage"]["verified_outcomes_per_weighted_usage"], 0.2)

            mixed = Path(directory) / "mixed"
            mixed_a = dict(complete_a)
            mixed_a["family"] = "routing"
            mixed_r = dict(complete_r)
            mixed_r["family"] = "receipts"
            close_receipt(mixed_a, mixed)
            close_receipt(mixed_r, mixed)
            mixed_summary = summarize(mixed)
            self.assertEqual(mixed_summary["usage"]["status"], "unknown")
            self.assertIsNone(mixed_summary["usage"]["verified_outcomes_per_weighted_usage"])
            self.assertEqual(mixed_summary["usage"]["reason"], "multiple_incomparable_cohorts")
            self.assertEqual(len(mixed_summary["usage"]["cohorts"]), 2)

    def test_usage_unknown_never_becomes_zero(self):
        value = dict(self.payloads["accepted"])
        value["usage"] = {"coverage": "unknown", "provenance": "usage_reporter", "total_tokens": 0, "weighted_usage": 0.0, "source_refs": [], "rate_card_version": "rate-card.v1"}
        value["receipt_id"] = "mr1-" + hashlib.sha256(_canonical({k: v for k, v in value.items() if k != "receipt_id"})).hexdigest()
        self.assertFalse(validate_receipt(value)["ok"])

    def test_validator_and_cli_outputs_are_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            receipts = Path(directory) / "receipts"
            close_receipt(self.payloads["accepted"], receipts)
            report = validate_paths([], receipts)
            rendered = json.dumps(report)
            self.assertNotIn(str(receipts), rendered)
            command = [sys.executable, "scripts/receipt_tool.py", "summarize", "--receipts-dir", str(receipts), "--format", "json"]
            completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0)
            self.assertNotIn(str(receipts), completed.stdout)


if __name__ == "__main__":
    unittest.main()
