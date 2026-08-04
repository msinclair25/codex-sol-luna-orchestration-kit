#!/usr/bin/env python3
"""Verify and evaluate the versioned Sol/Luna routing policy.

This module is deliberately advisory.  It validates a checked-in contract,
evaluates bounded JSON routing requests, and evaluates one post-admission
transport fallback.  It never launches agents, creates Codex app tasks, or
edits a worktree.  Invalid input, unsupported combinations, ownership
conflicts, runtime drift, and ineligible fallback events fail closed to direct
Sol work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import tomllib
except ImportError:  # pragma: no cover - supported Python versions include it.
    tomllib = None  # type: ignore[assignment]


SCHEMA_VERSION = 1
POLICY_VERSION = "routing-policy.v1.2"
DEFAULT_ROOT = Path(__file__).resolve().parents[1]
POLICY_RELATIVE = "config/routing-policy.v1.2.json"
POLICY_AGENTS_RELATIVE = "AGENTS.override.md"
AGENTS_RELATIVE = "AGENTS.md"
MANAGED_AGENTS_START = "# >>> sol-luna-orchestration-kit managed block >>>\n"
MANAGED_AGENTS_END = "# <<< sol-luna-orchestration-kit managed block <<<\n"
AGENTS_OVERRIDE_RELATIVE = "AGENTS.override.md"
SNIPPET_RELATIVE = "config-snippet.toml"
MIN_PYTHON = (3, 11)
PYTHON_REQUIREMENT = "Python >=3.11 is required for deterministic TOML contract verification"
MAX_ROUTE_INPUT_BYTES = 64 * 1024
MAX_OWNERSHIP_LANES = 1000
MAX_OWNERSHIP_ENTRIES = 2048
MAX_CONFLICTS = 256
MAX_LANES = 3
MAX_CONCURRENT_LANES = MAX_LANES
LUNA_TRANSPORT = {
    "fork_turns": "none",
    "history_inherited": False,
    "assignment": "self-contained",
    "nested_delegation": False,
    "on_spawn_error": "evaluate_transport_failure",
    "retry_spawn": False,
}
ELIGIBLE_NATIVE_FAILURE_CODES = (
    "custom_role_rejected",
    "custom_role_unavailable",
    "native_spawn_tool_unavailable",
    "native_spawn_transport_error",
)
APP_TASK_FALLBACK = {
    "target": "codex_app_task",
    "requires_explicit_user_authorization": True,
    "authorization_scope": "this_lane_once",
    "max_attempts_per_lane": 1,
    "current_checkout_only": True,
    "requires_canonical_project_root_match": True,
    "user_visible": True,
    "recursive": False,
    "on_unavailable": "sol",
    "on_ineligible": "sol",
    "eligible_failure_codes": list(ELIGIBLE_NATIVE_FAILURE_CODES),
}
APP_TASK_TRANSPORT = {
    "surface": "codex_app",
    "kind": "task",
    "environment": "local_current_checkout",
    "history_inherited": False,
    "assignment": "same_self_contained_capsule",
    "user_visible": True,
    "max_attempts": 1,
    "recursive_fallback": False,
    "on_create_error": "sol",
}
MAX_UPGRADE_REASON_CODES = (
    "genuine_ambiguity",
    "cross_cutting_risk",
    "failed_high_attempt",
    "high_impact_adversarial_review",
)
SPLIT_FIELDS = (
    "separate",
    "provable",
    "large_enough",
    "isolated",
    "tier_appropriate",
)
SPLIT_LABELS = ("Separate", "Provable", "Large enough", "Isolated", "Tier-appropriate")
EVIDENCE_FIELDS = (
    "scope",
    "files_or_surfaces",
    "commands_or_checks",
    "assumptions",
    "failures",
    "risks",
    "confidence",
    "recommendation",
)
SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
SAFE_RELATIVE = re.compile(r"^[A-Za-z0-9._/-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_NAME = re.compile(
    r"(?:^|[._-])(secret|secrets|credential|credentials|token|tokens|password|passwd|api[_-]?key|access[_-]?key|private[_-]?key)(?:$|[._-])",
    re.IGNORECASE,
)
_SENSITIVE_COMPONENTS = {
    ".git",
    ".aws",
    ".gnupg",
    ".ssh",
    "keys",
    "key",
    "cert",
    "certs",
    "certificate",
    "certificates",
    "credentials",
    "secrets",
    "tokens",
    "keystore",
    "truststore",
    "key-store",
    "cert-store",
    "customer_data",
    "production_data",
}
_SENSITIVE_FILENAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
_SENSITIVE_EXTENSIONS = {
    ".key",
    ".pem",
    ".crt",
    ".cer",
    ".der",
    ".p12",
    ".pfx",
    ".jks",
}

# These values are public policy data and intentionally duplicated in the
# generated contract so a malformed contract cannot silently broaden routing.
ROLE_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "scout": {
        "role": "luna_scout_fast",
        "path": "agents/luna_scout_fast.toml",
        "model": "gpt-5.6-luna",
        "reasoning": "medium",
        "service_tier": "fast",
        "sandbox_mode": "read-only",
    },
    "worker": {
        "role": "luna_worker_fast",
        "path": "agents/luna_worker_fast.toml",
        "model": "gpt-5.6-luna",
        "reasoning": "high",
        "service_tier": "fast",
        "sandbox_mode": "workspace-write",
    },
    "critic": {
        "role": "luna_critic_fast",
        "path": "agents/luna_critic_fast.toml",
        "model": "gpt-5.6-luna",
        "reasoning": "high",
        "service_tier": "fast",
        "sandbox_mode": "read-only",
    },
    "tester": {
        "role": "luna_tester_fast",
        "path": "agents/luna_tester_fast.toml",
        "model": "gpt-5.6-luna",
        "reasoning": "medium",
        "service_tier": "fast",
        "sandbox_mode": "workspace-write",
    },
    "max": {
        "role": "luna_max_fast",
        "path": "agents/luna_max_fast.toml",
        "model": "gpt-5.6-luna",
        "reasoning": "max",
        "service_tier": "fast",
        "sandbox_mode": "read-only",
    },
}

KIND_ALIASES = {
    "scout": "scout",
    "mapping": "scout",
    "map": "scout",
    "worker": "worker",
    "implementation": "worker",
    "write": "worker",
    "build": "worker",
    "critic": "critic",
    "review": "critic",
    "adversarial_review": "critic",
    "tester": "tester",
    "test": "tester",
    "validation": "tester",
    "validate": "tester",
    "analysis": "max",
    "max": "max",
}
REQUEST_FIELDS = {
    "kind",
    "profile",
    "split",
    *SPLIT_FIELDS,
    "ownership",
    "lane_count",
    "wave_count",
    "requested_role",
    "max_upgrade_reason",
    "model",
    "reasoning",
    "service_tier",
    "sandbox_mode",
    "fork_turns",
    "evidence",
}
FALLBACK_EVENT_FIELDS = {
    "routing_request",
    "fallback_authorization",
    "failure_code",
    "attempts_used",
    "app_task_available",
    "project_context",
}
FALLBACK_AUTHORIZATION_FIELDS = {
    "authorized",
    "target",
    "scope",
    "lane_id",
    "max_attempts",
    "current_checkout",
}
PROJECT_CONTEXT_FIELDS = {
    "current_checkout_root",
    "app_project_root",
}

STANDARD_ROLE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    kind: {
        **definition,
        "role": definition["role"].removesuffix("_fast") + "_standard",
        "path": definition["path"].removesuffix("_fast.toml") + "_standard.toml",
        "service_tier": "standard",
        "service_tier_configured": False,
    }
    for kind, definition in ROLE_DEFINITIONS.items()
}
PROFILE_SPECS: Dict[str, Dict[str, Any]] = {
    "fast": {
        "policy_relative": POLICY_RELATIVE,
        "agents_relative": POLICY_AGENTS_RELATIVE,
        "snippet_relative": SNIPPET_RELATIVE,
        "roles": ROLE_DEFINITIONS,
    },
    "standard": {
        "policy_relative": "config/routing-policy.standard.v1.2.json",
        "agents_relative": "profiles/standard/AGENTS.override.md",
        "snippet_relative": "profiles/standard/config-snippet.toml",
        "roles": STANDARD_ROLE_DEFINITIONS,
    },
}


def profile_spec(profile: str) -> Dict[str, Any]:
    """Return one immutable profile description or fail closed."""

    if profile not in PROFILE_SPECS:
        raise ValueError("unsupported_profile")
    spec = PROFILE_SPECS[profile]
    return {
        "name": profile,
        "policy_relative": spec["policy_relative"],
        "agents_relative": spec["agents_relative"],
        "snippet_relative": spec["snippet_relative"],
        "roles": {kind: dict(value) for kind, value in spec["roles"].items()},
    }


def _sol_fallback(reason_codes: Iterable[str], *, errors: Iterable[str] = ()) -> Dict[str, Any]:
    reasons = sorted({value for value in reason_codes if isinstance(value, str)})
    error_values = sorted({value for value in errors if isinstance(value, str)})
    return {
        "ok": False,
        "decision": "direct",
        "route": "sol",
        "role": "sol",
        "model": "gpt-5.6-sol",
        "reasoning": "user-selected",
        "service_tier": "standard",
        "service_tier_configured": False,
        "fallback": True,
        "reason_codes": reasons or ["unsupported_request"],
        "errors": error_values,
        "policy_version": POLICY_VERSION,
    }


def _safe_relative(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value or len(value) > 160:
        return None
    if "\x00" in value or value.startswith("/") or "\\" in value:
        return None
    if not SAFE_RELATIVE.fullmatch(value):
        return None
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix() != value:
        return None
    if any(part in ("", ".", "..") for part in parsed.parts):
        return None
    return value


def _is_sensitive_ownership_path(relative: str) -> bool:
    parsed = PurePosixPath(relative)
    parts = [part.lower() for part in parsed.parts]
    filename = parts[-1]
    if any(part == ".git" or part in _SENSITIVE_COMPONENTS for part in parts):
        return True
    if any(part.startswith(".env") for part in parts):
        return True
    if filename in _SENSITIVE_FILENAMES:
        return True
    if filename.endswith(".log") or filename.endswith(".customer") or filename.endswith(".production"):
        return True
    if Path(filename).suffix.lower() in _SENSITIVE_EXTENSIONS:
        return True
    if _SENSITIVE_NAME.search(filename):
        return True
    if any(re.search(r"(?:^|[._-])(customer|customers|production|prod)(?:$|[._-])", part) for part in parts):
        return True
    return False


def _safe_ownership_relative(value: Any) -> Optional[str]:
    relative = _safe_relative(value)
    if relative is None or _is_sensitive_ownership_path(relative):
        return None
    return relative


def _safe_id(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and SAFE_ID.fullmatch(value) else None


def _bounded_text(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 2000
        and (allow_empty or bool(value.strip()))
        and "\x00" not in value
    )


def _bounded_text_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= 100
        and all(_bounded_text(item) for item in value)
    )


def validate_evidence(evidence: Any) -> bool:
    """Validate the compact evidence packet required from every delegated lane."""

    if not isinstance(evidence, dict) or set(evidence) != set(EVIDENCE_FIELDS):
        return False
    if not _bounded_text(evidence["scope"]):
        return False
    for field in ("files_or_surfaces", "commands_or_checks", "assumptions", "failures", "risks"):
        if not _bounded_text_list(evidence[field]):
            return False
    if not _bounded_text(evidence["confidence"]):
        return False
    return _bounded_text(evidence["recommendation"])


def _safe_path(root: Path, relative: str) -> Optional[Path]:
    """Resolve a regular non-symlink repository-relative file safely."""

    if _safe_relative(relative) is None:
        return None
    try:
        root = root.resolve()
        candidate = root.joinpath(*relative.split("/"))
        current = root
        for part in relative.split("/"):
            current = current / part
            if current.is_symlink():
                return None
        if not candidate.is_file() or candidate.is_symlink():
            return None
        candidate.resolve().relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


class _DuplicateJSONKey(ValueError):
    """Raised when strict route JSON contains a repeated object key."""


def _strict_json_loads(raw: str) -> Any:
    if not isinstance(raw, str):
        raise ValueError("route input must be text")
    try:
        size = len(raw.encode("utf-8"))
    except (UnicodeError, MemoryError, OverflowError) as exc:
        raise ValueError("route input encoding failed") from exc
    if size > MAX_ROUTE_INPUT_BYTES:
        raise ValueError("route input exceeds 64KiB")

    def reject_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJSONKey("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=reject_duplicate_keys)


def parse_route_input(raw: str) -> Any:
    """Parse one bounded route request with duplicate-key rejection."""

    return _strict_json_loads(raw)


def _hash_file(path: Optional[Path]) -> Optional[Tuple[str, int]]:
    if path is None:
        return None
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except (OSError, UnicodeError):
        return None
    return digest.hexdigest(), size


def _agents_match(actual: Optional[Path], repository: Optional[Path]) -> Tuple[bool, bool]:
    """Accept an exact AGENTS file or one exact, uniquely delimited managed block.

    Repository verification remains hash-exact; this helper is intentionally used
    only for installed active roots where a user's surrounding instructions may
    be preserved by the installer.
    """
    if actual is None or repository is None:
        return False, False
    try:
        if actual.stat().st_size > MAX_ROUTE_INPUT_BYTES or repository.stat().st_size > MAX_ROUTE_INPUT_BYTES:
            return False, False
        actual_bytes = actual.read_bytes()
        repository_bytes = repository.read_bytes()
    except (OSError, UnicodeError):
        return False, False
    if actual_bytes == repository_bytes:
        return True, False
    start = MANAGED_AGENTS_START.encode("utf-8")
    end = MANAGED_AGENTS_END.encode("utf-8")
    if actual_bytes.count(start) != 1 or actual_bytes.count(end) != 1:
        return False, False
    begin = actual_bytes.find(start)
    finish = actual_bytes.find(end)
    if begin < 0 or finish < begin + len(start):
        return False, False
    body = actual_bytes[begin + len(start):finish]
    if body != repository_bytes:
        return False, False
    return True, True


def _active_agents_path(root: Path) -> Optional[Path]:
    """Resolve Codex's effective global instruction file safely."""
    override_candidate = root / AGENTS_OVERRIDE_RELATIVE
    if override_candidate.exists() or override_candidate.is_symlink():
        if override_candidate.is_symlink() or not override_candidate.is_file():
            return None
        override = _safe_path(root, AGENTS_OVERRIDE_RELATIVE)
        if override is None:
            return None
        try:
            with override.open("rb") as handle:
                raw = handle.read(MAX_ROUTE_INPUT_BYTES + 1)
            if len(raw) > MAX_ROUTE_INPUT_BYTES:
                return None
            if raw.strip():
                return override
        except (OSError, UnicodeError):
            return None
    return _safe_path(root, AGENTS_RELATIVE)


