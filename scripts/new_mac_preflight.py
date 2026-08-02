#!/usr/bin/env python3
"""Prepare a fresh macOS host for the unmeasured M4 installation smoke.

This wrapper is deliberately narrower than the normal installer. It verifies a
clean trusted checkout, checks the frozen pilot plan, and delegates environment
creation to ``pilot_tool``. It never authenticates, launches a model, copies
state, or registers a measured start.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from scripts import pilot_tool
except ImportError:  # pragma: no cover - direct script execution
    import pilot_tool  # type: ignore[no-redef]


SCHEMA_VERSION = 1
DEFAULT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PROJECT = "codex-sol-luna-orchestration-kit"
EXPECTED_REPOSITORY = "github.com/msinclair25/codex-sol-luna-orchestration-kit"
MIN_PYTHON = (3, 11)
SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .+_()/:-]{0,159}$")


class PreflightError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _run(command: Sequence[str], cwd: Path, *, allow_empty: bool = False) -> str:
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreflightError("command_failed") from exc
    if result.returncode != 0:
        raise PreflightError("command_failed")
    value = result.stdout.strip()
    if (not value and not allow_empty) or "\x00" in value or len(value) > 4096:
        raise PreflightError("command_output_invalid")
    return value


def _version(binary: str, repo: Path) -> str:
    if shutil.which(binary) is None:
        raise PreflightError(f"{binary}_missing")
    value = _run((binary, "--version"), repo).splitlines()[0].strip()
    if SAFE_VERSION.fullmatch(value) is None:
        raise PreflightError(f"{binary}_version_invalid")
    return value


def _canonical_repository(value: str) -> Optional[str]:
    patterns = (
        r"https://github\.com/msinclair25/codex-sol-luna-orchestration-kit(?:\.git)?/?",
        r"ssh://git@github\.com/msinclair25/codex-sol-luna-orchestration-kit(?:\.git)?/?",
        r"git@github\.com:msinclair25/codex-sol-luna-orchestration-kit(?:\.git)?",
    )
    return EXPECTED_REPOSITORY if any(re.fullmatch(pattern, value) for pattern in patterns) else None


def _repository_facts(repo: Path) -> Dict[str, Any]:
    if not repo.is_dir() or repo.is_symlink():
        raise PreflightError("repository_missing")
    top = Path(_run(("git", "rev-parse", "--show-toplevel"), repo)).resolve()
    if top != repo.resolve():
        raise PreflightError("repository_root_mismatch")
    origin = _canonical_repository(_run(("git", "remote", "get-url", "origin"), repo))
    if origin is None:
        raise PreflightError("repository_origin_mismatch")
    status = _run(("git", "status", "--porcelain=v1", "--untracked-files=all"), repo, allow_empty=True)
    if status:
        raise PreflightError("repository_not_clean")
    head = _run(("git", "rev-parse", "HEAD"), repo)
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise PreflightError("repository_head_invalid")
    branch = _run(("git", "branch", "--show-current"), repo, allow_empty=True)
    if not branch:
        branch = "detached"
    if re.fullmatch(r"[A-Za-z0-9._/-]{1,160}", branch) is None:
        raise PreflightError("repository_branch_invalid")
    return {"origin": origin, "head": head, "branch": branch, "clean": True}


def _ensure_no_measured_starts(repo: Path) -> None:
    starts = repo / ".sol-luna" / "starts"
    if starts.is_symlink() or (starts.exists() and not starts.is_dir()):
        raise PreflightError("measured_start_registry_unsafe")
    if starts.is_dir():
        try:
            if any(starts.iterdir()):
                raise PreflightError("measured_starts_present")
        except OSError as exc:
            raise PreflightError("measured_start_registry_unreadable") from exc


def prepare(repo_root: Path | str, pilot_home: Path | str, *, apply: bool) -> Dict[str, Any]:
    repo = Path(repo_root).expanduser().resolve()
    if platform.system() != "Darwin":
        raise PreflightError("macos_required")
    if sys.version_info < MIN_PYTHON:
        raise PreflightError("python_3_11_required")

    git_version = _version("git", repo)
    codex_version = _version("codex", repo)
    repository = _repository_facts(repo)
    _ensure_no_measured_starts(repo)

    plan_path = repo / "config" / "m4-pilot.v1.json"
    plan = pilot_tool.verify_plan(plan_path, repo)
    dry_run = pilot_tool.setup_environments(plan_path, repo, pilot_home, apply=False)
    if not dry_run.get("ok"):
        raise PreflightError("environment_dry_run_failed")

    applied: Optional[Dict[str, Any]] = None
    environment: Optional[Dict[str, Any]] = None
    pilot_status: Optional[Dict[str, Any]] = None
    if apply:
        applied = pilot_tool.setup_environments(plan_path, repo, pilot_home, apply=True)
        environment = pilot_tool.verify_environments(plan_path, repo, pilot_home)
        pilot_status = pilot_tool.summarize_pilot(
            plan_path,
            repo,
            repo / ".sol-luna" / "starts",
            repo / ".sol-luna" / "receipts",
            pilot_home,
        )
        if not environment.get("ok"):
            raise PreflightError("environment_verification_failed")
        if pilot_status.get("registered_count") != 0 or pilot_status.get("terminal_count") != 0:
            raise PreflightError("measured_starts_present")
        if pilot_status.get("state") != "ready" or not pilot_status.get("next_slot_eligible"):
            raise PreflightError("pilot_not_ready")

    architecture = platform.machine() or "unknown"
    if SAFE_VERSION.fullmatch(architecture) is None:
        architecture = "unknown"
    setup_result = applied if applied is not None else dry_run
    status = (
        "ready-for-separate-login-and-unmeasured-smoke"
        if apply
        else "dry-run-ready"
    )
    next_actions: List[str] = (
        ["apply-environment-setup"]
        if not apply
        else [
            "authenticate-control-separately",
            "authenticate-dynamic-separately",
            "confirm-before-two-unmeasured-smokes",
        ]
    )
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "host": {
            "platform": "macOS",
            "architecture": architecture,
            "python_version": platform.python_version(),
            "git_version": git_version,
            "codex_version": codex_version,
        },
        "repository": repository,
        "pilot": {
            "project_id": EXPECTED_PROJECT,
            "plan_id": plan["plan_id"],
            "plan_sha256": plan["plan_sha256"],
            "pilot_home_name": Path(pilot_home).expanduser().name,
            "arm_codex_homes": ["control/.codex", "dynamic/.codex"],
            "setup_status": setup_result["status"],
            "write_count": setup_result["write_count"],
            "environment": environment,
            "registered_count": 0,
            "terminal_count": 0,
        },
        "safety": {
            "ordinary_codex_home_targeted": False,
            "global_installer_run": False,
            "credentials_copied": False,
            "sessions_copied": False,
            "authentication_attempts_by_preflight": 0,
            "model_runs_started_by_preflight": 0,
            "measured_starts_registered_by_preflight": 0,
            "automatic_promotion": False,
        },
        "next_actions": next_actions,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--pilot-home", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = prepare(args.root, args.pilot_home, apply=args.apply)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (
        PreflightError,
        pilot_tool.PilotError,
        OSError,
        UnicodeError,
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        code = exc.code if isinstance(exc, (PreflightError, pilot_tool.PilotError)) else "preflight_failed"
        print(json.dumps({"ok": False, "errors": [code]}, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
