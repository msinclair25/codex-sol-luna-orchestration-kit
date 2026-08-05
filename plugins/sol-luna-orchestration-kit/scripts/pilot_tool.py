#!/usr/bin/env python3
"""Strict local tooling for the frozen M4 observational pilot.

The tool validates a checked-in plan, creates two isolated Codex state roots,
registers privacy-safe milestone starts, and joins them to terminal receipts.
It never launches Codex, copies authentication, reads session content, or
promotes a policy automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

try:
    import platform_fs
except ImportError:  # pragma: no cover - package import in tests
    from scripts import platform_fs  # type: ignore[no-redef]

try:
    from scripts import receipt_tool
except ImportError:  # pragma: no cover - direct script execution
    receipt_path = Path(__file__).resolve().parent / "receipt_tool.py"
    receipt_spec = importlib.util.spec_from_file_location("sol_luna_pilot_receipt_tool", receipt_path)
    if receipt_spec is None or receipt_spec.loader is None:
        raise
    receipt_tool = importlib.util.module_from_spec(receipt_spec)  # type: ignore[assignment]
    sys.modules[receipt_spec.name] = receipt_tool
    receipt_spec.loader.exec_module(receipt_tool)


SCHEMA_VERSION = 1
ORIGIN = "unsigned-local-audit"
DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = DEFAULT_ROOT / "config" / "m4-pilot.v1.json"
MAX_JSON_BYTES = 128 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024
ARMS = ("all-max-control", "dynamic-v0.2.1")
ROLES = (
    "luna_scout_fast",
    "luna_worker_fast",
    "luna_critic_fast",
    "luna_tester_fast",
    "luna_max_fast",
)
FAMILIES = {"foundation", "routing", "receipts", "feature", "bugfix", "integration", "release", "security", "other"}
RISK_BANDS = {"small", "medium", "large", "high-risk", "critical"}
DISPOSITIONS = {"accepted", "rejected", "abandoned"}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
REL_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
UTC_RE = re.compile(r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
PLAN_KEYS = {
    "schema_version", "plan_id", "project_id", "status", "created_at", "source_commit",
    "sample_size", "deadline_hours", "minimum_families", "assignment_method",
    "policies", "checkpoints", "kill_criteria", "slots", "origin",
}
POLICY_KEYS = {
    "environment_label", "bundle_version", "policy_hash_kind", "policy_path",
    "policy_sha256", "agents_path", "agents_sha256", "config_path",
    "config_sha256", "rate_card_path", "rate_card_sha256", "roles",
}
SLOT_KEYS = {"slot_id", "sequence", "pair_id", "arm", "family", "size_risk_band", "acceptance_check_ids"}
CHECKPOINT_KEYS = {
    "terminal_coverage_required", "critical_high_defect_regression_max",
    "spawn_precision_min", "weighted_usage_reduction_target",
    "latency_noninferiority_margin", "required_dispositions",
    "promotion_requires_calibrated_or_replicated", "automatic_promotion",
}
START_KEYS = {
    "schema_version", "start_id", "plan_id", "project_id", "plan_sha256", "source_commit", "slot_id",
    "sequence", "pair_id", "arm", "family", "size_risk_band",
    "milestone_id", "codex_task_id", "started_at", "due_at",
    "acceptance_check_ids", "expected", "origin",
}
EXPECTED_KEYS = {"bundle_version", "policy_sha256", "agents_sha256", "config_sha256", "rate_card_sha256", "roles"}
ENV_MANIFEST = ".sol-luna-pilot-environment.json"


class PilotError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _strict_loads(raw: str) -> Any:
    if not isinstance(raw, str):
        raise PilotError("invalid_json")
    try:
        if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
            raise PilotError("json_oversize")
    except (UnicodeError, MemoryError, OverflowError) as exc:
        raise PilotError("json_oversize") from exc

    def pairs_hook(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PilotError("duplicate_json_key")
            result[key] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs_hook,
            parse_constant=lambda _: (_ for _ in ()).throw(PilotError("nonfinite_number")),
        )
    except PilotError:
        raise
    except (json.JSONDecodeError, UnicodeError, MemoryError, OverflowError, RecursionError) as exc:
        raise PilotError("malformed_json") from exc


def _has_symlink(path: Path) -> bool:
    try:
        current = Path(path.anchor) if path.is_absolute() else Path.cwd()
        parts = path.parts[1:] if path.is_absolute() else path.parts
        for part in parts:
            current /= part
            if platform_fs.is_link_like(current) and not platform_fs.allowed_system_link(current):
                return True
        return False
    except (OSError, RuntimeError):
        return True


def _safe_relative(value: Any) -> Optional[str]:
    if not isinstance(value, str) or REL_RE.fullmatch(value) is None or "\\" in value or "\x00" in value:
        return None
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix() != value or any(part in {"", ".", ".."} for part in parsed.parts):
        return None
    return value


def _id(value: Any) -> bool:
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None


def _hash(value: Any) -> bool:
    return isinstance(value, str) and HASH_RE.fullmatch(value) is not None


def _timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or UTC_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _root(value: Path | str, *, must_exist: bool = True) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = Path(os.path.abspath(path))
    if len(path.parts) < 3 or platform_fs.is_link_like(path) or _has_symlink(path):
        raise PilotError("unsafe_root")
    if must_exist and not path.is_dir():
        raise PilotError("root_missing")
    if path.exists() and not path.is_dir():
        raise PilotError("unsafe_root")
    return path


def _pilot_home(value: Path | str, repo: Path) -> Path:
    """Require a dedicated container, never a home, repo, or CODEX_HOME root."""
    path = _root(value, must_exist=False)
    canonical = path.resolve(strict=False)

    def folded_parts(candidate: Path) -> Tuple[str, ...]:
        return tuple(unicodedata.normalize("NFKC", part).casefold() for part in candidate.parts)

    def contains(parent: Path, child: Path) -> bool:
        parent_parts = folded_parts(parent)
        child_parts = folded_parts(child)
        return len(parent_parts) <= len(child_parts) and child_parts[:len(parent_parts)] == parent_parts

    def overlaps(left: Path, right: Path) -> bool:
        return contains(left, right) or contains(right, left)

    home = Path.home().resolve()
    ordinary_codex_home = (home / ".codex").resolve(strict=False)
    active_codex_home = Path(os.environ.get("CODEX_HOME", ordinary_codex_home)).expanduser()
    if not active_codex_home.is_absolute():
        active_codex_home = Path.cwd() / active_codex_home
    protected = {
        repo.resolve(),
        ordinary_codex_home,
        Path(os.path.abspath(active_codex_home)).resolve(strict=False),
    }
    broad_home_target = contains(canonical, home)
    if len(canonical.parts) < 4 or broad_home_target or any(overlaps(canonical, root) for root in protected):
        raise PilotError("unsafe_pilot_home")
    return path


def _data_directory(value: Path | str, repo: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo / path
    return _root(path, must_exist=False)


def _file(root: Path, relative: str, limit: int = MAX_ARTIFACT_BYTES) -> Tuple[Path, bytes]:
    if _safe_relative(relative) is None:
        raise PilotError("unsafe_source_path")
    path = root.joinpath(*relative.split("/"))
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise PilotError("unsafe_source_path") from exc
    if platform_fs.is_link_like(path) or _has_symlink(path) or not path.is_file():
        raise PilotError("source_missing")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PilotError("source_unreadable") from exc
    if len(data) > limit:
        raise PilotError("source_oversize")
    return path, data


def _read_json_file(path: Path, *, require_mode: Optional[int] = None) -> Tuple[Any, bytes]:
    if platform_fs.is_link_like(path) or _has_symlink(path) or not path.is_file():
        raise PilotError("unsafe_json_path")
    try:
        if require_mode is not None and not platform_fs.mode_matches(path, require_mode):
            raise PilotError("unsafe_permissions")
        raw = path.read_bytes()
        if len(raw) > MAX_JSON_BYTES:
            raise PilotError("json_oversize")
        return _strict_loads(raw.decode("utf-8")), raw
    except PilotError:
        raise
    except (OSError, UnicodeError, MemoryError) as exc:
        raise PilotError("json_unreadable") from exc


def _ensure_directory(path: Path) -> None:
    path = _root(path, must_exist=False)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.exists() or platform_fs.is_link_like(current):
            if (
                platform_fs.is_link_like(current)
                and not platform_fs.allowed_system_link(current)
            ) or not current.is_dir():
                raise PilotError("unsafe_directory")
            continue
        current.mkdir(mode=0o700)
    platform_fs.set_mode(path, 0o700)


def _atomic_write(path: Path, data: bytes) -> None:
    if path.exists() or platform_fs.is_link_like(path):
        raise PilotError("destination_exists")
    _ensure_directory(path.parent)
    try:
        platform_fs.atomic_create(path, data)
    except FileExistsError as exc:
        raise PilotError("destination_exists") from exc


def _validate_policy(arm: str, policy: Any, repo: Path) -> None:
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise PilotError("policy_shape")
    expected_label = "control" if arm == "all-max-control" else "dynamic"
    expected_kind = "bundle-manifest" if arm == "all-max-control" else "routing-policy"
    if policy["environment_label"] != expected_label or policy["policy_hash_kind"] != expected_kind:
        raise PilotError("policy_identity")
    if not _id(policy["bundle_version"]):
        raise PilotError("policy_version")
    source_data: Dict[str, bytes] = {}
    for path_key, hash_key in (
        ("policy_path", "policy_sha256"),
        ("agents_path", "agents_sha256"),
        ("config_path", "config_sha256"),
        ("rate_card_path", "rate_card_sha256"),
    ):
        _, data = _file(repo, policy[path_key])
        source_data[path_key] = data
        if not _hash(policy[hash_key]) or hashlib.sha256(data).hexdigest() != policy[hash_key]:
            raise PilotError("policy_source_drift")
    if tomllib is None:
        raise PilotError("python_tomllib_missing")
    try:
        config = tomllib.loads(source_data["config_path"].decode("utf-8"))
    except (UnicodeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise PilotError("config_semantic_drift") from exc
    features = config.get("features")
    agents = config.get("agents")
    if (
        config.get("model") != "gpt-5.6-sol"
        or config.get("model_reasoning_effort") not in {"low", "medium", "high", "xhigh", "max", "ultra"}
        or "service_tier" in config
        or not isinstance(features, dict)
        or features.get("fast_mode") is not True
        or features.get("multi_agent") is not True
        or not isinstance(agents, dict)
        or agents.get("max_concurrent_threads_per_session") != 3
        or "default_subagent_model" in agents
    ):
        raise PilotError("config_semantic_drift")
    roles = policy["roles"]
    if not isinstance(roles, dict) or set(roles) != set(ROLES):
        raise PilotError("policy_roles_shape")
    expected_reasoning = {
        "luna_scout_fast": "medium",
        "luna_worker_fast": "high",
        "luna_critic_fast": "high",
        "luna_tester_fast": "medium",
        "luna_max_fast": "max",
    }
    for role in ROLES:
        entry = roles[role]
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"} or not _hash(entry["sha256"]):
            raise PilotError("policy_role_shape")
        _, data = _file(repo, entry["path"])
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise PilotError("policy_source_drift")
        try:
            parsed = tomllib.loads(data.decode("utf-8"))
        except (UnicodeError, ValueError, tomllib.TOMLDecodeError) as exc:
            raise PilotError("role_semantic_drift") from exc
        wanted = "max" if arm == "all-max-control" else expected_reasoning[role]
        if parsed.get("name") != role or parsed.get("model") != "gpt-5.6-luna" or parsed.get("model_reasoning_effort") != wanted or parsed.get("service_tier") != "fast":
            raise PilotError("role_semantic_drift")


def _load_plan(plan_path: Path | str, repo_root: Path | str) -> Tuple[Dict[str, Any], bytes, str, Path]:
    repo = _root(repo_root)
    path = Path(plan_path).expanduser()
    if not path.is_absolute():
        path = repo / path
    value, raw = _read_json_file(path)
    if not isinstance(value, dict) or set(value) != PLAN_KEYS:
        raise PilotError("plan_shape")
    if value["schema_version"] != SCHEMA_VERSION or value["status"] != "frozen-before-first-start" or value["origin"] != ORIGIN:
        raise PilotError("plan_identity")
    if not _id(value["plan_id"]) or not _id(value["project_id"]) or _timestamp(value["created_at"]) is None or not isinstance(value["source_commit"], str) or COMMIT_RE.fullmatch(value["source_commit"]) is None:
        raise PilotError("plan_metadata")
    if (
        isinstance(value["sample_size"], bool)
        or not isinstance(value["sample_size"], int)
        or value["sample_size"] != 10
        or isinstance(value["minimum_families"], bool)
        or not isinstance(value["minimum_families"], int)
        or not 3 <= value["minimum_families"] <= len(FAMILIES)
        or value["assignment_method"] != "predeclared-matched-alternating"
    ):
        raise PilotError("plan_design")
    deadline = value["deadline_hours"]
    if (
        isinstance(deadline, bool)
        or not isinstance(deadline, (int, float))
        or not math.isfinite(deadline)
        or not 0.5 <= deadline <= 24 * 30
        or deadline * 2 != int(deadline * 2)
    ):
        raise PilotError("plan_deadline")
    policies = value["policies"]
    if not isinstance(policies, dict) or set(policies) != set(ARMS):
        raise PilotError("plan_policies")
    for arm in ARMS:
        _validate_policy(arm, policies[arm], repo)
    checkpoints = value["checkpoints"]
    if not isinstance(checkpoints, dict) or set(checkpoints) != CHECKPOINT_KEYS:
        raise PilotError("checkpoint_shape")
    numeric = {
        "terminal_coverage_required": (1.0, 1.0),
        "spawn_precision_min": (0.0, 1.0),
        "weighted_usage_reduction_target": (0.0, 1.0),
        "latency_noninferiority_margin": (0.0, 1.0),
    }
    for key, (low, high) in numeric.items():
        number = checkpoints[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not low <= number <= high:
            raise PilotError("checkpoint_value")
    dispositions = checkpoints["required_dispositions"]
    if (
        isinstance(checkpoints["critical_high_defect_regression_max"], bool)
        or checkpoints["critical_high_defect_regression_max"] != 0
        or not isinstance(dispositions, list)
        or len(dispositions) != len(DISPOSITIONS)
        or any(not isinstance(item, str) for item in dispositions)
        or set(dispositions) != DISPOSITIONS
        or checkpoints["promotion_requires_calibrated_or_replicated"] is not True
        or checkpoints["automatic_promotion"] is not False
    ):
        raise PilotError("checkpoint_value")
    required_kills = {
        "critical-or-high-defect-regression", "runtime-policy-drift",
        "privacy-or-security-failure", "receipt-or-attribution-integrity-failure",
    }
    kills = value["kill_criteria"]
    if not isinstance(kills, list) or len(kills) != len(required_kills) or any(not isinstance(item, str) for item in kills) or set(kills) != required_kills:
        raise PilotError("kill_criteria")
    slots = value["slots"]
    if not isinstance(slots, list) or len(slots) != 10:
        raise PilotError("slot_count")
    by_pair: Dict[str, List[Dict[str, Any]]] = {}
    ids: set[str] = set()
    families: set[str] = set()
    arm_counts = {arm: 0 for arm in ARMS}
    for index, slot in enumerate(slots, 1):
        if not isinstance(slot, dict) or set(slot) != SLOT_KEYS:
            raise PilotError("slot_shape")
        if isinstance(slot["sequence"], bool) or not isinstance(slot["sequence"], int) or slot["sequence"] != index or not _id(slot["slot_id"]) or not _id(slot["pair_id"]) or slot["slot_id"] in ids:
            raise PilotError("slot_identity")
        ids.add(slot["slot_id"])
        if slot["arm"] not in ARMS or slot["family"] not in FAMILIES or slot["size_risk_band"] not in RISK_BANDS:
            raise PilotError("slot_values")
        checks = slot["acceptance_check_ids"]
        if not isinstance(checks, list) or not checks or len(checks) != len(set(checks)) or any(not _id(item) for item in checks):
            raise PilotError("slot_checks")
        arm_counts[slot["arm"]] += 1
        families.add(slot["family"])
        by_pair.setdefault(slot["pair_id"], []).append(slot)
    if arm_counts != {arm: 5 for arm in ARMS} or len(families) < value["minimum_families"] or len(by_pair) != 5:
        raise PilotError("slot_balance")
    pair_first_arms: List[str] = []
    for pair_id in sorted(by_pair):
        pair = sorted(by_pair[pair_id], key=lambda item: item["sequence"])
        if len(pair) != 2 or {item["arm"] for item in pair} != set(ARMS) or len({item["family"] for item in pair}) != 1 or len({item["size_risk_band"] for item in pair}) != 1:
            raise PilotError("slot_pairing")
        pair_first_arms.append(pair[0]["arm"])
    if any(pair_first_arms[index] == pair_first_arms[index - 1] for index in range(1, len(pair_first_arms))):
        raise PilotError("slot_order_not_alternating")
    return value, raw, hashlib.sha256(raw).hexdigest(), repo


def verify_plan(plan_path: Path | str = DEFAULT_PLAN, repo_root: Path | str = DEFAULT_ROOT) -> Dict[str, Any]:
    plan, _, digest, _ = _load_plan(plan_path, repo_root)
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan["plan_id"],
        "plan_sha256": digest,
        "sample_size": plan["sample_size"],
        "deadline_minutes": int(plan["deadline_hours"] * 60),
        "family_count": len({slot["family"] for slot in plan["slots"]}),
        "arm_counts": {arm: sum(slot["arm"] == arm for slot in plan["slots"]) for arm in ARMS},
        "source_integrity": True,
    }


def _environment_manifest(plan: Dict[str, Any], plan_hash: str, arm: str) -> bytes:
    policy = plan["policies"][arm]
    expected = {
        "bundle_version": policy["bundle_version"],
        "policy_sha256": policy["policy_sha256"],
        "agents_sha256": policy["agents_sha256"],
        "config_sha256": policy["config_sha256"],
        "rate_card_sha256": policy["rate_card_sha256"],
        "roles": {role: policy["roles"][role]["sha256"] for role in ROLES},
    }
    return _canonical({
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan["plan_id"],
        "plan_sha256": plan_hash,
        "arm": arm,
        "environment_label": policy["environment_label"],
        "expected": expected,
        "origin": ORIGIN,
    })


def _environment_writes(plan: Dict[str, Any], plan_hash: str, repo: Path, pilot_home: Path) -> Dict[str, Dict[Path, bytes]]:
    result: Dict[str, Dict[Path, bytes]] = {}
    for arm in ARMS:
        policy = plan["policies"][arm]
        codex_home = pilot_home / policy["environment_label"] / ".codex"
        writes: Dict[Path, bytes] = {}
        writes[codex_home / "AGENTS.md"] = _file(repo, policy["agents_path"])[1]
        writes[codex_home / "config.toml"] = _file(repo, policy["config_path"])[1]
        for role in ROLES:
            writes[codex_home / "agents" / f"{role}.toml"] = _file(repo, policy["roles"][role]["path"])[1]
        writes[codex_home / ENV_MANIFEST] = _environment_manifest(plan, plan_hash, arm)
        result[arm] = writes
    return result


def setup_environments(
    plan_path: Path | str,
    repo_root: Path | str,
    pilot_home: Path | str,
    *,
    apply: bool,
) -> Dict[str, Any]:
    plan, _, plan_hash, repo = _load_plan(plan_path, repo_root)
    home = _pilot_home(pilot_home, repo)
    writes_by_arm = _environment_writes(plan, plan_hash, repo, home)
    planned: List[Tuple[Path, bytes, str]] = []
    for arm, writes in writes_by_arm.items():
        for path, data in writes.items():
            if path.exists() or platform_fs.is_link_like(path):
                if platform_fs.is_link_like(path) or not path.is_file() or _has_symlink(path):
                    raise PilotError("environment_destination_unsafe")
                if path.read_bytes() != data or not platform_fs.mode_matches(path, 0o600):
                    raise PilotError("environment_conflict")
            else:
                planned.append((path, data, arm))
    report = {
        "ok": True,
        "status": "planned" if not apply else "applied",
        "plan_id": plan["plan_id"],
        "write_count": len(planned),
        "changes": [
            {"arm": arm, "path": str(path.relative_to(home)).replace("\\", "/"), "action": "create"}
            for path, _, arm in sorted(planned, key=lambda item: str(item[0]))
        ],
        "credentials_copied": False,
        "sessions_copied": False,
    }
    if not apply:
        report["status"] = "dry-run"
        return report
    created_files: List[Path] = []
    created_dirs: set[Path] = set()
    for path, _, _ in planned:
        parent = path.parent
        while parent != parent.parent and not parent.exists():
            created_dirs.add(parent)
            parent = parent.parent
    try:
        _ensure_directory(home)
        for path, data, _ in planned:
            _atomic_write(path, data)
            created_files.append(path)
        verification = verify_environments(plan_path, repo_root, home)
        if not verification["ok"]:
            raise PilotError("environment_verification_failed")
    except Exception as exc:
        for path in reversed(created_files):
            try:
                path.unlink()
            except OSError:
                pass
        for directory in sorted(created_dirs, key=lambda item: len(item.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        if isinstance(exc, PilotError):
            raise
        raise PilotError("environment_setup_failed") from exc
    report["verification"] = verification
    return report


def verify_environments(plan_path: Path | str, repo_root: Path | str, pilot_home: Path | str) -> Dict[str, Any]:
    plan, _, plan_hash, repo = _load_plan(plan_path, repo_root)
    home = _pilot_home(pilot_home, repo)
    if not home.is_dir():
        raise PilotError("root_missing")
    expected = _environment_writes(plan, plan_hash, repo, home)
    arms: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    for arm, writes in expected.items():
        matches = 0
        for path, data in writes.items():
            try:
                if path.is_file() and not platform_fs.is_link_like(path) and not _has_symlink(path) and platform_fs.mode_matches(path, 0o600) and path.read_bytes() == data:
                    matches += 1
                else:
                    errors.append("environment_drift")
            except OSError:
                errors.append("environment_drift")
        arms[arm] = {"ok": matches == len(writes), "matches": matches, "expected": len(writes)}
    return {"ok": not errors and all(value["ok"] for value in arms.values()), "plan_id": plan["plan_id"], "arms": arms, "errors": sorted(set(errors))}


def _expected(plan: Dict[str, Any], arm: str) -> Dict[str, Any]:
    policy = plan["policies"][arm]
    return {
        "bundle_version": policy["bundle_version"],
        "policy_sha256": policy["policy_sha256"],
        "agents_sha256": policy["agents_sha256"],
        "config_sha256": policy["config_sha256"],
        "rate_card_sha256": policy["rate_card_sha256"],
        "roles": {role: policy["roles"][role]["sha256"] for role in ROLES},
    }


def _validate_start(value: Any, plan: Dict[str, Any], plan_hash: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != START_KEYS or value["schema_version"] != SCHEMA_VERSION or value["origin"] != ORIGIN:
        raise PilotError("start_shape")
    if value["plan_id"] != plan["plan_id"] or value["plan_sha256"] != plan_hash or not _hash(value["plan_sha256"]):
        raise PilotError("start_plan_drift")
    if value["project_id"] != plan["project_id"] or value["source_commit"] != plan["source_commit"]:
        raise PilotError("start_source_drift")
    body = {key: child for key, child in value.items() if key != "start_id"}
    expected_id = "ps1-" + hashlib.sha256(_canonical(body)).hexdigest()
    if value["start_id"] != expected_id:
        raise PilotError("start_id_invalid")
    slots = {slot["slot_id"]: slot for slot in plan["slots"]}
    slot = slots.get(value["slot_id"])
    if slot is None or any(value[key] != slot[key] for key in ("sequence", "pair_id", "arm", "family", "size_risk_band", "acceptance_check_ids")):
        raise PilotError("start_slot_drift")
    if not _id(value["milestone_id"]) or not _id(value["codex_task_id"]):
        raise PilotError("start_identity")
    started = _timestamp(value["started_at"])
    due = _timestamp(value["due_at"])
    if started is None or due is None or due != started + timedelta(hours=plan["deadline_hours"]):
        raise PilotError("start_time")
    if not isinstance(value["expected"], dict) or set(value["expected"]) != EXPECTED_KEYS or value["expected"] != _expected(plan, value["arm"]):
        raise PilotError("start_expected_drift")
    return value


def _load_starts(starts_dir: Path, plan: Dict[str, Any], plan_hash: str) -> List[Dict[str, Any]]:
    if not starts_dir.exists():
        return []
    if platform_fs.is_link_like(starts_dir) or _has_symlink(starts_dir) or not starts_dir.is_dir() or not platform_fs.mode_matches(starts_dir, 0o700):
        raise PilotError("starts_directory_unsafe")
    starts: List[Dict[str, Any]] = []
    for path in sorted(starts_dir.iterdir(), key=lambda item: item.name):
        if path.suffix != ".json":
            raise PilotError("unexpected_start_file")
        value, _ = _read_json_file(path, require_mode=0o600)
        validated = _validate_start(value, plan, plan_hash)
        if path.name != f"{validated['slot_id']}.json":
            raise PilotError("start_filename_drift")
        starts.append(validated)
    slot_ids = [item["slot_id"] for item in starts]
    task_ids = [item["codex_task_id"] for item in starts]
    milestone_ids = [item["milestone_id"] for item in starts]
    if len(slot_ids) != len(set(slot_ids)) or len(task_ids) != len(set(task_ids)) or len(milestone_ids) != len(set(milestone_ids)):
        raise PilotError("duplicate_start_identity")
    sequences = sorted(item["sequence"] for item in starts)
    if sequences != list(range(1, len(starts) + 1)):
        raise PilotError("start_sequence_gap")
    return sorted(starts, key=lambda item: item["sequence"])


def register_start(
    plan_path: Path | str,
    repo_root: Path | str,
    pilot_home: Path | str,
    starts_dir: Path | str,
    slot_id: str,
    milestone_id: str,
    codex_task_id: str,
    started_at: str,
    receipts_dir: Path | str = ".sol-luna/receipts",
) -> Dict[str, Any]:
    plan, _, plan_hash, repo = _load_plan(plan_path, repo_root)
    environment = verify_environments(plan_path, repo, pilot_home)
    if not environment["ok"]:
        raise PilotError("environment_drift")
    slots = {slot["slot_id"]: slot for slot in plan["slots"]}
    slot = slots.get(slot_id)
    if slot is None or not _id(milestone_id) or not _id(codex_task_id):
        raise PilotError("start_input")
    started = _timestamp(started_at)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    created = _timestamp(plan["created_at"])
    if started is None or created is None or started < created or started > now + timedelta(minutes=5):
        raise PilotError("start_time")
    starts_path = _data_directory(starts_dir, repo)
    existing = _load_starts(starts_path, plan, plan_hash) if starts_path.exists() else []
    already = next((item for item in existing if item["slot_id"] == slot_id), None)
    if already is not None:
        if already["milestone_id"] == milestone_id and already["codex_task_id"] == codex_task_id and already["started_at"] == started_at:
            return {"ok": True, "start_id": already["start_id"], "slot_id": slot_id, "arm": slot["arm"], "idempotent": True}
        raise PilotError("start_conflict")
    receipts_path = _data_directory(receipts_dir, repo)
    current = summarize_pilot(plan_path, repo, starts_path, receipts_path, pilot_home, _utc(now))
    if (
        current["errors"]
        or current["overdue_count"]
        or current["pending_count"]
        or current["terminal_count"] != len(existing)
        or current["kill_criteria_triggered"]
    ):
        raise PilotError("prior_window_blocked")
    if existing and current["latest_terminal_closed_at"] is not None and started < _timestamp(current["latest_terminal_closed_at"]):
        raise PilotError("start_time")
    body: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan["plan_id"],
        "project_id": plan["project_id"],
        "plan_sha256": plan_hash,
        "source_commit": plan["source_commit"],
        "slot_id": slot["slot_id"],
        "sequence": slot["sequence"],
        "pair_id": slot["pair_id"],
        "arm": slot["arm"],
        "family": slot["family"],
        "size_risk_band": slot["size_risk_band"],
        "milestone_id": milestone_id,
        "codex_task_id": codex_task_id,
        "started_at": started_at,
        "due_at": _utc(started + timedelta(hours=plan["deadline_hours"])),
        "acceptance_check_ids": slot["acceptance_check_ids"],
        "expected": _expected(plan, slot["arm"]),
        "origin": ORIGIN,
    }
    record = dict(body)
    record["start_id"] = "ps1-" + hashlib.sha256(_canonical(body)).hexdigest()
    record = {key: record[key] for key in START_KEYS}
    target = starts_path / f"{slot_id}.json"
    if target.exists():
        value, raw = _read_json_file(target, require_mode=0o600)
        validated = _validate_start(value, plan, plan_hash)
        if validated == record:
            return {"ok": True, "start_id": record["start_id"], "slot_id": slot_id, "arm": slot["arm"], "idempotent": True}
        raise PilotError("start_conflict")
    if any(item["slot_id"] == slot_id or item["milestone_id"] == milestone_id or item["codex_task_id"] == codex_task_id for item in existing):
        raise PilotError("start_conflict")
    if slot["sequence"] != len(existing) + 1:
        raise PilotError("start_out_of_order")
    _ensure_directory(starts_path)
    _atomic_write(target, _canonical(record))
    return {"ok": True, "start_id": record["start_id"], "slot_id": slot_id, "arm": slot["arm"], "idempotent": False}


def _load_receipts(receipts_dir: Path) -> Tuple[List[Dict[str, Any]], int]:
    if not receipts_dir.exists():
        return [], 0
    if platform_fs.is_link_like(receipts_dir) or _has_symlink(receipts_dir) or not receipts_dir.is_dir() or not platform_fs.mode_matches(receipts_dir, 0o700):
        raise PilotError("receipts_directory_unsafe")
    receipts: List[Dict[str, Any]] = []
    invalid = 0
    for path in sorted(receipts_dir.iterdir(), key=lambda item: item.name):
        if path.suffix != ".json":
            continue
        try:
            value, _ = _read_json_file(path, require_mode=0o600)
            if receipt_tool.validate_receipt(value).get("ok"):
                receipts.append(value)
            else:
                invalid += 1
        except (PilotError, OSError, ValueError):
            invalid += 1
    return receipts, invalid


def _receipt_matches_start(receipt: Dict[str, Any], start: Dict[str, Any]) -> bool:
    if receipt.get("milestone_id") != start["milestone_id"] or receipt.get("codex_task_id") != start["codex_task_id"]:
        return False
    if receipt.get("project_id") != start["project_id"] or receipt.get("family") != start["family"] or receipt.get("size_risk_band") != start["size_risk_band"] or receipt.get("started_at") != start["started_at"]:
        raise PilotError("receipt_start_drift")
    repository = receipt.get("repository", {})
    hashes = repository.get("hashes", {}) if isinstance(repository, dict) else {}
    expected = start["expected"]
    if repository.get("base_commit") != start["source_commit"] or repository.get("bundle_version") != expected["bundle_version"]:
        raise PilotError("receipt_policy_drift")
    if any(hashes.get(key) != expected[f"{key}_sha256"] for key in ("agents", "policy", "config", "rate_card")):
        raise PilotError("receipt_policy_drift")
    if hashes.get("roles") != expected["roles"]:
        raise PilotError("receipt_policy_drift")
    checks = receipt.get("acceptance_checks", [])
    check_id_list = [item.get("id") for item in checks if isinstance(item, dict)]
    if len(check_id_list) != len(checks) or len(check_id_list) != len(set(check_id_list)) or set(check_id_list) != set(start["acceptance_check_ids"]):
        raise PilotError("receipt_check_drift")
    return True


def summarize_pilot(
    plan_path: Path | str,
    repo_root: Path | str,
    starts_dir: Path | str,
    receipts_dir: Path | str,
    pilot_home: Optional[Path | str] = None,
    as_of: Optional[str] = None,
) -> Dict[str, Any]:
    plan, _, plan_hash, repo = _load_plan(plan_path, repo_root)
    starts_path = _data_directory(starts_dir, repo)
    receipts_path = _data_directory(receipts_dir, repo)
    now = _timestamp(as_of) if as_of is not None else datetime.now(timezone.utc).replace(microsecond=0)
    if now is None:
        raise PilotError("as_of_invalid")
    starts = _load_starts(starts_path, plan, plan_hash) if starts_path.exists() else []
    receipts, invalid_receipts = _load_receipts(receipts_path)
    errors: List[str] = ["invalid_receipts"] if invalid_receipts else []
    matched_receipt_ids: set[str] = set()
    terminal: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    pending = 0
    overdue = 0
    for start in starts:
        candidates = [receipt for receipt in receipts if receipt.get("milestone_id") == start["milestone_id"] and receipt.get("codex_task_id") == start["codex_task_id"]]
        if len(candidates) > 1:
            errors.append("duplicate_terminal_receipt")
            continue
        if not candidates:
            if _timestamp(start["due_at"]) <= now:
                overdue += 1
            else:
                pending += 1
            continue
        receipt = candidates[0]
        try:
            _receipt_matches_start(receipt, start)
            closed = _timestamp(receipt.get("closed_at"))
            if closed is None or closed > now:
                raise PilotError("receipt_from_future")
            if closed > _timestamp(start["due_at"]):
                raise PilotError("receipt_after_deadline")
        except PilotError as exc:
            errors.append(exc.code)
            continue
        matched_receipt_ids.add(receipt["receipt_id"])
        terminal.append((start, receipt))
    environment = None
    if pilot_home is not None:
        environment = verify_environments(plan_path, repo, pilot_home)
        if not environment["ok"]:
            errors.append("environment_drift")
    coverage_fraction = (len(terminal) / len(starts)) if starts else None
    if errors:
        coverage_status, coverage_reason = "unknown", "pilot_integrity_failure"
    elif overdue:
        coverage_status, coverage_reason = "incomplete", "overdue_without_terminal_receipt"
    elif len(terminal) == plan["sample_size"] and len(starts) == plan["sample_size"]:
        coverage_status, coverage_reason = "complete", "all_registered_starts_terminal"
    elif starts:
        coverage_status, coverage_reason = "in-progress", "registered_starts_pending"
    else:
        coverage_status, coverage_reason = "not-started", "no_registered_starts"
    arm_rows: Dict[str, Dict[str, Any]] = {}
    for arm in ARMS:
        rows = [(start, receipt) for start, receipt in terminal if start["arm"] == arm]
        lanes = [lane for _, receipt in rows for lane in receipt.get("delegated_lanes", [])]
        durations = [
            int((_timestamp(receipt["closed_at"]) - _timestamp(start["started_at"])).total_seconds() * 1000)
            for start, receipt in rows
        ]
        complete_usage = bool(rows) and all(receipt["usage"]["coverage"] == "complete-full-workflow" for _, receipt in rows)
        weighted = sum(float(receipt["usage"]["weighted_usage"]) for _, receipt in rows) if complete_usage else None
        arm_rows[arm] = {
            "registered": sum(start["arm"] == arm for start in starts),
            "terminal": len(rows),
            "accepted": sum(receipt["disposition"] == "accepted" for _, receipt in rows),
            "rejected": sum(receipt["disposition"] == "rejected" for _, receipt in rows),
            "abandoned": sum(receipt["disposition"] == "abandoned" for _, receipt in rows),
            "critical_high_open_risks": sum(
                risk.get("status") == "open" and risk.get("severity") in {"high", "critical"}
                for _, receipt in rows for risk in receipt.get("risks", [])
            ),
            "spawn_precision": (sum(bool(lane.get("useful")) for lane in lanes) / len(lanes)) if lanes else None,
            "median_terminal_ms": int(median(durations)) if durations else None,
            "weighted_usage": weighted,
            "weighted_usage_status": "complete" if complete_usage else "unknown",
        }
    complete_window = coverage_status == "complete" and not errors
    control = arm_rows["all-max-control"]
    dynamic = arm_rows["dynamic-v0.2.1"]
    reduction = None
    if complete_window and control["weighted_usage"] is not None and dynamic["weighted_usage"] is not None and control["weighted_usage"] > 0:
        reduction = (control["weighted_usage"] - dynamic["weighted_usage"]) / control["weighted_usage"]
    latency_noninferior = None
    if complete_window and control["median_terminal_ms"] is not None and dynamic["median_terminal_ms"] is not None:
        latency_noninferior = dynamic["median_terminal_ms"] <= control["median_terminal_ms"] * (1 + plan["checkpoints"]["latency_noninferiority_margin"])
    required_dispositions = set(plan["checkpoints"]["required_dispositions"])
    observed_dispositions = {receipt["disposition"] for _, receipt in terminal}
    dispositions_complete = required_dispositions.issubset(observed_dispositions) if complete_window else False
    overall_lanes = [lane for _, receipt in terminal for lane in receipt.get("delegated_lanes", [])]
    overall_precision = (sum(bool(lane.get("useful")) for lane in overall_lanes) / len(overall_lanes)) if overall_lanes else None
    quality_noninferior = None
    if complete_window:
        quality_noninferior = dynamic["critical_high_open_risks"] <= control["critical_high_open_risks"] and dynamic["critical_high_open_risks"] == 0
    kill_criteria_triggered: set[str] = set()
    for _, receipt in terminal:
        for risk in receipt.get("risks", []):
            if risk.get("severity") in {"high", "critical"} and risk.get("status") == "open":
                kill_criteria_triggered.add("critical-or-high-defect-regression")
            if risk.get("code") in {"privacy", "security"}:
                kill_criteria_triggered.add("privacy-or-security-failure")
            if risk.get("code") == "runtime_drift":
                kill_criteria_triggered.add("runtime-policy-drift")
    if errors:
        kill_criteria_triggered.add("receipt-or-attribution-integrity-failure")
    if "environment_drift" in errors or "receipt_policy_drift" in errors:
        kill_criteria_triggered.add("runtime-policy-drift")
    comparison_fields_complete = complete_window and dispositions_complete and all(
        value is not None
        for value in (reduction, latency_noninferior, quality_noninferior, overall_precision)
    )
    comparison = {
        "status": "observed" if comparison_fields_complete else "partial" if complete_window else "unknown",
        "weighted_usage_reduction": reduction,
        "weighted_usage_target_met": reduction >= plan["checkpoints"]["weighted_usage_reduction_target"] if reduction is not None else None,
        "latency_noninferior": latency_noninferior,
        "quality_noninferior": quality_noninferior,
        "spawn_precision": overall_precision,
        "spawn_precision_target_met": overall_precision >= plan["checkpoints"]["spawn_precision_min"] if overall_precision is not None else None,
        "required_dispositions_observed": dispositions_complete if complete_window else None,
        "automatic_promotion": False,
        "promotion_status": (
            "kill-criteria-triggered"
            if kill_criteria_triggered
            else "human-review-required"
            if comparison_fields_complete
            else "evidence-incomplete-human-review"
            if complete_window
            else "blocked-or-unknown"
        ),
    }
    if errors or overdue or kill_criteria_triggered:
        state = "blocked"
    elif complete_window:
        state = "checkpoint-ready"
    elif starts:
        state = "in-progress"
    else:
        state = "setup-unverified" if environment is None else "ready"
    next_slot = None
    if len(starts) < plan["sample_size"]:
        slot = plan["slots"][len(starts)]
        next_slot = {key: slot[key] for key in ("slot_id", "sequence", "arm", "family", "size_risk_band")}
    return {
        "ok": not errors and not overdue and not kill_criteria_triggered and (environment is None or environment.get("ok")),
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan["plan_id"],
        "plan_sha256": plan_hash,
        "state": state,
        "registered_count": len(starts),
        "unregistered_count": plan["sample_size"] - len(starts),
        "terminal_count": len(terminal),
        "pending_count": pending,
        "overdue_count": overdue,
        "receipt_coverage": coverage_status,
        "receipt_coverage_reason": coverage_reason,
        "receipt_coverage_fraction": coverage_fraction,
        "invalid_receipts": invalid_receipts,
        "unmatched_receipts": len(receipts) - len(matched_receipt_ids),
        "latest_terminal_closed_at": max((receipt["closed_at"] for _, receipt in terminal), default=None),
        "kill_criteria_triggered": sorted(kill_criteria_triggered),
        "next_slot": next_slot,
        "next_slot_eligible": bool(
            next_slot
            and not errors
            and not overdue
            and not pending
            and not kill_criteria_triggered
            and len(terminal) == len(starts)
            and environment is not None
            and environment.get("ok")
        ),
        "arms": arm_rows,
        "comparison": comparison,
        "environment": environment,
        "errors": sorted(set(errors)),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--plan", default="config/m4-pilot.v1.json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify-plan")
    setup = sub.add_parser("setup-environments")
    setup.add_argument("--pilot-home", required=True)
    mode = setup.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    verify = sub.add_parser("verify-environments")
    verify.add_argument("--pilot-home", required=True)
    register = sub.add_parser("register-start")
    register.add_argument("--pilot-home", required=True)
    register.add_argument("--starts-dir", default=".sol-luna/starts")
    register.add_argument("--slot", required=True)
    register.add_argument("--milestone-id", required=True)
    register.add_argument("--codex-task-id", required=True)
    register.add_argument("--started-at", required=True)
    register.add_argument("--receipts-dir", default=".sol-luna/receipts")
    status = sub.add_parser("status")
    status.add_argument("--starts-dir", default=".sol-luna/starts")
    status.add_argument("--receipts-dir", default=".sol-luna/receipts")
    status.add_argument("--pilot-home")
    status.add_argument("--as-of")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = Path(args.root)
        plan = Path(args.plan)
        if args.command == "verify-plan":
            result = verify_plan(plan, root)
        elif args.command == "setup-environments":
            result = setup_environments(plan, root, args.pilot_home, apply=args.apply)
        elif args.command == "verify-environments":
            result = verify_environments(plan, root, args.pilot_home)
        elif args.command == "register-start":
            result = register_start(plan, root, args.pilot_home, args.starts_dir, args.slot, args.milestone_id, args.codex_task_id, args.started_at, args.receipts_dir)
        else:
            result = summarize_pilot(plan, root, args.starts_dir, args.receipts_dir, args.pilot_home, args.as_of)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result.get("ok") else 1
    except (PilotError, OSError, UnicodeError, MemoryError, OverflowError, RecursionError, TypeError, ValueError) as exc:
        code = exc.code if isinstance(exc, PilotError) else "operation_failed"
        print(json.dumps({"ok": False, "errors": [code]}, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