def _read_json(path: Optional[Path]) -> Tuple[Optional[Any], bool]:
    if path is None:
        return None, False
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = handle.read(MAX_ROUTE_INPUT_BYTES + 1)
        return parse_route_input(raw), True
    except (
        OSError,
        UnicodeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        MemoryError,
        OverflowError,
        RecursionError,
    ):
        return None, False


def _contract_shape(contract: Any, spec: Mapping[str, Any]) -> List[str]:
    """Return deterministic semantic errors for the public contract shape."""

    errors: List[str] = []
    if not isinstance(contract, dict):
        return ["contract_not_object"]
    expected_contract_keys = {
        "schema_version",
        "version",
        "root",
        "runtime",
        "roles",
        "transport",
        "transport_failure_fallback",
        "split",
        "concurrency",
        "max_upgrade_reason_codes",
        "evidence",
        "sol_fallback",
    }
    if set(contract) != expected_contract_keys:
        errors.append("unknown_contract_key" if set(contract) - expected_contract_keys else "missing_contract_key")
    if contract.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported_schema")
    if contract.get("version") != POLICY_VERSION:
        errors.append("unsupported_version")

    root = contract.get("root")
    if not isinstance(root, dict) or root != {
        "model": "gpt-5.6-sol",
        "reasoning": "user-selected",
        "service_tier": "standard",
        "service_tier_configured": False,
    }:
        errors.append("root_contract")

    runtime = contract.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("runtime_contract")
    else:
        if set(runtime) != {"agents_path", "agents_sha256", "config_snippet_path", "config_snippet_sha256"}:
            errors.append("unknown_runtime_key")
        if runtime.get("agents_path") != spec["agents_relative"] or not isinstance(runtime.get("agents_sha256"), str) or not SHA256.fullmatch(runtime.get("agents_sha256", "")):
            errors.append("runtime_agents_contract")
        if runtime.get("config_snippet_path") != spec["snippet_relative"] or not isinstance(runtime.get("config_snippet_sha256"), str) or not SHA256.fullmatch(runtime.get("config_snippet_sha256", "")):
            errors.append("runtime_config_contract")

    roles = contract.get("roles")
    role_definitions = spec["roles"]
    expected_roles = {definition["role"] for definition in role_definitions.values()}
    if not isinstance(roles, dict) or set(roles) != expected_roles:
        if isinstance(roles, dict) and set(roles) - expected_roles:
            errors.append("unknown_role_key")
        else:
            errors.append("role_set_contract")
    else:
        for definition in role_definitions.values():
            role = definition["role"]
            value = roles.get(role)
            if isinstance(value, dict) and set(value) != {"path", "model", "reasoning", "service_tier", "sandbox_mode", "sha256"}:
                errors.append("unknown_role_key")
            expected = {
                "path": definition["path"],
                "model": definition["model"],
                "reasoning": definition["reasoning"],
                "service_tier": definition["service_tier"],
                "sandbox_mode": definition["sandbox_mode"],
            }
            if not isinstance(value, dict) or any(value.get(key) != expected_value for key, expected_value in expected.items()):
                errors.append("role_contract")
                continue
            if not isinstance(value.get("sha256"), str) or not SHA256.fullmatch(value["sha256"]):
                errors.append("role_hash_contract")

    transport = contract.get("transport")
    if not isinstance(transport, dict) or transport != LUNA_TRANSPORT:
        errors.append("transport_contract")
    transport_fallback = contract.get("transport_failure_fallback")
    if not isinstance(transport_fallback, dict) or transport_fallback != APP_TASK_FALLBACK:
        errors.append("transport_fallback_contract")

    split = contract.get("split")
    expected_checks = [
        {"name": label, "field": field, "required": True}
        for label, field in zip(SPLIT_LABELS, SPLIT_FIELDS)
    ]
    if not isinstance(split, dict) or split != {
        "checks": expected_checks,
        "all_required": True,
        "on_failure": "sol",
    }:
        errors.append("split_contract")

    concurrency = contract.get("concurrency")
    if isinstance(concurrency, dict) and set(concurrency) != {
        "max_concurrent_threads_per_session",
        "max_concurrent_delegated_lanes",
        "processing",
        "dependent_work",
    }:
        errors.append("unknown_concurrency_key")
    if not isinstance(concurrency, dict) or concurrency != {
        "max_concurrent_threads_per_session": MAX_LANES,
        "max_concurrent_delegated_lanes": MAX_LANES,
        "processing": "waves",
        "dependent_work": "serialized",
    }:
        errors.append("concurrency_contract")
    if contract.get("max_upgrade_reason_codes") != list(MAX_UPGRADE_REASON_CODES):
        errors.append("max_upgrade_codes_contract")
    evidence = contract.get("evidence")
    if isinstance(evidence, dict) and set(evidence) != {"required_fields", "on_missing"}:
        errors.append("unknown_evidence_key")
    if not isinstance(evidence, dict) or evidence != {
        "required_fields": list(EVIDENCE_FIELDS),
        "on_missing": "sol",
    }:
        errors.append("evidence_contract")
    fallback = contract.get("sol_fallback")
    if not isinstance(fallback, dict) or fallback != {
        "route": "sol",
        "role": "sol",
        "model": "gpt-5.6-sol",
        "reasoning": "user-selected",
        "service_tier": "standard",
        "service_tier_configured": False,
        "on_error": "direct",
    }:
        errors.append("fallback_contract")
    return sorted(set(errors))


