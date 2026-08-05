import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.verify_control_bundle import verify


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "control-bundles" / "all-max-v1"


class ControlBundleTests(unittest.TestCase):
    def _copy_bundle(self):
        temporary = tempfile.TemporaryDirectory()
        copy = Path(temporary.name) / "bundle"
        shutil.copytree(BUNDLE, copy)
        return temporary, copy

    def _rewrite_entry_hash(self, bundle, relative):
        path = bundle / "files" / relative
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        for entry in manifest["files"]:
            if entry["path"] == relative:
                entry["sha256"] = digest
                entry["size"] = path.stat().st_size
                break
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    def test_pristine_bundle_is_valid_and_dynamic_root_is_rejected(self):
        report = verify(BUNDLE)
        self.assertTrue(report["ok"])
        self.assertTrue(report["bundle_match"])
        self.assertFalse(report["active_root_checked"])
        self.assertEqual(report["entry_count"], 8)
        self.assertEqual(report["errors"], [])
        active_report = verify(BUNDLE, ROOT)
        self.assertFalse(active_report["ok"])
        self.assertTrue(active_report["bundle_match"])
        self.assertTrue(active_report["active_root_checked"])
        self.assertFalse(active_report["active_root_match"])
        self.assertGreater(active_report["mismatches"]["active"], 0)
        card = json.loads((ROOT / "config" / "rate-card.v1.json").read_text())
        self.assertEqual(card["unit"], "estimated-weighted-tokens")
        self.assertEqual(
            set(card["weights"]["reasoning"]),
            {"default", "medium", "high", "max", "xhigh"},
        )
        self.assertTrue(all(value == 1.0 for value in card["weights"]["reasoning"].values()))

    def test_active_drift_is_nonzero_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory)
            for entry in json.loads((BUNDLE / "manifest.json").read_text())["files"]:
                source = BUNDLE / "files" / entry["path"]
                destination = active / entry["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            drift = active / "agents" / "luna_max_fast.toml"
            drift.write_bytes(drift.read_bytes() + b"\n# drift\n")
            report = verify(BUNDLE, active)
        self.assertFalse(report["ok"])
        self.assertFalse(report["active_root_match"])
        self.assertGreater(report["mismatches"]["active"], 0)

    def test_bundle_tamper_is_detected(self):
        temporary, copy = self._copy_bundle()
        try:
            target = copy / "files" / "AGENTS.md"
            target.write_bytes(target.read_bytes() + b"\ntamper\n")
            report = verify(copy)
        finally:
            temporary.cleanup()
        self.assertFalse(report["ok"])
        self.assertGreater(report["mismatches"]["bundle"], 0)

    def test_unsafe_manifest_path_is_rejected_without_echoing_it(self):
        temporary, copy = self._copy_bundle()
        try:
            manifest_path = copy / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["files"][0]["path"] = "../unsafe-injected-path"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            report = verify(copy)
            rendered = json.dumps(report, sort_keys=True)
        finally:
            temporary.cleanup()
        self.assertFalse(report["ok"])
        self.assertGreater(report["mismatches"]["unsafe_paths"], 0)
        self.assertIn("unsafe_manifest_path", report["errors"])
        self.assertNotIn("unsafe-injected-path", rendered)

    def test_unknown_safe_and_overlong_manifest_paths_are_not_echoed(self):
        for injected_path in ("unknown-safe.txt", "a" * 161 + ".txt"):
            temporary, copy = self._copy_bundle()
            try:
                manifest_path = copy / "manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["files"].append(
                    {
                        "path": injected_path,
                        "sha256": "0" * 64,
                        "size": 0,
                    }
                )
                manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
                report = verify(copy)
                rendered = json.dumps(report, sort_keys=True)
            finally:
                temporary.cleanup()
            self.assertFalse(report["ok"])
            self.assertNotIn(injected_path, rendered)
            expected_error = "unsafe_manifest_path" if len(injected_path) > 160 else "unexpected_manifest_entry"
            self.assertIn(expected_error, report["errors"])

    def test_authority_and_source_provenance_are_exact(self):
        mutations = (
            ("authority", {"runtime": "active-root", "bundle_role": "review-and-restore-input", "automatic_restore": True}),
            ("source", {"commit": "0" * 40, "commit_sha": "0" * 40, "dirty": True, "dirty_paths": []}),
        )
        for key, value in mutations:
            temporary, copy = self._copy_bundle()
            try:
                manifest_path = copy / "manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest[key] = value
                manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
                report = verify(copy)
            finally:
                temporary.cleanup()
            self.assertFalse(report["ok"])
            self.assertTrue(any(error in report["errors"] for error in ("invalid_authority", "invalid_source_commit")))

    def test_parser_metadata_and_hash_are_required(self):
        for field, value in (("schema_version", 99), ("sha256", "f" * 64)):
            temporary, copy = self._copy_bundle()
            try:
                manifest_path = copy / "manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["parser"][field] = value
                manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
                report = verify(copy)
            finally:
                temporary.cleanup()
            self.assertFalse(report["ok"])
            self.assertTrue(
                any(error in report["errors"] for error in ("invalid_parser_metadata", "parser_hash_mismatch"))
            )

    def test_symlinked_bundle_root_and_manifest_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root_link = root / "bundle-link"
            os.symlink(BUNDLE, root_link)
            root_report = verify(root_link)
            self.assertFalse(root_report["ok"])
            self.assertIn("bundle_root_unreadable", root_report["errors"])

            manifest_copy = root / "bundle-manifest-link"
            shutil.copytree(BUNDLE, manifest_copy)
            (manifest_copy / "manifest.json").unlink()
            os.symlink(BUNDLE / "manifest.json", manifest_copy / "manifest.json")
            manifest_report = verify(manifest_copy)
            self.assertFalse(manifest_report["ok"])
            self.assertIn("manifest_unreadable", manifest_report["errors"])

    @unittest.skipIf(os.name == "nt", "covered by the native Windows junction integration test")
    def test_nested_symlink_is_counted_without_traversing_outside_bundle(self):
        temporary, copy = self._copy_bundle()
        try:
            outside = Path(temporary.name) / "outside"
            outside.mkdir()
            (outside / "borrowed.txt").write_text("outside", encoding="utf-8")
            (copy / "files" / "nested-link").symlink_to(outside, target_is_directory=True)
            report = verify(copy)
        finally:
            temporary.cleanup()
        self.assertFalse(report["ok"])
        self.assertEqual(report["mismatches"]["unexpected_files"], 1)
        self.assertIn("unexpected_bundle_file", report["errors"])

    def test_manifest_json_is_bounded_strict_and_fail_closed(self):
        for raw in (
            '{"schema_version":1,"schema_version":1}',
            "[" * 10000 + "]" * 10000,
            "x" * (64 * 1024 + 1),
        ):
            temporary, copy = self._copy_bundle()
            try:
                (copy / "manifest.json").write_text(raw)
                report = verify(copy)
                self.assertFalse(report["ok"])
                self.assertIn("manifest_unreadable", report["errors"])
            finally:
                temporary.cleanup()

    def test_rate_card_schema_rejects_missing_source_scope_and_nonfinite_values(self):
        mutations = (
            lambda card: card["provenance"].update(source_url="https://evil.example/card"),
            lambda card: card["provenance"].update(source_type="local-note"),
            lambda card: card["atomic_input"].update(scope="single-turn"),
            lambda card: card["weights"]["model"].update(default=float("nan")),
            lambda card: card["weights"]["service_tier"].pop("priority"),
            lambda card: card.update(stale_after="2026-07-01T00:00:00Z"),
        )
        for mutate in mutations:
            temporary, copy = self._copy_bundle()
            try:
                card_path = copy / "files" / "config" / "rate-card.v1.json"
                card = json.loads(card_path.read_text())
                mutate(card)
                card_path.write_text(json.dumps(card, indent=2) + "\n")
                self._rewrite_entry_hash(copy, "config/rate-card.v1.json")
                report = verify(copy)
            finally:
                temporary.cleanup()
            self.assertFalse(report["ok"])
            self.assertIn("rate_card_contract", report["errors"])

    def test_rate_card_rejects_huge_integer_without_traceback(self):
        temporary, copy = self._copy_bundle()
        try:
            card_path = copy / "files" / "config" / "rate-card.v1.json"
            card = json.loads(card_path.read_text())
            card["weights"]["model"]["default"] = 10**1000
            card_path.write_text(json.dumps(card, indent=2) + "\n")
            self._rewrite_entry_hash(copy, "config/rate-card.v1.json")
            first = verify(copy)
            second = verify(copy)
        finally:
            temporary.cleanup()
        self.assertFalse(first["ok"])
        self.assertEqual(first, second)
        self.assertIn("rate_card_contract", first["errors"])

    def test_role_identity_sandbox_and_instructions_are_required(self):
        def empty_instructions(text):
            marker = 'developer_instructions = """'
            start = text.index(marker)
            end = text.index('"""', start + len(marker)) + 3
            return text[:start] + 'developer_instructions = ""' + text[end:]

        mutations = (
            lambda text: text.replace('name = "luna_critic_fast"', 'name = "wrong-role"', 1),
            lambda text: text.replace('sandbox_mode = "read-only"', 'sandbox_mode = "workspace-write"', 1),
            lambda text: text.replace('description = "Read-only adversarial', 'description = ""', 1),
            empty_instructions,
        )
        for mutate in mutations:
            temporary, copy = self._copy_bundle()
            try:
                role_path = copy / "files" / "agents" / "luna_critic_fast.toml"
                role_path.write_text(mutate(role_path.read_text()))
                self._rewrite_entry_hash(copy, "agents/luna_critic_fast.toml")
                report = verify(copy)
            finally:
                temporary.cleanup()
            self.assertFalse(report["ok"])
            self.assertIn("role_contract", report["errors"])

    def test_rate_card_contract_is_checked_even_when_hash_is_rewritten(self):
        temporary, copy = self._copy_bundle()
        try:
            card_path = copy / "files" / "config" / "rate-card.v1.json"
            card = json.loads(card_path.read_text())
            del card["weights"]["reasoning"]["xhigh"]
            card_path.write_text(json.dumps(card, indent=2) + "\n")
            digest = hashlib.sha256(card_path.read_bytes()).hexdigest()
            manifest_path = copy / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            for entry in manifest["files"]:
                if entry["path"] == "config/rate-card.v1.json":
                    entry["sha256"] = digest
                    entry["size"] = card_path.stat().st_size
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            report = verify(copy)
        finally:
            temporary.cleanup()
        self.assertFalse(report["ok"])
        self.assertEqual(report["mismatches"]["bundle"], 0)
        self.assertEqual(report["mismatches"]["rate_card"], 1)
        self.assertIn("rate_card_contract", report["errors"])

    def test_cli_json_is_deterministic_and_markdown_safe(self):
        command = [
            sys.executable,
            "scripts/verify_control_bundle.py",
            "--bundle",
            str(BUNDLE),
            "--format",
            "json",
        ]
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        first = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True)
        second = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(first.stdout, second.stdout)
        report = json.loads(first.stdout)
        self.assertTrue(report["ok"])
        self.assertFalse(report["active_root_checked"])
        self.assertNotIn("\n#", first.stdout)


if __name__ == "__main__":
    unittest.main()
