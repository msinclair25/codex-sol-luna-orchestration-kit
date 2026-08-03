#!/usr/bin/env python3
"""Run one bounded, two-arm Sol/Luna calibration benchmark.

The command verifies the existing M4 window-02 environments, asks before any
quota-consuming call, creates two byte-identical disposable workspaces, runs
the same prompt sequentially with a 15-minute limit per arm, and writes one
privacy-safe comparison receipt. It never touches the ten-slot pilot registry
or promotes a policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import resource
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

try:
    from scripts import pilot_tool, routing_policy, usage_report, verify_control_bundle
except ImportError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import pilot_tool, routing_policy, usage_report, verify_control_bundle


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "m4-benchmark.v1.json"
EXPECTED_ORIGIN = "github.com/msinclair25/codex-sol-luna-orchestration-kit"
EXPECTED_CONFIG_SHA256 = "546858601aaf162ddb144a4b81cdbe293a3ae5ef3084a736393f1275a9ea7c47"
SCHEMA_VERSION = 1
ORIGIN = "unsigned-local-audit"
ARMS = ("all-max-control", "dynamic-v0.2.1")
REQUIRED_ROLES = ("luna_scout_fast", "luna_worker_fast", "luna_tester_fast")
MAX_JSON_BYTES = 256 * 1024
MAX_CAPTURE_BYTES = 64 * 1024 * 1024
MAX_ORACLE_CAPTURE_BYTES = 1024 * 1024
MAX_WORKSPACE_FILES = 128
MAX_WORKSPACE_FILE_BYTES = 2 * 1024 * 1024
MAX_WORKSPACE_BYTES = 8 * 1024 * 1024
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

CONFIG_KEYS = {
    "schema_version", "benchmark_id", "status", "origin", "pilot_plan_path",
    "pilot_plan_sha256", "fixture", "prompt", "oracle", "arms",
    "required_roles", "arm_timeout_seconds", "total_model_timeout_seconds",
    "acceptance_timeout_seconds", "weighted_usage_reduction_target",
    "latency_noninferiority_margin", "automatic_promotion", "directional_only",
}


class BenchmarkError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _strict_json(raw: bytes) -> Any:
    if len(raw) > MAX_JSON_BYTES:
        raise BenchmarkError("json_oversize")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BenchmarkError("duplicate_json_key")
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs_hook,
            parse_constant=lambda _: (_ for _ in ()).throw(BenchmarkError("nonfinite_number")),
        )
    except BenchmarkError:
        raise
    except (UnicodeError, json.JSONDecodeError, MemoryError, RecursionError) as exc:
        raise BenchmarkError("malformed_json") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value or len(value) > 200 or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return value


def _safe_file(root: Path, relative: str, *, max_bytes: int = 512 * 1024) -> tuple[Path, bytes]:
    safe = _safe_relative(relative)
    if safe is None:
        raise BenchmarkError("unsafe_relative_path")
    base = root.resolve()
    path = base.joinpath(*PurePosixPath(safe).parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(base)
        if path.is_symlink() or not resolved.is_file() or resolved.stat().st_size > max_bytes:
            raise BenchmarkError("unsafe_source_file")
        return resolved, resolved.read_bytes()
    except BenchmarkError:
        raise
    except (OSError, ValueError) as exc:
        raise BenchmarkError("unsafe_source_file") from exc


def _validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != CONFIG_KEYS:
        raise BenchmarkError("benchmark_config_shape")
    if value["schema_version"] != SCHEMA_VERSION or value["status"] != "frozen-before-first-run" or value["origin"] != ORIGIN:
        raise BenchmarkError("benchmark_config_header")
    if not isinstance(value["benchmark_id"], str) or not SAFE_ID_RE.fullmatch(value["benchmark_id"]):
        raise BenchmarkError("benchmark_id")
    if _safe_relative(value["pilot_plan_path"]) is None or not HASH_RE.fullmatch(str(value["pilot_plan_sha256"])):
        raise BenchmarkError("pilot_plan_reference")
    fixture = value["fixture"]
    if not isinstance(fixture, dict) or set(fixture) != {"root", "files", "allowed_changes"}:
        raise BenchmarkError("fixture_config")
    if _safe_relative(fixture["root"]) is None or not isinstance(fixture["files"], dict) or not fixture["files"]:
        raise BenchmarkError("fixture_config")
    for relative, digest in fixture["files"].items():
        if _safe_relative(relative) is None or not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            raise BenchmarkError("fixture_manifest")
    if fixture["allowed_changes"] != ["inventory.py"]:
        raise BenchmarkError("fixture_allowed_changes")
    for name in ("prompt", "oracle"):
        row = value[name]
        expected = {"path", "sha256"} if name == "prompt" else {"path", "sha256", "checks"}
        if not isinstance(row, dict) or set(row) != expected or _safe_relative(row.get("path")) is None or not HASH_RE.fullmatch(str(row.get("sha256", ""))):
            raise BenchmarkError(f"{name}_config")
    if value["oracle"]["checks"] != 14:
        raise BenchmarkError("oracle_check_count")
    if value["arms"] != [
        {"arm": "all-max-control", "environment_label": "control"},
        {"arm": "dynamic-v0.2.1", "environment_label": "dynamic"},
    ]:
        raise BenchmarkError("arm_order")
    if value["required_roles"] != list(REQUIRED_ROLES):
        raise BenchmarkError("required_roles")
    if value["arm_timeout_seconds"] != 900 or value["total_model_timeout_seconds"] != 1800:
        raise BenchmarkError("model_timeout")
    if value["total_model_timeout_seconds"] != value["arm_timeout_seconds"] * len(ARMS):
        raise BenchmarkError("total_timeout")
    if not isinstance(value["acceptance_timeout_seconds"], int) or not 1 <= value["acceptance_timeout_seconds"] <= 120:
        raise BenchmarkError("acceptance_timeout")
    for key in ("weighted_usage_reduction_target", "latency_noninferiority_margin"):
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(float(number)) or not 0 <= float(number) <= 1:
            raise BenchmarkError("comparison_threshold")
    if value["automatic_promotion"] is not False or value["directional_only"] is not True:
        raise BenchmarkError("promotion_boundary")
    return value


def verify_benchmark(repo_root: Path | str = ROOT, config_path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    repo = Path(repo_root).resolve()
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = repo / config_file
    try:
        raw = config_file.read_bytes()
    except OSError as exc:
        raise BenchmarkError("benchmark_config_missing") from exc
    if _sha256(raw) != EXPECTED_CONFIG_SHA256:
        raise BenchmarkError("benchmark_config_drift")
    config = _validate_config(_strict_json(raw))
    plan_path, plan_raw = _safe_file(repo, config["pilot_plan_path"])
    if _sha256(plan_raw) != config["pilot_plan_sha256"]:
        raise BenchmarkError("pilot_plan_drift")
    plan = pilot_tool.verify_plan(plan_path, repo)
    if plan["plan_sha256"] != config["pilot_plan_sha256"] or plan["deadline_minutes"] != 30:
        raise BenchmarkError("pilot_plan_drift")
    fixture_root = repo.joinpath(*PurePosixPath(config["fixture"]["root"]).parts)
    expected_files = set(config["fixture"]["files"])
    if not fixture_root.is_dir() or fixture_root.is_symlink():
        raise BenchmarkError("fixture_root")
    observed_files: set[str] = set()
    for path in fixture_root.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file():
            raise BenchmarkError("fixture_unsafe_entry")
        relative = path.relative_to(fixture_root).as_posix()
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        observed_files.add(relative)
    if observed_files != expected_files:
        raise BenchmarkError("fixture_file_set_drift")
    for relative, digest in config["fixture"]["files"].items():
        _, data = _safe_file(fixture_root, relative)
        if _sha256(data) != digest:
            raise BenchmarkError("fixture_hash_drift")
    for name in ("prompt", "oracle"):
        _, data = _safe_file(repo, config[name]["path"])
        if _sha256(data) != config[name]["sha256"]:
            raise BenchmarkError(f"{name}_hash_drift")
    routing = routing_policy.verify_contract(repo)
    if not routing.get("ok"):
        raise BenchmarkError("routing_policy_drift")
    control = verify_control_bundle.verify(repo / "control-bundles" / "all-max-v1")
    if not control.get("ok"):
        raise BenchmarkError("control_bundle_drift")
    manifest_digest = _sha256(_canonical({"files": config["fixture"]["files"]}))
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": config["benchmark_id"],
        "benchmark_config_sha256": _sha256(raw),
        "fixture_manifest_sha256": manifest_digest,
        "prompt_sha256": config["prompt"]["sha256"],
        "oracle_sha256": config["oracle"]["sha256"],
        "pilot_plan_id": plan["plan_id"],
        "pilot_plan_sha256": plan["plan_sha256"],
        "arm_timeout_seconds": config["arm_timeout_seconds"],
        "total_model_timeout_seconds": config["total_model_timeout_seconds"],
        "automatic_promotion": False,
        "directional_only": True,
        "benchmark_config_path": config_file.resolve(),
        "config": config,
    }


def _canonical_origin(value: str) -> Optional[str]:
    text = value.strip()
    for prefix in ("https://", "http://", "ssh://git@"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    if text.startswith("git@github.com:"):
        text = "github.com/" + text[len("git@github.com:"):]
    if text.endswith(".git"):
        text = text[:-4]
    return text if text == EXPECTED_ORIGIN else None


def _git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BenchmarkError("git_unavailable") from exc
    if proc.returncode != 0:
        raise BenchmarkError("git_check_failed")
    return proc.stdout.strip()


def _repository_facts(repo: Path) -> dict[str, Any]:
    origin = _git(repo, "config", "--get", "remote.origin.url")
    if _canonical_origin(origin) is None:
        raise BenchmarkError("repository_origin_mismatch")
    dirty = bool(_git(repo, "status", "--porcelain", "--untracked-files=all"))
    if dirty:
        raise BenchmarkError("repository_dirty")
    commit = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise BenchmarkError("repository_commit")
    return {"commit": commit, "branch": branch, "dirty": False, "origin_match": True}


def _safe_pilot_home(value: Path | str, repo: Path) -> Path:
    raw = Path(value).expanduser()
    try:
        home = raw.resolve(strict=True)
    except OSError as exc:
        raise BenchmarkError("pilot_home_missing") from exc
    ordinary = (Path.home() / ".codex").resolve(strict=False)
    active = Path(os.environ.get("CODEX_HOME", str(ordinary))).expanduser().resolve(strict=False)
    if home.is_symlink() or not home.is_dir():
        raise BenchmarkError("pilot_home_unsafe")
    for forbidden in (repo.resolve(), ordinary, active):
        try:
            home.relative_to(forbidden)
            raise BenchmarkError("pilot_home_unsafe")
        except ValueError:
            pass
    return home


def _base_env() -> dict[str, str]:
    keep = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SHELL", "USER", "LOGNAME", "SSL_CERT_FILE", "CODEX_CA_CERTIFICATE")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _minimal_env(codex_home: Path) -> dict[str, str]:
    env = _base_env()
    env["CODEX_HOME"] = str(codex_home)
    return env


def _codex_facts(codex_binary: str, pilot_home: Path) -> dict[str, Any]:
    try:
        version = subprocess.run([codex_binary, "--version"], text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BenchmarkError("codex_unavailable") from exc
    if version.returncode != 0 or not version.stdout.strip():
        raise BenchmarkError("codex_unavailable")
    try:
        sandbox_help = subprocess.run(
            [codex_binary, "sandbox", "--help"], env=_minimal_env(pilot_home / "control" / ".codex"),
            text=True, capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BenchmarkError("codex_sandbox_unavailable") from exc
    if sandbox_help.returncode != 0:
        raise BenchmarkError("codex_sandbox_unavailable")
    try:
        sandbox_smoke = subprocess.run(
            [
                codex_binary, "sandbox", "-P", ":workspace", "-C", str(pilot_home),
                "--sandbox-state-disable-network", "--", "/usr/bin/true",
            ],
            env=_minimal_env(pilot_home / "control" / ".codex"),
            text=True, capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BenchmarkError("codex_sandbox_smoke_failed") from exc
    if sandbox_smoke.returncode != 0:
        raise BenchmarkError("codex_sandbox_smoke_failed")
    logins: dict[str, bool] = {}
    for label in ("control", "dynamic"):
        codex_home = pilot_home / label / ".codex"
        try:
            status_result = subprocess.run(
                [codex_binary, "login", "status"], env=_minimal_env(codex_home),
                text=True, capture_output=True, timeout=20, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BenchmarkError("separate_login_required") from exc
        logins[label] = status_result.returncode == 0
    if not all(logins.values()):
        raise BenchmarkError("separate_login_required")
    return {
        "version": version.stdout.strip().splitlines()[0][:120],
        "logins": logins,
        "sandbox_smoke": True,
    }


def preflight(
    repo_root: Path | str,
    config_path: Path | str,
    pilot_home: Path | str,
    *,
    codex_binary: str = "codex",
) -> dict[str, Any]:
    repo = Path(repo_root).resolve()
    benchmark = verify_benchmark(repo, config_path)
    repository = _repository_facts(repo)
    home = _safe_pilot_home(pilot_home, repo)
    config = benchmark["config"]
    environment = pilot_tool.verify_environments(repo / config["pilot_plan_path"], repo, home)
    if not environment.get("ok") or any(row.get("matches") != 8 for row in environment.get("arms", {}).values()):
        raise BenchmarkError("environment_drift")
    pilot = pilot_tool.summarize_pilot(
        repo / config["pilot_plan_path"], repo, repo / ".sol-luna" / "starts",
        repo / ".sol-luna" / "receipts", home,
    )
    if not pilot.get("ok") or pilot.get("registered_count") != 0 or pilot.get("terminal_count") != 0:
        raise BenchmarkError("observational_registry_not_empty")
    codex = _codex_facts(codex_binary, home)
    return {
        "ok": True,
        "benchmark_id": benchmark["benchmark_id"],
        "benchmark_config_sha256": benchmark["benchmark_config_sha256"],
        "fixture_manifest_sha256": benchmark["fixture_manifest_sha256"],
        "prompt_sha256": benchmark["prompt_sha256"],
        "oracle_sha256": benchmark["oracle_sha256"],
        "pilot_plan_id": benchmark["pilot_plan_id"],
        "pilot_plan_sha256": benchmark["pilot_plan_sha256"],
        "repository": repository,
        "codex": codex,
        "environment_matches": {arm: row["matches"] for arm, row in environment["arms"].items()},
        "registered_count": 0,
        "terminal_count": 0,
        "model_calls_started": 0,
        "arm_timeout_seconds": benchmark["arm_timeout_seconds"],
        "total_model_timeout_seconds": benchmark["total_model_timeout_seconds"],
        "automatic_promotion": False,
        "directional_only": True,
        "benchmark_config_path": benchmark["benchmark_config_path"],
        "config": config,
        "pilot_home": home,
    }


def _ensure_private_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_dir():
            raise BenchmarkError("output_path_unsafe")
        if stat.S_IMODE(path.stat().st_mode) != 0o700:
            raise BenchmarkError("output_mode")
        return
    path.mkdir(parents=False, mode=0o700)
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        path.chmod(0o700)


def _private_write(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise BenchmarkError("output_conflict")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _copy_fixture(repo: Path, config: dict[str, Any], destination: Path) -> None:
    _ensure_private_directory(destination)
    fixture_root = repo.joinpath(*PurePosixPath(config["fixture"]["root"]).parts)
    for relative in sorted(config["fixture"]["files"]):
        source, data = _safe_file(fixture_root, relative)
        target = destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if source.is_symlink():
            raise BenchmarkError("fixture_unsafe_entry")
        _private_write(target, data)


def _workspace_state(workspace: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    total_bytes = 0
    for path in workspace.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file():
            result["__unsafe__"] = "unsafe"
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            result["__unsafe__"] = "unsafe"
            continue
        total_bytes += size
        if len(result) >= MAX_WORKSPACE_FILES or size > MAX_WORKSPACE_FILE_BYTES or total_bytes > MAX_WORKSPACE_BYTES:
            result["__unsafe__"] = "unsafe"
            continue
        result[path.relative_to(workspace).as_posix()] = _sha256(path.read_bytes())
    return result


def _scope_ok(before: dict[str, str], after: dict[str, str], allowed_changes: Iterable[str]) -> bool:
    allowed = set(allowed_changes)
    if "__unsafe__" in after or set(before) != set(after):
        return False
    changed = {path for path in before if before[path] != after[path]}
    return bool(changed) and changed.issubset(allowed)


def _session_snapshot(codex_home: Path) -> dict[Path, tuple[int, int]]:
    sessions = codex_home / "sessions"
    if not sessions.exists():
        return {}
    if sessions.is_symlink() or not sessions.is_dir():
        raise BenchmarkError("session_root_unsafe")
    result: dict[Path, tuple[int, int]] = {}
    for path in sessions.rglob("*.jsonl"):
        if path.is_symlink() or not path.is_file():
            raise BenchmarkError("session_file_unsafe")
        info = path.stat()
        result[path] = (info.st_size, info.st_mtime_ns)
    return result


def _session_delta(before: dict[Path, tuple[int, int]], after: dict[Path, tuple[int, int]]) -> tuple[list[Path], bool]:
    new = sorted(path for path in after if path not in before)
    changed_existing = any(path in after and after[path] != marker for path, marker in before.items())
    deleted = any(path not in after for path in before)
    return new, changed_existing or deleted


def _session_meta(path: Path) -> dict[str, Any]:
    metadata: list[dict[str, Any]] = []
    try:
        with path.open("rb") as handle:
            for raw in handle:
                if len(raw) > MAX_JSON_BYTES:
                    return {}
                value = json.loads(raw)
                if isinstance(value, dict) and value.get("type") == "session_meta" and isinstance(value.get("payload"), dict):
                    metadata.append(value["payload"])
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return metadata[0] if len(metadata) == 1 else {}


def _correlated_sessions(paths: Sequence[Path], root_thread_id: Optional[str], concurrent_change: bool) -> tuple[list[Path], bool]:
    if concurrent_change or not isinstance(root_thread_id, str) or len(paths) != len(REQUIRED_ROLES) + 1:
        return [], False
    root_files: list[Path] = []
    child_files: dict[str, Path] = {}
    for path in paths:
        meta = _session_meta(path)
        if not meta:
            return [], False
        role = meta.get("agent_role")
        identifier = meta.get("id") or meta.get("session_id")
        parent = meta.get("parent_thread_id") or meta.get("forked_from_id")
        if role in REQUIRED_ROLES:
            if role in child_files or parent != root_thread_id:
                return [], False
            child_files[role] = path
        elif role in {None, "root"} and identifier == root_thread_id and parent is None:
            root_files.append(path)
        else:
            return [], False
    if len(root_files) != 1 or set(child_files) != set(REQUIRED_ROLES):
        return [], False
    return [root_files[0], *(child_files[role] for role in REQUIRED_ROLES)], True


def _open_capture(path: Path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "wb")


def _terminate_group(proc: subprocess.Popen[bytes], *, immediate: bool = False) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL if immediate else signal.SIGTERM)
        proc.wait(timeout=2)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _file_limit(max_bytes: int):
    def apply_limit() -> None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_bytes, max_bytes))

    return apply_limit


def _oracle_limits() -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_ORACLE_CAPTURE_BYTES, MAX_ORACLE_CAPTURE_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (65, 65))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def _run_codex(
    codex_binary: str,
    codex_home: Path,
    workspace: Path,
    prompt: str,
    capture_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    stdout_path = capture_dir / "events.jsonl"
    stderr_path = capture_dir / "stderr.log"
    last_path = capture_dir / "last-message.txt"
    _private_write(last_path, b"")
    command = [
        codex_binary, "exec", "--json", "--skip-git-repo-check", "--sandbox",
        "workspace-write", "--output-last-message", str(last_path), prompt,
    ]
    started = time.monotonic()
    with _open_capture(stdout_path) as stdout_file, _open_capture(stderr_path) as stderr_file:
        try:
            proc = subprocess.Popen(
                command, cwd=workspace, env=_minimal_env(codex_home),
                stdout=stdout_file, stderr=stderr_file, start_new_session=True,
                preexec_fn=_file_limit(MAX_CAPTURE_BYTES),
            )
        except OSError as exc:
            raise BenchmarkError("codex_launch_failed") from exc
        timed_out = False
        try:
            exit_code = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_group(proc, immediate=True)
            exit_code = None
        except BaseException:
            _terminate_group(proc)
            raise
    duration_ms = int((time.monotonic() - started) * 1000)
    event_summary = _event_summary(stdout_path)
    if stdout_path.stat().st_size > MAX_CAPTURE_BYTES or stderr_path.stat().st_size > MAX_CAPTURE_BYTES or last_path.stat().st_size > MAX_CAPTURE_BYTES:
        raise BenchmarkError("capture_limit")
    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_ms": min(duration_ms, timeout_seconds * 1000 + 6000),
        "events": event_summary,
        "last_message_present": last_path.stat().st_size > 0,
    }


def _event_summary(path: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    malformed = 0
    root_thread_id: Optional[str] = None
    try:
        with path.open("rb") as handle:
            for raw in handle:
                if len(raw) > MAX_JSON_BYTES:
                    malformed += 1
                    continue
                try:
                    value = json.loads(raw)
                except (UnicodeError, json.JSONDecodeError):
                    malformed += 1
                    continue
                kind = value.get("type") if isinstance(value, dict) else None
                if isinstance(kind, str) and len(kind) <= 80:
                    counts[kind] = counts.get(kind, 0) + 1
                    if kind == "thread.started":
                        candidate = value.get("thread_id")
                        if isinstance(candidate, str) and 1 <= len(candidate) <= 128 and "/" not in candidate and "\\" not in candidate:
                            root_thread_id = candidate
                        else:
                            malformed += 1
                else:
                    malformed += 1
    except OSError:
        return {"ok": False, "malformed": 1, "types": {}}
    errors = sum(counts.get(key, 0) for key in ("error", "turn.failed"))
    return {
        "ok": malformed == 0 and errors == 0 and counts.get("thread.started", 0) == 1 and counts.get("turn.completed", 0) == 1,
        "malformed": malformed,
        "errors": errors,
        "types": counts,
        "root_thread_id": root_thread_id,
    }


def _expected_runtime(codex_home: Path) -> dict[str, dict[str, str]]:
    if tomllib is None:
        raise BenchmarkError("python_311_required")
    try:
        config = tomllib.loads((codex_home / "config.toml").read_text())
        expected = {
            "root": {
                "model": config["model"],
                "reasoning_effort": config["model_reasoning_effort"],
                "service_tier": "default",
            }
        }
        for role in REQUIRED_ROLES:
            row = tomllib.loads((codex_home / "agents" / f"{role}.toml").read_text())
            expected[role] = {
                "model": row["model"],
                "reasoning_effort": row["model_reasoning_effort"],
                "service_tier": row["service_tier"],
            }
        return expected
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise BenchmarkError("runtime_config_unreadable") from exc


def _weighted_usage(report: dict[str, Any], expected: dict[str, dict[str, str]], rate_card: dict[str, Any]) -> dict[str, Any]:
    groups = report.get("groups")
    if not isinstance(groups, list):
        return {"coverage": "unknown", "total_tokens": None, "weighted_usage": None, "groups": []}
    observed: dict[str, dict[str, Any]] = {}
    privacy_groups: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict) or group.get("role") not in expected or group.get("role") in observed:
            return {"coverage": "unknown", "total_tokens": None, "weighted_usage": None, "groups": []}
        role = group["role"]
        runtime = expected[role]
        service = group.get("service_tier")
        service_matches = service in {runtime["service_tier"], "priority" if runtime["service_tier"] == "fast" else runtime["service_tier"], "unknown"}
        if (
            group.get("model") != runtime["model"]
            or group.get("reasoning_effort") != runtime["reasoning_effort"]
            or not service_matches
            or group.get("runs") != 1
            or group.get("completed") != 1
        ):
            return {"coverage": "unknown", "total_tokens": None, "weighted_usage": None, "groups": []}
        observed[role] = group
        total = group.get("tokens", {}).get("total")
        privacy_groups.append({
            "role": role,
            "model": runtime["model"],
            "reasoning": runtime["reasoning_effort"],
            "service_tier": runtime["service_tier"],
            "service_tier_provenance": "observed" if service != "unknown" else "frozen-config",
            "runs": 1,
            "completed": 1,
            "token_usage_available": group.get("token_usage_runs") == 1,
            "total_tokens": total if isinstance(total, int) and total >= 0 else None,
        })
    required = set(expected)
    roles_ok = set(observed) == required
    token_complete = roles_ok and report.get("runs") == len(required) and report.get("completed") == len(required) and report.get("token_usage_runs") == len(required)
    if not token_complete:
        return {"coverage": "unknown", "total_tokens": None, "weighted_usage": None, "groups": privacy_groups, "roles_complete": roles_ok}
    weighted = 0.0
    total_tokens = 0
    weights = rate_card["weights"]
    for group in privacy_groups:
        total = group["total_tokens"]
        if not isinstance(total, int):
            return {"coverage": "unknown", "total_tokens": None, "weighted_usage": None, "groups": privacy_groups, "roles_complete": roles_ok}
        total_tokens += total
        weighted += total * weights["model"].get(group["model"], weights["model"]["default"]) * weights["reasoning"].get(group["reasoning"], weights["reasoning"]["default"]) * weights["service_tier"].get(group["service_tier"], weights["service_tier"]["default"])
    return {
        "coverage": "complete-full-workflow",
        "total_tokens": total_tokens,
        "weighted_usage": weighted,
        "groups": privacy_groups,
        "roles_complete": True,
        "provenance": "attributable-session-records-and-frozen-rate-card",
        "rate_card_version": rate_card["version"],
        "rate_card_calibration": rate_card["status"],
    }


def _run_oracle(repo: Path, config: dict[str, Any], workspace: Path, capture_dir: Path, codex_binary: str) -> dict[str, Any]:
    oracle, _ = _safe_file(repo, config["oracle"]["path"])
    stdout_path = capture_dir / "oracle.json"
    stderr_path = capture_dir / "oracle.stderr.log"
    sandbox_home = capture_dir / "oracle-codex-home"
    fake_home = capture_dir / "oracle-home"
    _ensure_private_directory(sandbox_home)
    _ensure_private_directory(fake_home)
    env = _base_env()
    env["CODEX_HOME"] = str(sandbox_home)
    env["HOME"] = str(fake_home)
    command = [
        codex_binary, "sandbox", "-P", ":workspace", "-C", str(workspace),
        "--sandbox-state-disable-network", "--", sys.executable, str(oracle),
        "--workspace", str(workspace),
    ]
    with _open_capture(stdout_path) as stdout_file, _open_capture(stderr_path) as stderr_file:
        try:
            proc = subprocess.Popen(
                command, cwd=workspace, env=env, stdout=stdout_file,
                stderr=stderr_file, start_new_session=True,
                preexec_fn=_oracle_limits,
            )
            try:
                exit_code = proc.wait(timeout=config["acceptance_timeout_seconds"])
            except subprocess.TimeoutExpired:
                _terminate_group(proc, immediate=True)
                exit_code = None
            except BaseException:
                _terminate_group(proc)
                raise
        except OSError:
            return {"ok": False, "status": "sandbox-unavailable", "checks": config["oracle"]["checks"], "passed": 0, "failed": config["oracle"]["checks"]}
        if exit_code is None:
            return {"ok": False, "status": "timeout", "checks": config["oracle"]["checks"], "passed": 0, "failed": config["oracle"]["checks"]}
    if stdout_path.stat().st_size > MAX_ORACLE_CAPTURE_BYTES or stderr_path.stat().st_size > MAX_ORACLE_CAPTURE_BYTES:
        return {"ok": False, "status": "capture-limit", "checks": config["oracle"]["checks"], "passed": 0, "failed": config["oracle"]["checks"]}
    try:
        value = _strict_json(stdout_path.read_bytes())
    except BenchmarkError:
        return {"ok": False, "status": "invalid-output", "checks": config["oracle"]["checks"], "passed": 0, "failed": config["oracle"]["checks"]}
    expected_keys = {"ok", "checks", "passed", "failed"}
    if not isinstance(value, dict) or set(value) != expected_keys or value.get("checks") != config["oracle"]["checks"]:
        return {"ok": False, "status": "invalid-output", "checks": config["oracle"]["checks"], "passed": 0, "failed": config["oracle"]["checks"]}
    return {**value, "ok": bool(value["ok"] and exit_code == 0), "status": "passed" if value["ok"] and exit_code == 0 else "failed"}


def _load_rate_card(repo: Path) -> dict[str, Any]:
    _, raw = _safe_file(repo, "config/rate-card.v1.json")
    value = _strict_json(raw)
    if not isinstance(value, dict) or value.get("version") != "rate-card.v1" or value.get("status") != "uncalibrated":
        raise BenchmarkError("rate_card_drift")
    return value


def _arm_result(
    repo: Path,
    config: dict[str, Any],
    arm: str,
    codex_binary: str,
    pilot_home: Path,
    workspace: Path,
    capture_dir: Path,
    prompt: str,
    before_state: dict[str, str],
) -> dict[str, Any]:
    label = next(row["environment_label"] for row in config["arms"] if row["arm"] == arm)
    codex_home = pilot_home / label / ".codex"
    environment = pilot_tool.verify_environments(repo / config["pilot_plan_path"], repo, pilot_home)
    if not environment.get("ok") or environment["arms"][arm]["matches"] != 8:
        raise BenchmarkError("environment_drift")
    sessions_before = _session_snapshot(codex_home)
    execution = _run_codex(codex_binary, codex_home, workspace, prompt, capture_dir, config["arm_timeout_seconds"])
    sessions_after = _session_snapshot(codex_home)
    new_session_files, concurrent_session_change = _session_delta(sessions_before, sessions_after)
    session_files, session_attributed = _correlated_sessions(
        new_session_files, execution["events"].get("root_thread_id"), concurrent_session_change,
    )
    report = usage_report.analyze([str(path) for path in session_files])
    expected_runtime = _expected_runtime(codex_home)
    usage = _weighted_usage(report, expected_runtime, _load_rate_card(repo))
    lane_evidence = bool(session_attributed and usage.get("roles_complete"))
    after_state = _workspace_state(workspace)
    scope_ok = _scope_ok(before_state, after_state, config["fixture"]["allowed_changes"])
    if execution["timed_out"]:
        oracle = {"ok": False, "status": "not-run", "checks": config["oracle"]["checks"], "passed": 0, "failed": config["oracle"]["checks"]}
        disposition = "abandoned"
    else:
        oracle = _run_oracle(repo, config, workspace, capture_dir, codex_binary)
        accepted = execution["exit_code"] == 0 and execution["events"]["ok"] and execution["last_message_present"] and oracle["ok"] and scope_ok and lane_evidence
        disposition = "accepted" if accepted else "rejected"
    return {
        "arm": arm,
        "disposition": disposition,
        "duration_ms": execution["duration_ms"],
        "timed_out": execution["timed_out"],
        "process_exit_ok": execution["exit_code"] == 0,
        "structured_events_ok": execution["events"]["ok"],
        "last_message_present": execution["last_message_present"],
        "environment_matches": environment["arms"][arm]["matches"],
        "scope_ok": scope_ok,
        "lane_evidence": {
            "status": "complete" if lane_evidence else "unknown",
            "required_roles": list(REQUIRED_ROLES),
            "roles_complete": lane_evidence,
            "session_attribution": "complete" if session_attributed else "unknown",
        },
        "acceptance": oracle,
        "usage": usage,
        "raw_capture_retained_private": True,
    }


def _comparison(config: dict[str, Any], arms: dict[str, dict[str, Any]]) -> dict[str, Any]:
    control = arms["all-max-control"]
    dynamic = arms["dynamic-v0.2.1"]
    both_quality = control["disposition"] == "accepted" and dynamic["disposition"] == "accepted"
    complete_usage = all(row["usage"].get("coverage") == "complete-full-workflow" for row in arms.values())
    reduction = None
    if complete_usage and control["usage"]["weighted_usage"] > 0:
        reduction = (control["usage"]["weighted_usage"] - dynamic["usage"]["weighted_usage"]) / control["usage"]["weighted_usage"]
    latency_ok = dynamic["duration_ms"] <= control["duration_ms"] * (1 + config["latency_noninferiority_margin"]) if both_quality else None
    target_ok = reduction >= config["weighted_usage_reduction_target"] if reduction is not None else None
    if both_quality and complete_usage:
        status = "dynamic-promising-human-review" if target_ok and latency_ok else "keep-all-max"
    else:
        status = "inconclusive"
    return {
        "status": status,
        "both_quality_pass": both_quality,
        "usage_coverage_complete": complete_usage,
        "weighted_usage_reduction": reduction,
        "weighted_usage_reduction_target": config["weighted_usage_reduction_target"],
        "weighted_usage_target_met": target_ok,
        "latency_noninferior": latency_ok,
        "latency_margin": config["latency_noninferiority_margin"],
        "directional_only": True,
        "automatic_promotion": False,
        "human_review_required": True,
    }


def validate_receipt(value: Any) -> bool:
    """Validate the privacy and decision boundary of a generated receipt."""

    top_keys = {
        "schema_version", "benchmark_id", "run_id", "origin", "started_at",
        "closed_at", "toolkit", "integrity", "limits", "arms", "comparison",
        "artifacts_retained_private",
    }
    if not isinstance(value, dict) or set(value) != top_keys:
        return False
    if value.get("schema_version") != SCHEMA_VERSION or value.get("origin") != ORIGIN:
        return False
    if not isinstance(value.get("run_id"), str) or not re.fullmatch(r"br1-[0-9a-f]{16}", value["run_id"]):
        return False
    if set(value.get("arms", {})) != set(ARMS):
        return False
    for arm, row in value["arms"].items():
        if not isinstance(row, dict) or row.get("arm") != arm or row.get("disposition") not in {"accepted", "rejected", "abandoned"}:
            return False
    comparison = value.get("comparison")
    if not isinstance(comparison, dict) or comparison.get("status") not in {"dynamic-promising-human-review", "keep-all-max", "inconclusive"}:
        return False
    if comparison.get("automatic_promotion") is not False or comparison.get("directional_only") is not True or comparison.get("human_review_required") is not True:
        return False
    if value.get("artifacts_retained_private") is not True:
        return False
    forbidden_keys = {"prompt", "path", "stdout", "stderr", "raw", "source", "tool_arguments", "thread_id", "session_id", "codex_task_id"}
    home_text = str(Path.home())

    def safe(node: Any) -> bool:
        if isinstance(node, dict):
            return not (set(node) & forbidden_keys) and all(safe(item) for item in node.values())
        if isinstance(node, list):
            return all(safe(item) for item in node)
        if isinstance(node, str):
            return home_text not in node and "auth.json" not in node and "BEGIN PRIVATE KEY" not in node
        return True

    return safe(value)


def execute(
    preflight_report: dict[str, Any],
    repo_root: Path | str,
    *,
    codex_binary: str = "codex",
    output_root: Optional[Path | str] = None,
) -> tuple[dict[str, Any], Path]:
    repo = Path(repo_root).resolve()
    config = preflight_report["config"]
    pilot_home = Path(preflight_report["pilot_home"]).resolve()
    root = Path(output_root).expanduser().resolve(strict=False) if output_root else pilot_home / "benchmark-runs"
    allowed_output = (pilot_home / "benchmark-runs").resolve(strict=False)
    try:
        root.relative_to(allowed_output)
    except ValueError as exc:
        raise BenchmarkError("output_root_unsafe") from exc
    if root.exists():
        _ensure_private_directory(root)
    else:
        parent = root.parent.resolve(strict=True)
        if parent != pilot_home.resolve() and pilot_home.resolve() not in parent.parents:
            raise BenchmarkError("output_root_unsafe")
        root.mkdir(mode=0o700)
    run_id = "br1-" + secrets.token_hex(8)
    run_dir = root / run_id
    _ensure_private_directory(run_dir)
    workspaces = run_dir / "workspaces"
    captures = run_dir / "captures"
    _ensure_private_directory(workspaces)
    _ensure_private_directory(captures)
    _, prompt_bytes = _safe_file(repo, config["prompt"]["path"])
    prompt = prompt_bytes.decode("utf-8")
    results: dict[str, dict[str, Any]] = {}
    started_at = _utc_now()
    for arm_row in config["arms"]:
        current = verify_benchmark(repo, preflight_report["benchmark_config_path"])
        if any(current[key] != preflight_report[key] for key in ("benchmark_config_sha256", "fixture_manifest_sha256", "prompt_sha256", "oracle_sha256", "pilot_plan_sha256")):
            raise BenchmarkError("benchmark_drift_after_preflight")
        arm = arm_row["arm"]
        workspace = workspaces / arm
        capture = captures / arm
        _copy_fixture(repo, config, workspace)
        _ensure_private_directory(capture)
        before = _workspace_state(workspace)
        results[arm] = _arm_result(
            repo, config, arm, codex_binary, pilot_home, workspace, capture,
            prompt, before,
        )
        post_environment = pilot_tool.verify_environments(repo / config["pilot_plan_path"], repo, pilot_home)
        if not post_environment.get("ok"):
            raise BenchmarkError("environment_drift")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": config["benchmark_id"],
        "run_id": run_id,
        "origin": ORIGIN,
        "started_at": started_at,
        "closed_at": _utc_now(),
        "toolkit": {
            "commit": preflight_report["repository"]["commit"],
            "branch": preflight_report["repository"]["branch"],
            "clean": True,
            "codex_version": preflight_report["codex"]["version"],
            "benchmark_config_sha256": preflight_report["benchmark_config_sha256"],
            "pilot_plan_sha256": preflight_report["pilot_plan_sha256"],
        },
        "integrity": {
            "fixture_manifest_sha256": preflight_report["fixture_manifest_sha256"],
            "prompt_sha256": preflight_report["prompt_sha256"],
            "oracle_sha256": preflight_report["oracle_sha256"],
            "environment_matches": preflight_report["environment_matches"],
            "ordinary_codex_home_targeted": False,
            "credentials_or_sessions_copied": False,
            "observational_registry_touched": False,
        },
        "limits": {
            "arm_seconds": config["arm_timeout_seconds"],
            "total_model_seconds": config["total_model_timeout_seconds"],
            "sequential": True,
            "retries": 0,
        },
        "arms": results,
        "comparison": _comparison(config, results),
        "artifacts_retained_private": True,
    }
    if not validate_receipt(receipt):
        raise BenchmarkError("receipt_validation_failed")
    receipt_path = run_dir / "comparison-receipt.json"
    _private_write(receipt_path, _canonical(receipt))
    return receipt, receipt_path


def _public_preflight(report: dict[str, Any]) -> dict[str, Any]:
    return {key: report[key] for key in (
        "ok", "benchmark_id", "benchmark_config_sha256", "fixture_manifest_sha256",
        "prompt_sha256", "oracle_sha256", "pilot_plan_id", "pilot_plan_sha256",
        "repository", "codex", "environment_matches", "registered_count",
        "terminal_count", "model_calls_started", "arm_timeout_seconds",
        "total_model_timeout_seconds", "automatic_promotion", "directional_only",
    )}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--pilot-home", required=True)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--output-root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--approve-model-calls", action="store_true")
    parser.add_argument("--format", choices=("json",), default="json")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if sys.version_info < (3, 11):
        print(json.dumps({"ok": False, "error": "python_311_required"}, sort_keys=True))
        return 2
    try:
        report = preflight(args.root, args.config, args.pilot_home, codex_binary=args.codex)
        if args.dry_run:
            print(json.dumps(_public_preflight(report), sort_keys=True, separators=(",", ":")))
            return 0
        approved = args.approve_model_calls
        if not approved and sys.stdin.isatty():
            print("This will make two sequential quota-consuming Codex calls, limited to 15 minutes each.")
            approved = input("Type RUN to continue: ").strip() == "RUN"
        if not approved:
            output = _public_preflight(report)
            output.update({"ok": False, "status": "approval-required", "model_calls_started": 0})
            print(json.dumps(output, sort_keys=True, separators=(",", ":")))
            return 4
        receipt, receipt_path = execute(
            report, args.root, codex_binary=args.codex, output_root=args.output_root,
        )
        public = {
            "ok": receipt["comparison"]["status"] != "inconclusive",
            "benchmark_id": receipt["benchmark_id"],
            "run_id": receipt["run_id"],
            "comparison": receipt["comparison"],
            "arms": {
                arm: {
                    "disposition": row["disposition"],
                    "duration_ms": row["duration_ms"],
                    "acceptance": row["acceptance"],
                    "usage_coverage": row["usage"].get("coverage"),
                    "weighted_usage": row["usage"].get("weighted_usage"),
                }
                for arm, row in receipt["arms"].items()
            },
            "receipt": receipt_path.name,
            "automatic_promotion": False,
        }
        print(json.dumps(public, sort_keys=True, separators=(",", ":")))
        return 0 if public["ok"] else 3
    except (BenchmarkError, pilot_tool.PilotError) as exc:
        code = exc.code if hasattr(exc, "code") else "benchmark_failed"
        print(json.dumps({"ok": False, "error": code, "automatic_promotion": False}, sort_keys=True, separators=(",", ":")))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "error": "interrupted", "automatic_promotion": False}, sort_keys=True, separators=(",", ":")))
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