def _validate_snippet(path: Optional[Path]) -> bool:
    if path is None or tomllib is None:
        return False
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return False
    if set(data) != {"model", "model_reasoning_effort", "features", "agents"}:
        return False
    if data.get("model") != "gpt-5.6-sol" or not isinstance(data.get("model_reasoning_effort"), str) or not data["model_reasoning_effort"].strip():
        return False
    features = data.get("features")
    if features != {"fast_mode": True, "multi_agent": True}:
        return False
    agents = data.get("agents")
    return (
        isinstance(agents, dict)
        and set(agents) == {"max_concurrent_threads_per_session"}
        and agents.get("max_concurrent_threads_per_session") == MAX_LANES
    )


def _validate_role_file(path: Optional[Path], expected: Mapping[str, Any]) -> bool:
    if path is None or tomllib is None:
        return False
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return False
    expected_keys = {
        "name",
        "description",
        "model",
        "model_reasoning_effort",
        "sandbox_mode",
        "developer_instructions",
    }
    service_tier_configured = expected.get("service_tier_configured", True) is True
    if service_tier_configured:
        expected_keys.add("service_tier")
    if set(data) != expected_keys:
        return False
    instructions = data.get("developer_instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        return False
    if "exactly these fields" not in instructions.lower() or any(f"`{field}`" not in instructions for field in EVIDENCE_FIELDS):
        return False
    if expected["role"].startswith("luna_max_") and (
        re.search(r"max\s+upgrade\s+reason", instructions, re.IGNORECASE) is None
        or any(code not in instructions for code in MAX_UPGRADE_REASON_CODES)
    ):
        return False
    core_matches = all(data.get(key) == value for key, value in {
        "name": expected["role"],
        "model": expected["model"],
        "model_reasoning_effort": expected["reasoning"],
        "sandbox_mode": expected["sandbox_mode"],
    }.items())
    tier_matches = (
        data.get("service_tier") == expected["service_tier"]
        if service_tier_configured
        else "service_tier" not in data and expected["service_tier"] == "standard"
    )
    return core_matches and tier_matches and isinstance(data.get("description"), str) and bool(data["description"].strip())


def _validate_active_config(path: Optional[Path]) -> bool:
    """Check only the non-sensitive installed keys owned by this kit."""

    if path is None or tomllib is None or path.is_symlink() or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return False
    features = data.get("features")
    agents = data.get("agents")
    return (
        data.get("model") == "gpt-5.6-sol"
        and isinstance(data.get("model_reasoning_effort"), str)
        and bool(data["model_reasoning_effort"].strip())
        and "service_tier" not in data
        and isinstance(features, dict)
        and features.get("fast_mode") is True
        and features.get("multi_agent") is True
        and isinstance(agents, dict)
        and agents.get("max_concurrent_threads_per_session") == MAX_LANES
        and "default_subagent_model" not in agents
    )


def verify_contract(root: Path | str = DEFAULT_ROOT, profile: str = "fast") -> Dict[str, Any]:
    """Verify policy schema and runtime hashes without writing any files."""

    try:
        spec = profile_spec(profile)
    except ValueError:
        return {
            "schema_version": SCHEMA_VERSION,
            "version": POLICY_VERSION,
            "profile": profile if isinstance(profile, str) and len(profile) <= 32 else "unsupported",
            "ok": False,
            "runtime_root_match": False,
            "runtime_agents_match": False,
            "runtime_config_match": False,
            "role_matches": 0,
            "role_count": 0,
            "errors": ["unsupported_profile"],
        }
    role_definitions = spec["roles"]
    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "version": POLICY_VERSION,
        "profile": profile,
        "ok": False,
        "runtime_root_match": False,
        "runtime_agents_match": False,
        "runtime_config_match": False,
        "role_matches": 0,
        "role_count": len(role_definitions),
        "errors": [],
    }
    if sys.version_info < MIN_PYTHON or tomllib is None:
        report["errors"] = ["python_version_unsupported"]
        report["diagnostic"] = PYTHON_REQUIREMENT
        return report
    try:
        root_path = Path(root)
    except (TypeError, ValueError):
        report["errors"] = ["runtime_root_unreadable"]
        return report
    if root_path.is_symlink() or not root_path.is_dir():
        report["errors"] = ["runtime_root_unreadable"]
        return report
    policy_path = _safe_path(root_path, spec["policy_relative"])
    contract, parsed = _read_json(policy_path)
    if not parsed:
        report["errors"] = ["policy_unreadable"]
        return report
    errors = _contract_shape(contract, spec)
    if errors:
        report["errors"] = errors
        return report

    assert isinstance(contract, dict)
    runtime = contract["runtime"]
    agents_path = _safe_path(root_path, spec["agents_relative"])
    snippet_path = _safe_path(root_path, spec["snippet_relative"])
    agents_hash = _hash_file(agents_path)
    snippet_hash = _hash_file(snippet_path)
    report["runtime_agents_match"] = agents_hash is not None and agents_hash[0] == runtime["agents_sha256"]
    report["runtime_config_match"] = snippet_hash is not None and snippet_hash[0] == runtime["config_snippet_sha256"] and _validate_snippet(snippet_path)
    if not report["runtime_agents_match"]:
        errors.append("runtime_agents_drift")
    if not report["runtime_config_match"]:
        errors.append("runtime_config_drift")

    roles = contract["roles"]
    for expected in role_definitions.values():
        path = _safe_path(root_path, expected["path"])
        actual = _hash_file(path)
        configured = roles[expected["role"]]
        hash_match = actual is not None and actual[0] == configured["sha256"]
        semantic_match = _validate_role_file(path, expected)
        if hash_match and semantic_match:
            report["role_matches"] += 1
        if not hash_match:
            errors.append("role_runtime_drift")
        if not semantic_match:
            errors.append("role_semantic_contract")
    report["runtime_root_match"] = bool(report["runtime_agents_match"] and report["runtime_config_match"] and report["role_matches"] == len(role_definitions))
    report["errors"] = sorted(set(errors))
    report["ok"] = not report["errors"] and report["runtime_root_match"]
    return report


