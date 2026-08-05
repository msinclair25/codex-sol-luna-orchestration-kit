import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "sol-luna-orchestration-kit"
GUARD = PLUGIN / "scripts" / "pre_tool_use_guard.py"
EVIDENCE_FIELDS = [
    "status",
    "files_or_surfaces",
    "checks",
    "findings",
    "risks",
    "confidence",
    "recommendation",
]


def _envelope() -> dict:
    return {
        "schema_version": 1,
        "routing_request": {
            "kind": "worker",
            "profile": "fast",
            "fork_turns": "none",
            "task_class": "substantial_implementation",
            "benefit_code": "isolated_large_implementation",
            "substantive_work": {"estimated_minutes": 30, "affected_files": 3, "distinct_surfaces": 2, "independent_checks": 1},
            "work_band": "substantial",
            "risk_domains": [],
            "separate": True,
            "provable": True,
            "isolated": True,
            "tier_appropriate": True,
            "lane_count": 1,
            "ownership": {"m5_guard": ["src/m5_guard.py"]},
        },
        "assignment": {
            "lane_id": "m5_guard",
            "outcome": "Implement one bounded guard change.",
            "relevant_inputs": ["docs/guard-contract.md"],
            "scope_or_owned_files": ["src/m5_guard.py"],
            "constraints": ["Do not edit outside the owned file."],
            "acceptance_checks": ["Run the named unit test."],
            "expected_evidence": list(EVIDENCE_FIELDS),
            "risk_boundary": "No network, secrets, commits, or destructive actions.",
            "deadline": "Complete within one bounded agent turn.",
        },
    }


def _event(envelope: dict | str | None = None, cwd: Path = ROOT) -> dict:
    message = json.dumps(_envelope() if envelope is None else envelope, separators=(",", ":"))
    return {
        "session_id": "redacted-test-session",
        "turn_id": "redacted-test-turn",
        "transcript_path": None,
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "permission_mode": "default",
        "model": "gpt-5.6-sol",
        "tool_name": "Agent",
        "tool_use_id": "redacted-test-call",
        "tool_input": {
            "agent_type": "luna_worker_fast",
            "fork_turns": "none",
            "message": message,
            "task_name": "m5_guard",
        },
    }


def _run_guard(event: dict, guard: Path = GUARD) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(guard)],
        cwd=ROOT,
        input=json.dumps(event),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _deny_code(result: subprocess.CompletedProcess[str]) -> str | None:
    if not result.stdout:
        return None
    payload = json.loads(result.stdout)
    return payload["hookSpecificOutput"]["permissionDecisionReason"]