def verify_active_root(
    active_root: Path | str,
    repository_root: Path | str = DEFAULT_ROOT,
    active_config: Optional[Path | str] = None,
    profile: str = "fast",
) -> Dict[str, Any]:
    """Compare an installed root and optional sanitized config contract."""

    try:
        spec = profile_spec(profile)
    except ValueError:
        return {
            "schema_version": SCHEMA_VERSION,
            "version": POLICY_VERSION,
            "profile": profile if isinstance(profile, str) and len(profile) <= 32 else "unsupported",
            "ok": False,
            "repository_contract_ok": False,
            "active_root_match": False,
            "active_agents_match": False,
            "active_agents_managed_block": False,
            "active_config_checked": active_config is not None,
            "active_config_match": None,
            "role_matches": 0,
            "role_count": 0,
            "errors": ["unsupported_profile"],
        }
    role_definitions = spec["roles"]
    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "version": POLICY_VERSION,
        "profile": profile,
        "ok": False,
        "repository_contract_ok": False,
        "active_root_match": False,
        "active_agents_match": False,
        "active_agents_managed_block": False,
        "active_config_checked": active_config is not None,
        "active_config_match": None,
        "role_matches": 0,
        "role_count": len(role_definitions),
        "errors": [],
    }
    repository_report = verify_contract(repository_root, profile)
    if not repository_report["ok"]:
        report["errors"] = ["repository_contract_invalid", *repository_report["errors"]]
        return report
    report["repository_contract_ok"] = True
    try:
        active_path = Path(active_root)
        repository_path = Path(repository_root)
    except (TypeError, ValueError):
        report["errors"] = ["active_root_unreadable"]
        return report
    if active_path.is_symlink() or not active_path.is_dir():
        report["errors"] = ["active_root_unreadable"]
        return report
    contract, parsed = _read_json(_safe_path(repository_path, spec["policy_relative"]))
    if not parsed or not isinstance(contract, dict):
        report["errors"] = ["repository_contract_invalid"]
        return report
    runtime = contract["runtime"]
    agents_path = _active_agents_path(active_path)
    repository_agents = _safe_path(repository_path, spec["agents_relative"])
    report["active_agents_match"], report["active_agents_managed_block"] = _agents_match(agents_path, repository_agents)
    report["active_agents_path"] = AGENTS_OVERRIDE_RELATIVE if agents_path is not None and agents_path.name == AGENTS_OVERRIDE_RELATIVE else AGENTS_RELATIVE
    if not report["active_agents_match"]:
        report["errors"].append("active_agents_drift")
    if active_config is not None:
        try:
            config_path = Path(active_config)
        except (TypeError, ValueError):
            config_path = None
        report["active_config_match"] = _validate_active_config(config_path)
        if not report["active_config_match"]:
            report["errors"].append("active_config_drift")
    roles = contract["roles"]
    for expected in role_definitions.values():
        path = _safe_path(active_path, expected["path"])
        actual = _hash_file(path)
        configured = roles[expected["role"]]
        hash_match = actual is not None and actual[0] == configured["sha256"]
        semantic_match = _validate_role_file(path, expected)
        if hash_match and semantic_match:
            report["role_matches"] += 1
        if not hash_match:
            report["errors"].append("active_role_drift")
        if not semantic_match:
            report["errors"].append("active_role_semantic_contract")
    config_ok = active_config is None or report["active_config_match"] is True
    report["active_root_match"] = bool(
        report["active_agents_match"]
        and report["role_matches"] == len(role_definitions)
        and config_ok
    )
    report["errors"] = sorted(set(report["errors"]))
    report["ok"] = report["active_root_match"] and not report["errors"]
    return report


def _ownership_path_is_safe(root: Path, relative: str) -> bool:
    try:
        resolved_root = root.resolve()
        candidate = resolved_root.joinpath(*relative.split("/"))
        current = resolved_root
        for index, part in enumerate(relative.split("/")):
            current = current / part
            if current.is_symlink():
                return False
            if index < len(relative.split("/")) - 1 and current.exists() and not current.is_dir():
                return False
        candidate.resolve(strict=False).relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _normalise_ownership(ownership: Any, root: Path) -> Tuple[Optional[Dict[str, List[str]]], List[str]]:
    if not isinstance(ownership, dict) or not ownership or len(ownership) > MAX_OWNERSHIP_LANES:
        return None, ["malformed_ownership"]
    result: Dict[str, List[str]] = {}
    errors: List[str] = []
    entry_count = 0
    for lane, raw_paths in ownership.items():
        if _safe_id(lane) is None or not isinstance(raw_paths, list) or not raw_paths or len(raw_paths) > 100:
            errors.append("malformed_ownership")
            continue
        paths: List[str] = []
        for raw_path in raw_paths:
            path = _safe_relative(raw_path)
            if path is None:
                errors.append("unsafe_ownership_path")
            elif _is_sensitive_ownership_path(path):
                errors.append("sensitive_ownership_path")
            elif not _ownership_path_is_safe(root, path):
                errors.append("unsafe_ownership_path")
            elif path not in paths:
                paths.append(path)
                entry_count += 1
                if entry_count > MAX_OWNERSHIP_ENTRIES:
                    return None, ["ownership_entries_limit"]
        if paths:
            result[lane] = sorted(paths)
        else:
            errors.append("malformed_ownership")
    if len(result) != len(ownership):
        return None, sorted(set(errors))
    return dict(sorted(result.items())), sorted(set(errors))