class M5PluginTests(unittest.TestCase):
    def test_manifest_and_default_hook_discovery_are_valid(self):
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["name"], PLUGIN.name)
        self.assertEqual(manifest["version"], "0.6.1")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertNotIn("hooks", manifest)
        self.assertIsInstance(manifest["interface"]["defaultPrompt"], list)
        self.assertLessEqual(len(manifest["interface"]["defaultPrompt"]), 3)

        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
        matcher = hooks["hooks"]["PreToolUse"][0]
        self.assertEqual(matcher["matcher"], "^Agent$")
        command = matcher["hooks"][0]["command"]
        self.assertIn("$PLUGIN_ROOT/scripts/pre_tool_use_guard.py", command)
        self.assertTrue((PLUGIN / "skills" / "sol-luna-orchestration" / "SKILL.md").is_file())
        self.assertTrue((PLUGIN / "skills" / "sol-luna-setup" / "SKILL.md").is_file())
        self.assertTrue((PLUGIN / "skills" / "sol-luna-status" / "SKILL.md").is_file())
        setup = (PLUGIN / "skills" / "sol-luna-setup" / "SKILL.md").read_text()
        self.assertIn("without manually operating the installer", setup)
        self.assertIn("--dry-run --update", setup)
        self.assertIn("Never pass `--approve-conflicts`", setup)
        self.assertIn("codex plugin marketplace upgrade sol-luna", setup)
        self.assertIn("codex plugin marketplace list --json", setup)
        self.assertIn("$sol-luna-setup Continue.", setup)
        self.assertIn("--mark-update-pending", setup)
        self.assertIn("Do not require an intermediate restart", setup)
        orchestration = (PLUGIN / "skills" / "sol-luna-orchestration" / "SKILL.md").read_text()
        status = (PLUGIN / "skills" / "sol-luna-status" / "SKILL.md").read_text()
        self.assertIn(".sol-luna-install-state.json", orchestration)
        self.assertIn("Native transport fallback", orchestration)
        self.assertIn("May I create one visible", orchestration)
        self.assertIn("do not persist", orchestration)
        self.assertIn("canonical root and the routing evaluator's canonical", orchestration)
        self.assertIn("checkout root and require exact equality", orchestration)
        self.assertIn("missing or mismatched root consumes", orchestration)
        self.assertIn("`project_context` object", orchestration)
        self.assertIn("`project_root_verified: true`", orchestration)
        self.assertIn("automatically reuses the profile", status)
        self.assertIn("routine-delegation-record.v2", orchestration)
        self.assertIn("guaranteed runtime lifecycle hook", orchestration)
        self.assertIn("canonical active project root", orchestration)
        self.assertIn("Read-only settings overview", setup)
        self.assertIn("install-state-v3", setup)
        self.assertIn("--workspace-root", status)

        marketplace = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
        self.assertEqual(marketplace["name"], "sol-luna")
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], PLUGIN.name)
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/sol-luna-orchestration-kit"})
        self.assertEqual(entry["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"})

    def test_bundled_policy_and_status_assets_match_canonical_sources(self):
        direct_pairs = [
            (ROOT / "AGENTS.md", PLUGIN / "AGENTS.md"),
            (ROOT / "AGENTS.override.md", PLUGIN / "AGENTS.override.md"),
            (ROOT / "config-snippet.toml", PLUGIN / "config-snippet.toml"),
        ]
        for directory in ("agents", "config", "control-bundles", "evidence", "pilot-plans", "profiles", "schemas"):
            for source in sorted((ROOT / directory).rglob("*")):
                if source.is_file() and "__pycache__" not in source.parts:
                    direct_pairs.append((source, PLUGIN / source.relative_to(ROOT)))
        for name in ("install.py", "lifecycle.py", "pilot_tool.py", "platform_fs.py", "receipt_tool.py", "routing_policy.py", "setup.py", "usage_report.py", "verify_control_bundle.py", "windows_setup.ps1"):
            direct_pairs.append((ROOT / "scripts" / name, PLUGIN / "scripts" / name))
        for skill_name in ("sol-luna-setup", "sol-luna-status"):
            canonical_skill = ROOT / ".agents" / "skills" / skill_name
            for source in sorted(canonical_skill.rglob("*")):
                if source.is_file() and "__pycache__" not in source.parts:
                    destination = PLUGIN / "skills" / skill_name / source.relative_to(canonical_skill)
                    direct_pairs.append((source, destination))
        for source, destination in direct_pairs:
            self.assertTrue(destination.is_file(), destination)
            self.assertEqual(source.read_bytes(), destination.read_bytes(), destination)
            self.assertEqual(
                stat.S_IMODE(source.stat().st_mode),
                stat.S_IMODE(destination.stat().st_mode),
                destination,
            )

    def test_release_sync_check_is_clean_and_version_coherent(self):
        result = subprocess.run(
            [sys.executable, "scripts/sync_plugin.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["mismatches"], [])
        self.assertEqual(report["version"], "0.6.1")

    def test_bundled_setup_installer_applies_standard_profile(self):
        previous_dont_write_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec = importlib.util.spec_from_file_location("bundled_sol_luna_install", PLUGIN / "scripts" / "install.py")
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary) / "home"
                home.mkdir()
                codex_home = home / ".codex"
                plan = module.install(
                    PLUGIN,
                    codex_home,
                    home,
                    apply=True,
                    with_usage=False,
                    luna_tier="standard",
                )
                self.assertTrue(plan["verification"]["ok"])
                self.assertTrue((codex_home / "agents" / "luna_worker_standard.toml").is_file())
                role = (codex_home / "agents" / "luna_worker_standard.toml").read_text()
                self.assertNotIn("service_tier", role)
        finally:
            sys.dont_write_bytecode = previous_dont_write_bytecode

    def test_bundled_routing_contract_verifies(self):
        result = subprocess.run(
            [sys.executable, str(PLUGIN / "scripts" / "routing_policy.py"), "verify", "--root", str(PLUGIN), "--format", "json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_bundled_status_skill_runs_against_plugin_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            empty = Path(temporary)
            (empty / "receipts").mkdir()
            (empty / "sessions").mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(PLUGIN / "skills" / "sol-luna-status" / "scripts" / "sol_luna_status.py"),
                    "--root", str(PLUGIN),
                    "--receipts-dir", str(empty / "receipts"),
                    "--session-root", str(empty / "sessions"),
                    "--format", "json",
                ],
                cwd=PLUGIN,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["pilot"]["state"], "retired-non-retryable")
        self.assertIsNone(report["pilot"]["next_slot"])

    def test_valid_context_free_spawn_is_allowed_unchanged(self):
        result = _run_guard(_event())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_exact_lane_scoped_fallback_authorization_is_optional_and_guarded(self):
        authorized = _envelope()
        authorized["fallback_authorization"] = {
            "authorized": True,
            "target": "codex_app_task",
            "scope": "this_lane_once",
            "lane_id": "m5_guard",
            "max_attempts": 1,
            "current_checkout": True,
        }
        result = _run_guard(_event(authorized))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

        for name, mutate in (
            ("lane", lambda value: value.update(lane_id="different_lane")),
            ("attempts", lambda value: value.update(max_attempts=2)),
            ("bool_attempts", lambda value: value.update(max_attempts=True)),
            ("checkout", lambda value: value.update(current_checkout=False)),
            ("extra", lambda value: value.update(persist=True)),
        ):
            with self.subTest(name=name):
                envelope = _envelope()
                authorization = dict(authorized["fallback_authorization"])
                mutate(authorization)
                envelope["fallback_authorization"] = authorization
                code = _deny_code(_run_guard(_event(envelope)))
                self.assertIn(code, {"sol-luna-guard:fallback_authorization_shape", "sol-luna-guard:fallback_authorization_invalid"})

    def test_standard_profile_spawn_is_allowed_with_standard_role(self):
        envelope = _envelope()
        envelope["routing_request"]["profile"] = "standard"
        event = _event(envelope)
        event["tool_input"]["agent_type"] = "luna_worker_standard"
        result = _run_guard(event)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_history_fork_role_and_ownership_mismatches_are_denied(self):
        history = _event()
        history["tool_input"]["fork_turns"] = "all"
        self.assertEqual(_deny_code(_run_guard(history)), "sol-luna-guard:history_fork_denied")

        role = _event()
        role["tool_input"]["agent_type"] = "luna_scout_fast"
        self.assertEqual(_deny_code(_run_guard(role)), "sol-luna-guard:role_mismatch")

        ownership_envelope = _envelope()
        ownership_envelope["assignment"]["scope_or_owned_files"] = ["src/other.py"]
        self.assertEqual(
            _deny_code(_run_guard(_event(ownership_envelope))),
            "sol-luna-guard:assignment_ownership_mismatch",
        )

    def test_failed_split_and_incomplete_total_lane_map_are_denied(self):
        split = _envelope()
        split["routing_request"]["provable"] = False
        self.assertEqual(_deny_code(_run_guard(_event(split))), "sol-luna-guard:route_split_provable")

        wave = _envelope()
        wave["routing_request"]["lane_count"] = 2
        wave["routing_request"]["total_lane_count"] = 2
        self.assertEqual(_deny_code(_run_guard(_event(wave))), "sol-luna-guard:route_unsupported_concurrency")

    def test_complete_total_lane_ownership_map_is_allowed(self):
        envelope = _envelope()
        envelope["routing_request"].update({
            "lane_count": 2,
            "total_lane_count": 2,
            "ownership": {
                "m5_guard": ["src/m5_guard.py"],
                "m5_review": ["docs/m5-review.md"],
            },
        })
        result = _run_guard(_event(envelope))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_sensitive_or_absolute_relevant_inputs_are_denied(self):
        for path in (".env", "secrets.json", "/absolute/private.txt", "credentials/token.txt"):
            with self.subTest(path=path):
                envelope = _envelope()
                envelope["assignment"]["relevant_inputs"] = [path]
                self.assertEqual(
                    _deny_code(_run_guard(_event(envelope))),
                    "sol-luna-guard:assignment_relevant_inputs_unsafe",
                )

    def test_duplicate_json_and_project_symlink_are_denied(self):
        duplicate = _event()
        duplicate["tool_input"]["message"] = '{"schema_version":1,"schema_version":1}'
        self.assertEqual(_deny_code(_run_guard(duplicate)), "sol-luna-guard:duplicate_json_key")

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            outside = Path(temporary) / "outside"
            project.mkdir()
            outside.mkdir()
            os.symlink(outside, project / "linked")
            envelope = _envelope()
            envelope["routing_request"]["ownership"] = {"m5_guard": ["linked/file.py"]}
            envelope["assignment"]["scope_or_owned_files"] = ["linked/file.py"]
            self.assertEqual(
                _deny_code(_run_guard(_event(envelope, project))),
                "sol-luna-guard:project_ownership_path_unsafe",
            )

    def test_invalid_utf8_hook_input_is_denied_without_process_failure(self):
        result = subprocess.run(
            [sys.executable, str(GUARD)],
            cwd=ROOT,
            input=b"\xff",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecisionReason"],
            "sol-luna-guard:hook_input_encoding",
        )

    def test_casefold_hardlink_and_broad_cwd_aliases_are_denied(self):
        casefold = _envelope()
        casefold["routing_request"].update({
            "lane_count": 2,
            "ownership": {
                "m5_guard": ["src/Foo.py"],
                "second_lane": ["src/foo.py"],
            },
        })
        casefold["assignment"]["scope_or_owned_files"] = ["src/Foo.py"]
        self.assertEqual(
            _deny_code(_run_guard(_event(casefold))),
            "sol-luna-guard:project_ownership_path_unsafe",
        )

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            first = project / "first.py"
            second = project / "second.py"
            first.write_text("pass\n")
            os.link(first, second)
            hardlink = _envelope()
            hardlink["routing_request"].update({
                "lane_count": 2,
                "ownership": {
                    "m5_guard": ["first.py"],
                    "second_lane": ["second.py"],
                },
            })
            hardlink["assignment"]["scope_or_owned_files"] = ["first.py"]
            self.assertEqual(
                _deny_code(_run_guard(_event(hardlink, project))),
                "sol-luna-guard:project_ownership_path_unsafe",
            )

        self.assertEqual(_deny_code(_run_guard(_event(cwd=Path("/")))), "sol-luna-guard:cwd_too_broad")

    def test_bundled_policy_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy_root = Path(temporary) / PLUGIN.name
            shutil.copytree(PLUGIN, copy_root)
            role = copy_root / "agents" / "v0.4" / "luna_worker_fast.toml"
            role.write_text(role.read_text() + "\n# drift\n")
            result = _run_guard(_event(), copy_root / "scripts" / "pre_tool_use_guard.py")
            self.assertEqual(_deny_code(result), "sol-luna-guard:route_runtime_drift")

    def test_missing_policy_module_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy_root = Path(temporary) / PLUGIN.name
            shutil.copytree(PLUGIN, copy_root)
            (copy_root / "scripts" / "routing_policy.py").unlink()
            result = _run_guard(_event(), copy_root / "scripts" / "pre_tool_use_guard.py")
            self.assertEqual(_deny_code(result), "sol-luna-guard:policy_module_unavailable")

    def test_documentation_states_partial_enforcement_and_declined_features(self):
        text = (ROOT / "docs" / "M5_PLUGIN_GUARDRAILS.md").read_text()
        for phrase in (
            "partial admission guard",
            "Not universally enforceable",
            "Luna Standard experiment",
            "Dashboard",
            "Sites or hosted surface",
            "no routing promotion or savings claim",
            "cannot start or times out",
            "Cross-call consistency",
            "time-of-check/time-of-use",
            "Directory ownership",
        ):
            self.assertIn(phrase, text)

    def test_primary_onboarding_is_one_prompt_and_one_final_restart(self):
        readme = (ROOT / "README.md").read_text()
        installing = (ROOT / "docs" / "INSTALLING_AND_UPDATING.md").read_text()
        for text in (readme, installing):
            compact = " ".join(text.split())
            self.assertIn("Install and fully configure the Sol/Luna Orchestration Kit", text)
            self.assertIn("codex plugin list --json", text)
            self.assertIn("source.path", text)
            self.assertIn("one final restart", compact)
            self.assertIn("no intermediate restart", compact)
        self.assertIn("$sol-luna-setup Continue.", installing)
        self.assertIn("resumable", installing)

        lines = readme.splitlines()
        self.assertLessEqual(len(lines), 400)
        quick_start = next(index for index, line in enumerate(lines, 1) if line == "## Quick Start")
        self.assertLessEqual(quick_start, 40)
        self.assertLess(readme.index("| **Fast**"), readme.index("Install and fully configure"))
        prompt = readme.split("```text", 1)[1].split("```", 1)[0].strip().splitlines()
        self.assertLessEqual(len(prompt), 6)
        for label in ("Setup", "Status", "Update", "Continue", "Switch", "Verify", "Settings"):
            self.assertIn(f"| {label} |", readme)
        self.assertIn("Healthy full install", readme)
        self.assertIn("Not enough comparable evidence yet.", readme)
        self.assertIn("Workflow-only alternative", readme)
        self.assertIn("Technical history", readme)
        visual = (ROOT / "assets" / "sol-luna-orchestration-system-v0.6.svg").read_text()
        self.assertIn("LUNA · FAST", visual)
        self.assertIn("LUNA · STANDARD", visual)
        self.assertIn("#f6c85f", visual)
        self.assertIn("#41d8ee", visual)
        self.assertIn("#63e6a6", visual)

    def test_settings_guidance_is_read_only_and_maintainer_help_is_explicit(self):
        setup = (ROOT / ".agents" / "skills" / "sol-luna-setup" / "SKILL.md").read_text()
        settings = setup.split("## Read-only settings overview", 1)[1].split("## Update the plugin package", 1)[0]
        for phrase in (
            "workflow-only or full-role mode",
            "plugin/bundle version",
            "managed surface categories",
            "current project metric collection",
            "available conversational actions",
        ):
            self.assertIn(phrase, settings)
        self.assertIn("never writes files", settings)
        self.assertNotIn("--apply", settings)
        self.assertNotIn("SHA-256", settings)

        install_help = subprocess.run(
            [sys.executable, "scripts/install.py", "--help"],
            cwd=ROOT, text=True, capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        status_help = subprocess.run(
            [sys.executable, str(ROOT / ".agents/skills/sol-luna-status/scripts/sol_luna_status.py"), "--help"],
            cwd=ROOT, text=True, capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertIn("Normal users ask the Sol/Luna setup skill", install_help.stdout)
        self.assertIn("maintainer", status_help.stdout)
        self.assertIn("project-local", status_help.stdout)


if __name__ == "__main__":
    unittest.main()