def ownership_conflicts(ownership: Mapping[str, Sequence[str]]) -> List[Dict[str, str]]:
    """Return bounded exact or directory-prefix conflicts in O(entries * depth)."""

    entries = sorted((lane, path) for lane, paths in ownership.items() for path in paths)
    conflicts: List[Dict[str, str]] = []
    indexed: Dict[str, List[str]] = {}

    def add_conflict(left_lane: str, left_path: str, right_lane: str, right_path: str, relation: str) -> None:
        if left_lane == right_lane or len(conflicts) >= MAX_CONFLICTS:
            return
        left = (left_lane, left_path)
        right = (right_lane, right_path)
        if right < left:
            left, right = right, left
        conflicts.append({
            "left_lane": left[0],
            "left_path": left[1],
            "right_lane": right[0],
            "right_path": right[1],
            "relation": relation,
        })

    for lane, path in entries:
        if path in indexed:
            for other_lane in indexed[path]:
                add_conflict(other_lane, path, lane, path, "exact")
                if len(conflicts) >= MAX_CONFLICTS:
                    break
        parts = path.split("/")
        for index in range(1, len(parts)):
            ancestor = "/".join(parts[:index])
            for other_lane in indexed.get(ancestor, ()):
                add_conflict(other_lane, ancestor, lane, path, "prefix")
                if len(conflicts) >= MAX_CONFLICTS:
                    break
            if len(conflicts) >= MAX_CONFLICTS:
                break
        indexed.setdefault(path, []).append(lane)
        if len(conflicts) >= MAX_CONFLICTS:
            # No more conflict records can be emitted; ownership remains
            # bounded and the caller only needs the deterministic prefix.
            break
    return sorted(conflicts, key=lambda item: (item["left_path"], item["right_path"], item["left_lane"], item["right_lane"], item["relation"]))[:MAX_CONFLICTS]


def detect_ownership_conflicts(ownership: Mapping[str, Sequence[str]]) -> List[Dict[str, str]]:
    """Compatibility alias with an explicit name for callers and tests."""

    return ownership_conflicts(ownership)


def _request_reason(request: Mapping[str, Any], code: str) -> Dict[str, Any]:
    return _sol_fallback([code])


def evaluate(request: Any, root: Path | str = DEFAULT_ROOT) -> Dict[str, Any]:
    """Evaluate one bounded request and return a route or Sol fallback."""

    if not isinstance(request, dict):
        return _sol_fallback(["malformed_request"])
    if len(request) > 24:
        return _sol_fallback(["malformed_request"])
    if any(key not in REQUEST_FIELDS for key in request):
        return _sol_fallback(["unsupported_request_field"])
    profile = request.get("profile", "fast")
    if profile not in PROFILE_SPECS:
        return _sol_fallback(["unsupported_profile"])
    spec = profile_spec(profile)
    role_definitions = spec["roles"]
    contract_report = verify_contract(root, profile)
    if not contract_report["ok"]:
        return _sol_fallback(["runtime_drift"], errors=contract_report["errors"])

    kind = request.get("kind")
    if not isinstance(kind, str) or len(kind) > 48 or kind not in KIND_ALIASES:
        return _sol_fallback(["unsupported_kind"])
    canonical_kind = KIND_ALIASES[kind]
    if "fork_turns" not in request:
        return _sol_fallback(["fork_turns_required"])

    nested_split = request.get("split")
    if nested_split is not None:
        if not isinstance(nested_split, dict) or set(nested_split) != set(SPLIT_FIELDS):
            return _sol_fallback(["malformed_split"])
        if any(field in request for field in SPLIT_FIELDS):
            return _sol_fallback(["unsupported_request_combination"])
        split_values = nested_split
    else:
        split_values = request
    for field in SPLIT_FIELDS:
        if not isinstance(split_values.get(field), bool):
            return _sol_fallback(["malformed_split"])
    lanes = request.get("lane_count", 1)
    waves = request.get("wave_count", 1)
    if isinstance(lanes, bool) or not isinstance(lanes, int) or lanes < 1 or lanes > MAX_CONCURRENT_LANES:
        return _sol_fallback(["unsupported_concurrency"])
    if isinstance(waves, bool) or not isinstance(waves, int) or waves < 1:
        return _sol_fallback(["unsupported_concurrency"])

    if "evidence" in request and not validate_evidence(request["evidence"]):
        return _sol_fallback(["malformed_evidence"])

    ownership, ownership_errors = _normalise_ownership(request.get("ownership"), Path(root))
    if ownership is None:
        return _sol_fallback(ownership_errors or ["malformed_ownership"])
    conflicts = ownership_conflicts(ownership)
    gate_values = {field: split_values[field] for field in SPLIT_FIELDS}
    if conflicts:
        gate_values["isolated"] = False

    configured_kind = role_definitions[canonical_kind]
    requested_role = request.get("requested_role", configured_kind["role"])
    if not isinstance(requested_role, str):
        return _sol_fallback(["unsupported_combination"])
    max_reason = request.get("max_upgrade_reason")
    if max_reason is not None and max_reason not in MAX_UPGRADE_REASON_CODES:
        return _sol_fallback(["unsupported_max_upgrade_reason"])
    if requested_role == role_definitions["max"]["role"]:
        if max_reason is None:
            return _sol_fallback(["max_upgrade_reason_required"])
        if max_reason not in MAX_UPGRADE_REASON_CODES:
            return _sol_fallback(["unsupported_max_upgrade_reason"])
        configured_kind = role_definitions["max"]
    elif requested_role != configured_kind["role"]:
        return _sol_fallback(["unsupported_combination"])
    elif max_reason is not None:
        return _sol_fallback(["unsupported_combination"])

    for field, expected in (
        ("model", configured_kind["model"]),
        ("reasoning", configured_kind["reasoning"]),
        ("service_tier", configured_kind["service_tier"]),
        ("sandbox_mode", configured_kind["sandbox_mode"]),
        ("fork_turns", LUNA_TRANSPORT["fork_turns"]),
    ):
        if field in request and request[field] != expected:
            gate_values["tier_appropriate"] = False
    if conflicts:
        gate_values["isolated"] = False
    failed = [field for field in SPLIT_FIELDS if gate_values[field] is not True]
    if failed:
        return _sol_fallback([f"split_{field}" for field in failed])

    return {
        "ok": True,
        "decision": "delegate",
        "route": configured_kind["role"],
        "role": configured_kind["role"],
        "model": configured_kind["model"],
        "reasoning": configured_kind["reasoning"],
        "service_tier": configured_kind["service_tier"],
        "sandbox_mode": configured_kind["sandbox_mode"],
        "transport": dict(LUNA_TRANSPORT),
        "fallback": False,
        "kind": canonical_kind,
        "max_upgrade_reason": max_reason,
        "lane_count": lanes,
        "wave_count": waves,
        "max_concurrent_delegated_lanes": MAX_CONCURRENT_LANES,
        "processing": "waves",
        "dependent_work": "serialized",
        "split": gate_values,
        "ownership_conflicts": conflicts,
        "reason_codes": [],
        "errors": [],
        "policy_version": POLICY_VERSION,
        "profile": profile,
    }


def _transport_direct(
    reason_code: str,
    *,
    stage: str = "post_admission_transport",
    failure_code: Optional[str] = None,
    attempts_used: int = 0,
    fallback: bool = True,
    authorization_consumed: bool = False,
    admission_reason_codes: Iterable[str] = (),
    errors: Iterable[str] = (),
) -> Dict[str, Any]:
    """Return a privacy-safe direct-Sol decision for a fallback event."""

    result = _sol_fallback([reason_code], errors=errors)
    result.update({
        "fallback": fallback,
        "fallback_stage": stage,
        "native_failure_code": failure_code,
        "app_task_attempts_used": attempts_used,
        "authorization_consumed": authorization_consumed,
        "admission_reason_codes": sorted({code for code in admission_reason_codes if isinstance(code, str)}),
    })
    return result


def _project_roots_match(value: Any) -> bool:
    """Return true only for the same two existing canonical directories."""

    if not isinstance(value, dict) or set(value) != PROJECT_CONTEXT_FIELDS:
        return False
    resolved = []
    for field in ("current_checkout_root", "app_project_root"):
        raw = value.get(field)
        if not isinstance(raw, str) or not raw or len(raw) > 4096 or "\x00" in raw:
            return False
        path = Path(raw)
        if not path.is_absolute():
            return False
        try:
            canonical = path.resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        if not canonical.is_dir():
            return False
        resolved.append(canonical)
    return resolved[0] == resolved[1]


def evaluate_transport_failure(event: Any, root: Path | str = DEFAULT_ROOT) -> Dict[str, Any]:
    """Evaluate one post-admission native Luna transport failure.

    This does not create a task.  It only authorizes exactly one user-visible
    Codex app task when the original route still passes, the failure belongs to
    the closed native-transport enum, and the user explicitly authorized this
    lane and current checkout.  Every other condition routes directly to Sol.
    """

    if not isinstance(event, dict) or set(event) != FALLBACK_EVENT_FIELDS:
        return _transport_direct(
            "malformed_fallback_event",
            stage="fallback_validation",
            fallback=False,
        )
    failure_code = event.get("failure_code")
    attempts_used = event.get("attempts_used")
    if isinstance(attempts_used, bool) or not isinstance(attempts_used, int) or attempts_used not in (0, 1):
        return _transport_direct(
            "malformed_fallback_event",
            stage="fallback_validation",
            fallback=False,
        )
    app_task_available = event.get("app_task_available")
    if not isinstance(failure_code, str) or not isinstance(app_task_available, bool):
        return _transport_direct(
            "malformed_fallback_event",
            stage="fallback_validation",
            fallback=False,
        )

    admission = evaluate(event.get("routing_request"), root)
    if admission.get("ok") is not True or admission.get("decision") != "delegate":
        return _transport_direct(
            "admission_not_approved",
            stage="pre_admission",
            fallback=False,
            admission_reason_codes=admission.get("reason_codes", []),
            errors=admission.get("errors", []),
        )
    if failure_code not in ELIGIBLE_NATIVE_FAILURE_CODES:
        return _transport_direct(
            "ineligible_transport_failure",
            stage="post_admission_ineligible",
            attempts_used=attempts_used,
            fallback=False,
        )

    authorization = event.get("fallback_authorization")
    if not isinstance(authorization, dict) or set(authorization) != FALLBACK_AUTHORIZATION_FIELDS:
        return _transport_direct(
            "fallback_not_authorized",
            failure_code=failure_code,
            attempts_used=attempts_used,
        )
    lane_id = authorization.get("lane_id")
    max_attempts = authorization.get("max_attempts")
    ownership = event["routing_request"].get("ownership")
    if (
        authorization.get("authorized") is not True
        or authorization.get("target") != APP_TASK_FALLBACK["target"]
        or authorization.get("scope") != APP_TASK_FALLBACK["authorization_scope"]
        or isinstance(max_attempts, bool)
        or max_attempts != APP_TASK_FALLBACK["max_attempts_per_lane"]
        or authorization.get("current_checkout") is not True
        or _safe_id(lane_id) is None
        or not isinstance(ownership, dict)
        or lane_id not in ownership
    ):
        return _transport_direct(
            "fallback_not_authorized",
            failure_code=failure_code,
            attempts_used=attempts_used,
        )
    if attempts_used != 0:
        return _transport_direct(
            "fallback_attempt_exhausted",
            failure_code=failure_code,
            attempts_used=attempts_used,
            authorization_consumed=True,
        )
    if not app_task_available:
        return _transport_direct(
            "app_task_unavailable",
            failure_code=failure_code,
            attempts_used=1,
            authorization_consumed=True,
        )
    if not _project_roots_match(event.get("project_context")):
        return _transport_direct(
            "app_project_mismatch",
            failure_code=failure_code,
            attempts_used=1,
            authorization_consumed=True,
        )

    return {
        "ok": True,
        "decision": "create_codex_app_task",
        "route": "codex_app_task",
        "role": "codex_app_task",
        "requested_role": admission["role"],
        "requested_profile": admission["profile"],
        "model_override": None,
        "reasoning_override": None,
        "service_tier_override": None,
        "custom_role_fidelity": "prompt_capsule_only",
        "transport": dict(APP_TASK_TRANSPORT),
        "fallback": True,
        "fallback_stage": "post_admission_transport",
        "native_failure_code": failure_code,
        "authorization_consumed": True,
        "app_task_attempt_number": 1,
        "app_task_attempts_remaining": 0,
        "project_root_verified": True,
        "lane_id": lane_id,
        "reason_codes": [failure_code],
        "errors": [],
        "policy_version": POLICY_VERSION,
    }


def _json_output(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, separators=(",", ": "))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify and evaluate the Sol/Luna routing policy.")
    parser.add_argument("command", nargs="?", choices=("verify", "route", "fallback", "active-root"), help="operation (defaults to verify)")
    parser.add_argument("--verify", action="store_true", help="run static contract verification")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="repository root containing the policy")
    parser.add_argument("--profile", choices=tuple(PROFILE_SPECS), default="fast", help="Luna service-tier profile")
    parser.add_argument("--active-root", help="installed root to compare in active-root mode")
    parser.add_argument("--active-config", help="optional installed config.toml to check without reporting its contents")
    parser.add_argument("--format", choices=("json", "pretty"), default="pretty")
    parser.add_argument("--request", help="bounded JSON request for route or fallback mode (or '-' for stdin)")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    command = args.command or ("route" if args.request is not None else "verify")
    if args.verify:
        command = "verify"
    if command == "verify":
        report = verify_contract(args.root, args.profile)
        print(_json_output(report) if args.format == "json" else _json_output(report))
        return 0 if report["ok"] else 1
    if command == "active-root":
        if not args.active_root:
            report = {
                "ok": False,
                "schema_version": SCHEMA_VERSION,
                "version": POLICY_VERSION,
                "active_root_match": False,
                "errors": ["active_root_required"],
            }
        else:
            report = verify_active_root(args.active_root, args.root, args.active_config, args.profile)
        print(_json_output(report) if args.format == "json" else _json_output(report))
        return 0 if report["ok"] else 1
    try:
        raw = sys.stdin.read(MAX_ROUTE_INPUT_BYTES + 1) if args.request == "-" else args.request
        request = parse_route_input(raw) if isinstance(raw, str) else None
        if command == "route" and isinstance(request, dict) and "profile" not in request:
            request = dict(request)
            request["profile"] = args.profile
        result = evaluate_transport_failure(request, args.root) if command == "fallback" else evaluate(request, args.root)
    except (TypeError, ValueError, UnicodeError, MemoryError, OverflowError, RecursionError):
        result = (
            _transport_direct("malformed_fallback_event")
            if command == "fallback"
            else _sol_fallback(["malformed_route_input"])
        )
    print(_json_output(result) if args.format == "json" else _json_output(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - exercised by CLI checks.
    sys.exit(main())
