#!/usr/bin/env python3
"""Strict local milestone receipt close/validate/summarize tool.

Receipts are unsigned audit artifacts. This tool never launches work, sends
data, or treats a receipt as cryptographic authenticity or automation input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import platform_fs
except ImportError:  # pragma: no cover - package import in tests
    from scripts import platform_fs  # type: ignore[no-redef]


SCHEMA_VERSION = 1
ORIGIN = "unsigned-local-audit"
RECEIPT_POLICY_VERSION = "receipt-policy.v2"
ROUTINE_RECORD_VERSION = "routine-delegation-record.v2"
LEGACY_ROUTINE_RECORD_VERSION = "routine-delegation-record.v1"
DEFAULT_ROOT = Path(__file__).resolve().parents[1]
MAX_INPUT_BYTES = 64 * 1024
MAX_ARRAY_ITEMS = 64
MAX_REF_ITEMS = 16
MAX_SAFE_TEXT = 128
RECEIPT_ID_RE = re.compile(r"^mr1-[0-9a-f]{64}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,63}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
REF_RE = re.compile(r"^[a-z0-9][a-z0-9._:/-]{0,127}$")
TASK_REF_RE = re.compile(r"^ct1-[0-9a-f]{64}$")
UTC_RE = re.compile(r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
FAMILIES = {"foundation", "routing", "receipts", "feature", "bugfix", "integration", "release", "security", "other"}
RISK_BANDS = {"small", "medium", "large", "high-risk", "critical"}
DISPOSITIONS = {"accepted", "rejected", "abandoned"}
PROFILE_ROLES = {
    "fast": {
        "luna_scout_fast",
        "luna_worker_fast",
        "luna_critic_fast",
        "luna_tester_fast",
        "luna_max_fast",
    },
    "standard": {
        "luna_scout_standard",
        "luna_worker_standard",
        "luna_critic_standard",
        "luna_tester_standard",
        "luna_max_standard",
    },
}
ROLES = set().union(*PROFILE_ROLES.values())
MAX_ROLES = {"luna_max_fast", "luna_max_standard"}
REASONING = {"medium", "high", "max"}
ROOT_REASONING = {"low", "medium", "high", "xhigh", "max", "ultra"}
MAX_REASONS = {"genuine_ambiguity", "cross_cutting_risk", "failed_high_attempt", "high_impact_adversarial_review"}
LANE_OUTCOMES = {"completed", "failed", "blocked", "skipped"}
NATIVE_TRANSPORT_FAILURES = {
    "custom_role_rejected",
    "custom_role_unavailable",
    "native_spawn_tool_unavailable",
    "native_spawn_transport_error",
}
LANE_TRANSPORTS = {"native_luna_subagent", "codex_app_task", "sol"}
APP_TASK_OUTCOMES = {"completed", "failed", "blocked", "unavailable"}
CHECK_RESULTS = {"pass", "fail", "unknown"}
RISK_CODES = {"none", "runtime_drift", "scope", "security", "privacy", "validation", "availability", "cost", "data_loss", "unknown"}
COVERAGE = {"complete-full-workflow", "incomplete", "unknown"}
RECEIPT_WORK_BANDS = {"routine", "substantial", "high_risk", "critical"}
RECEIPT_OUTCOMES = {"accepted", "failed", "blocked", "abandoned"}
FULL_RECEIPT_CATEGORIES = {
    "security",
    "release",
    "deployment",
    "migration",
    "destructive",
    "external_side_effect",
    "app_task_fallback",
    "pilot",
    "benchmark",
    "evaluation",
}
RECEIPT_TIER_CONTEXT_FIELDS = {
    "work_band",
    "delegated",
    "outcome",
    "categories",
    "material_rework",
    "explicit_audit",
    "automatic_collection_available",
}
LEGACY_ROUTINE_RECORD_FIELDS = {"schema_version", "version", "spawn", "outcome", "checks", "usage"}
ROUTINE_RECORD_FIELDS = {
    "schema_version", "version", "recorded_on", "context", "spawn", "outcome", "checks", "usage",
}
ROUTINE_RECORD_OUTCOMES = {"completed", "blocked", "failed"}
ROUTINE_CHECK_RESULTS = {"pass", "fail", "skipped"}
ROUTINE_PROFILES = {"fast", "standard"}
ROUTINE_ROLE_KINDS = {"scout", "worker", "critic", "tester", "max"}
ROUTINE_TASK_CLASSES = {
    "explanation_question", "status_reporting", "git_operation", "one_command_diagnostic",
    "targeted_lookup", "localized_single_file_edit", "formatting_documentation",
    "straightforward_test_rerun", "overhead_comparable", "broad_mapping",
    "substantial_implementation", "substantial_validation", "independent_risk_review",
    "complex_analysis",
}
ROUTINE_BENEFIT_CODES = {
    "parallel_latency", "isolated_large_implementation", "broad_read_only_mapping",
    "independent_risk_review",
}
ROUTING_POLICY_RE = re.compile(r"^routing-policy\.v[1-9][0-9]*\.[0-9]+$")
RECORDED_DATE_RE = re.compile(r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$")
TOP_KEYS = {
    "schema_version", "receipt_id", "project_id", "codex_task_id", "milestone_id", "family", "size_risk_band",
    "started_at", "closed_at", "disposition", "decision_owner", "accepted_by", "user_confirmation", "root_runtime",
    "repository", "delegated_lanes", "acceptance_checks", "rework_count", "risks", "usage", "origin",
}
FORBIDDEN_KEYS = {
    "prompt", "messages", "source_code", "file_contents", "tool_arguments", "tool_output", "raw_trace",
    "transcript", "secrets", "credentials", "private_keys",
}
CREDENTIAL_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|bearer\s+[A-Za-z0-9._~+/=-]{12,}|-----BEGIN(?: [A-Z]+)* PRIVATE KEY-----)",
    re.IGNORECASE,
)
RECEIPT_POLICY_CONTRACT = {
    "schema_version": 2,
    "version": RECEIPT_POLICY_VERSION,
    "historical_full_schema": "milestone-receipt.v1",
    "minimal_schema": ROUTINE_RECORD_VERSION,
    "historical_minimal_schemas": [LEGACY_ROUTINE_RECORD_VERSION],
    "routine_direct": "handoff_only",
    "routine_delegated": "minimal_if_automatic_else_unknown",
    "full_triggers": sorted(FULL_RECEIPT_CATEGORIES),
    "full_outcomes": ["failed", "blocked", "abandoned"],
    "full_work_bands": ["high_risk", "critical"],
    "material_rework_requires_full": True,
    "explicit_audit_requires_full": True,
    "missing_optional_routine_record": "not_error",
    "absent_usage_attribution": "unknown",
}


class ReceiptError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class DuplicateKeyError(ReceiptError):
    pass


def _enum(value: Any, choices: set[str]) -> bool:
    """Membership check that never raises for malformed/unhashable JSON values."""

    return isinstance(value, str) and value in choices


def _path_has_symlink_component(path: Path) -> bool:
    try:
        current = Path(path.anchor) if path.is_absolute() else Path(".")
        for part in path.parts[1:] if path.is_absolute() else path.parts:
            current = current / part
            if platform_fs.is_link_like(current) and not platform_fs.allowed_system_link(current):
                return True
    except (OSError, RuntimeError):
        return True
    return False


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _strict_loads(raw: str) -> Any:
    if not isinstance(raw, str):
        raise ReceiptError("invalid_input")
    try:
        if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ReceiptError("input_oversize")
    except (UnicodeError, MemoryError, OverflowError) as exc:
        raise ReceiptError("input_oversize") from exc

    def pairs_hook(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateKeyError("duplicate_key")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=pairs_hook, parse_constant=lambda _: (_ for _ in ()).throw(ReceiptError("nonfinite_number")))
    except (json.JSONDecodeError, RecursionError, MemoryError, OverflowError, UnicodeError) as exc:
        raise ReceiptError("malformed_json") from exc


def _read_input(path: Path) -> Any:
    if _path_has_symlink_component(path) or not path.is_file():
        raise ReceiptError("unsafe_input_path")
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise ReceiptError("input_oversize")
        raw = data.decode("utf-8")
    except (OSError, UnicodeError, RuntimeError, ValueError, MemoryError) as exc:
        if isinstance(exc, ReceiptError):
            raise
        raise ReceiptError("input_unreadable") from exc
    return _strict_loads(raw)


def _safe_text(value: Any, pattern: re.Pattern[str] = LABEL_RE) -> bool:
    return isinstance(value, str) and len(value) <= MAX_SAFE_TEXT and pattern.fullmatch(value) is not None


def _safe_refs(value: Any) -> bool:
    return isinstance(value, list) and len(value) <= MAX_REF_ITEMS and all(_safe_text(item, REF_RE) for item in value)


def _walk_privacy(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or key.lower() in FORBIDDEN_KEYS:
                raise ReceiptError("forbidden_privacy_key")
            _walk_privacy(child)
    elif isinstance(value, list):
        if len(value) > MAX_ARRAY_ITEMS:
            raise ReceiptError("array_oversize")
        for child in value:
            _walk_privacy(child)
    elif isinstance(value, str):
        if len(value) > MAX_SAFE_TEXT or CREDENTIAL_RE.search(value):
            raise ReceiptError("credential_like_value")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ReceiptError("nonfinite_number")


def _timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or UTC_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def _hash(value: Any) -> bool:
    return isinstance(value, str) and HASH_RE.fullmatch(value) is not None


def _validate_hashes(repository: Any) -> str:
    if not isinstance(repository, dict) or set(repository) != {"base_commit", "dirty", "hashes", "bundle_version", "rate_card_version"}:
        raise ReceiptError("repository_shape")
    if not isinstance(repository["base_commit"], str) or COMMIT_RE.fullmatch(repository["base_commit"]) is None or not isinstance(repository["dirty"], bool):
        raise ReceiptError("repository_metadata")
    hashes = repository["hashes"]
    if not isinstance(hashes, dict) or set(hashes) != {"agents", "policy", "config", "rate_card", "roles"}:
        raise ReceiptError("hash_shape")
    if any(not _hash(hashes[name]) for name in ("agents", "policy", "config", "rate_card")):
        raise ReceiptError("invalid_hash")
    roles = hashes["roles"]
    if not isinstance(roles, dict) or any(not _hash(v) for v in roles.values()):
        raise ReceiptError("invalid_role_hashes")
    profiles = [profile for profile, expected in PROFILE_ROLES.items() if set(roles) == expected]
    if len(profiles) != 1:
        raise ReceiptError("invalid_role_hashes")
    if not _safe_text(repository["bundle_version"]) or repository["rate_card_version"] != "rate-card.v1":
        raise ReceiptError("repository_versions")
    return profiles[0]


def _validate_lane_transport(transport: Any) -> None:
    required = {
        "requested",
        "used",
        "native_failure",
        "fallback_authorized",
        "fallback_attempts",
        "fallback_outcome",
        "task_ref",
    }
    if not isinstance(transport, dict) or set(transport) != required:
        raise ReceiptError("lane_transport_shape")
    if transport["requested"] != "native_luna_subagent" or not _enum(transport["used"], LANE_TRANSPORTS):
        raise ReceiptError("lane_transport_values")
    attempts = transport["fallback_attempts"]
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts not in (0, 1):
        raise ReceiptError("lane_transport_attempts")
    if not isinstance(transport["fallback_authorized"], bool):
        raise ReceiptError("lane_transport_authorization")
    failure = transport["native_failure"]
    outcome = transport["fallback_outcome"]
    task_ref = transport["task_ref"]
    used = transport["used"]
    if used == "native_luna_subagent":
        if failure is not None or transport["fallback_authorized"] or attempts != 0 or outcome is not None or task_ref is not None:
            raise ReceiptError("lane_transport_consistency")
        return
    if not _enum(failure, NATIVE_TRANSPORT_FAILURES):
        raise ReceiptError("lane_transport_failure")
    if used == "codex_app_task":
        if (
            transport["fallback_authorized"] is not True
            or attempts != 1
            or not _enum(outcome, APP_TASK_OUTCOMES - {"unavailable"})
            or not isinstance(task_ref, str)
            or TASK_REF_RE.fullmatch(task_ref) is None
        ):
            raise ReceiptError("lane_transport_consistency")
        return
    if task_ref is not None:
        raise ReceiptError("lane_transport_consistency")
    if transport["fallback_authorized"] is False:
        if attempts != 0 or outcome is not None:
            raise ReceiptError("lane_transport_consistency")
    elif outcome != "unavailable" or attempts != 1:
        raise ReceiptError("lane_transport_consistency")


def _validate_lane(lane: Any, profile: str = "fast") -> None:
    required = {"lane_id", "role", "reasoning", "tier", "attempts", "retries", "escalation", "max_reason", "outcome", "useful"}
    if not isinstance(lane, dict) or set(lane) not in (required, required | {"transport"}):
        raise ReceiptError("lane_shape")
    roles = PROFILE_ROLES.get(profile)
    if roles is None:
        raise ReceiptError("lane_runtime")
    if not _safe_text(lane["lane_id"], ID_RE) or not _enum(lane["role"], roles) or not _enum(lane["reasoning"], REASONING) or lane["tier"] != profile:
        raise ReceiptError("lane_runtime")
    if any(isinstance(lane[k], bool) or not isinstance(lane[k], int) or not 0 <= lane[k] <= 100 for k in ("attempts", "retries")) or lane["attempts"] < 1 or lane["retries"] >= lane["attempts"]:
        raise ReceiptError("lane_counts")
    escalation = lane["escalation"]
    if not isinstance(escalation, dict) or set(escalation) != {"target", "reason"}:
        raise ReceiptError("escalation_shape")
    if (escalation["target"] is not None and not _enum(escalation["target"], {"sol"} | roles)) or (escalation["reason"] is not None and not _enum(escalation["reason"], MAX_REASONS)):
        raise ReceiptError("escalation_values")
    if (escalation["target"] is None) != (escalation["reason"] is None):
        raise ReceiptError("escalation_consistency")
    if not isinstance(lane["escalation"], dict) or not _enum(lane["outcome"], LANE_OUTCOMES) or not isinstance(lane["useful"], bool):
        raise ReceiptError("lane_values")
    reason = lane["max_reason"]
    if reason is not None and not _enum(reason, MAX_REASONS):
        raise ReceiptError("max_reason")
    if lane["role"] in MAX_ROLES and reason is None:
        raise ReceiptError("max_reason_required")
    if lane["role"] not in MAX_ROLES and reason is not None:
        raise ReceiptError("max_reason_unsupported")
    if "transport" in lane:
        _validate_lane_transport(lane["transport"])


def _validate_checks(checks: Any) -> None:
    if not isinstance(checks, list) or not 1 <= len(checks) <= 64:
        raise ReceiptError("checks_shape")
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"id", "result", "evidence_refs", "provenance"}:
            raise ReceiptError("check_shape")
        if not _safe_text(check["id"], ID_RE) or not _enum(check["result"], CHECK_RESULTS) or not _safe_refs(check["evidence_refs"]) or not _safe_refs(check["provenance"]):
            raise ReceiptError("check_values")


def _validate_usage(usage: Any) -> None:
    if not isinstance(usage, dict) or set(usage) != {"coverage", "provenance", "total_tokens", "weighted_usage", "source_refs", "rate_card_version"}:
        raise ReceiptError("usage_shape")
    coverage = usage["coverage"]
    if not _enum(coverage, COVERAGE) or not _safe_refs(usage["source_refs"]):
        raise ReceiptError("usage_values")
    total = usage["total_tokens"]
    if total is not None and (isinstance(total, bool) or not isinstance(total, int) or total < 0):
        raise ReceiptError("usage_total")
    weighted = usage["weighted_usage"]
    if weighted is not None and (isinstance(weighted, bool) or not isinstance(weighted, (int, float)) or not math.isfinite(float(weighted)) or weighted < 0):
        raise ReceiptError("usage_weighted")
    if coverage == "complete-full-workflow":
        if usage["provenance"] != "usage_reporter" or usage["rate_card_version"] != "rate-card.v1" or total is None or weighted is None or not usage["source_refs"]:
            raise ReceiptError("usage_incomplete")
    else:
        if not _enum(usage["provenance"], {"unknown", "none"}) or total is not None or weighted is not None or usage["rate_card_version"] is not None:
            raise ReceiptError("usage_unknown_invariant")


def _validate_receipt_shape(receipt: Any, *, require_id: bool = True) -> None:
    if not isinstance(receipt, dict) or set(receipt) != TOP_KEYS:
        raise ReceiptError("top_level_shape")
    if isinstance(receipt["schema_version"], bool) or receipt["schema_version"] != SCHEMA_VERSION or (require_id and (not isinstance(receipt["receipt_id"], str) or RECEIPT_ID_RE.fullmatch(receipt["receipt_id"]) is None)):
        raise ReceiptError("schema_version_or_id")
    if not _safe_text(receipt["project_id"]) or not _safe_text(receipt["codex_task_id"], ID_RE) or not _safe_text(receipt["milestone_id"], ID_RE):
        raise ReceiptError("identity_values")
    if not _enum(receipt["family"], FAMILIES) or not _enum(receipt["size_risk_band"], RISK_BANDS) or not _enum(receipt["disposition"], DISPOSITIONS):
        raise ReceiptError("enum_value")
    started = _timestamp(receipt["started_at"])
    closed = _timestamp(receipt["closed_at"])
    if started is None or closed is None or started > closed:
        raise ReceiptError("invalid_time")
    if receipt["decision_owner"] != "sol":
        raise ReceiptError("decision_owner")
    if receipt["disposition"] == "accepted" and receipt["accepted_by"] != "sol":
        raise ReceiptError("accepted_by_required")
    if receipt["disposition"] != "accepted" and receipt["accepted_by"] is not None:
        raise ReceiptError("accepted_by_forbidden")
    if receipt["accepted_by"] not in ("sol", None) or not isinstance(receipt["user_confirmation"], (bool, type(None))):
        raise ReceiptError("confirmation_value")
    runtime = receipt["root_runtime"]
    if not isinstance(runtime, dict) or set(runtime) != {"model", "reasoning", "service_tier", "service_tier_provenance"} or runtime["model"] != "gpt-5.6-sol" or not _enum(runtime["reasoning"], ROOT_REASONING) or not _enum(runtime["service_tier"], {"standard", "default"}) or not _enum(runtime["service_tier_provenance"], {"global-unset-standard", "explicit-standard"}):
        raise ReceiptError("root_runtime")
    profile = _validate_hashes(receipt["repository"])
    lanes = receipt["delegated_lanes"]
    if not isinstance(lanes, list) or len(lanes) > 32:
        raise ReceiptError("lanes_shape")
    lane_ids = set()
    for lane in lanes:
        _validate_lane(lane, profile)
        if lane["lane_id"] in lane_ids:
            raise ReceiptError("duplicate_lane_id")
        lane_ids.add(lane["lane_id"])
    _validate_checks(receipt["acceptance_checks"])
    if isinstance(receipt["rework_count"], bool) or not isinstance(receipt["rework_count"], int) or not 0 <= receipt["rework_count"] <= 1000:
        raise ReceiptError("rework_count")
    risks = receipt["risks"]
    if not isinstance(risks, list) or len(risks) > 32:
        raise ReceiptError("risk_codes")
    for risk in risks:
        if not isinstance(risk, dict) or set(risk) != {"code", "severity", "status"} or not _enum(risk["code"], RISK_CODES) or not _enum(risk["severity"], {"low", "medium", "high", "critical"}) or not _enum(risk["status"], {"open", "mitigated", "accepted"}):
            raise ReceiptError("risk_shape")
    if receipt["disposition"] == "accepted":
        if any(check["result"] in {"fail", "unknown"} for check in receipt["acceptance_checks"]):
            raise ReceiptError("accepted_check_not_pass")
        if any(risk["status"] == "open" and risk["severity"] in {"high", "critical"} for risk in risks):
            raise ReceiptError("accepted_risk_open")
    _validate_usage(receipt["usage"])
    if receipt["origin"] != ORIGIN:
        raise ReceiptError("origin")


def receipt_profile(receipt: Any) -> Optional[str]:
    """Return the validated Luna profile without exposing receipt content."""

    try:
        _walk_privacy(receipt)
        _validate_receipt_shape(receipt)
        payload = dict(receipt)
        receipt_id = payload.pop("receipt_id")
        if receipt_id != "mr1-" + hashlib.sha256(_canonical(payload)).hexdigest():
            raise ReceiptError("receipt_id_mismatch")
        return _validate_hashes(receipt["repository"])
    except (ReceiptError, TypeError, ValueError, OverflowError, MemoryError, RecursionError):
        return None


def validate_receipt(receipt: Any) -> Dict[str, Any]:
    """Return a sanitized validation result without echoing content or paths."""

    try:
        _walk_privacy(receipt)
        _validate_receipt_shape(receipt)
        payload = dict(receipt)
        receipt_id = payload.pop("receipt_id")
        expected = "mr1-" + hashlib.sha256(_canonical(payload)).hexdigest()
        if receipt_id != expected:
            raise ReceiptError("receipt_id_mismatch")
        return {"ok": True, "error": None}
    except (ReceiptError, TypeError, ValueError, OverflowError, MemoryError, RecursionError) as exc:
        code = exc.code if isinstance(exc, ReceiptError) else "invalid_receipt"
        return {"ok": False, "error": code}


def verify_receipt_policy(root: Path | str = DEFAULT_ROOT) -> Dict[str, Any]:
    """Verify receipt-policy.v2 while preserving historical v1 artifacts."""

    path = Path(root) / "config" / "receipt-policy.v2.json"
    try:
        if _path_has_symlink_component(path) or not path.is_file():
            raise ReceiptError("receipt_policy_unavailable")
        data = path.read_bytes()
        if len(data) > MAX_INPUT_BYTES:
            raise ReceiptError("receipt_policy_oversize")
        value = _strict_loads(data.decode("utf-8"))
        if value != RECEIPT_POLICY_CONTRACT:
            raise ReceiptError("receipt_policy_drift")
        return {"ok": True, "version": RECEIPT_POLICY_VERSION, "errors": []}
    except (ReceiptError, OSError, UnicodeError, ValueError, MemoryError, RecursionError) as exc:
        code = exc.code if isinstance(exc, ReceiptError) else "receipt_policy_invalid"
        return {"ok": False, "version": RECEIPT_POLICY_VERSION, "errors": [code]}


def select_receipt_tier(context: Any, root: Path | str = DEFAULT_ROOT) -> Dict[str, Any]:
    """Select none, minimal, or full from a closed trigger matrix."""

    policy = verify_receipt_policy(root)
    if not policy["ok"]:
        return {"ok": False, "tier": "full", "measurement": "unknown", "reason": "policy_invalid"}
    if not isinstance(context, dict) or set(context) != RECEIPT_TIER_CONTEXT_FIELDS:
        return {"ok": False, "tier": "full", "measurement": "unknown", "reason": "malformed_context"}
    band = context.get("work_band")
    delegated = context.get("delegated")
    outcome = context.get("outcome")
    categories = context.get("categories")
    rework = context.get("material_rework")
    audit = context.get("explicit_audit")
    automatic = context.get("automatic_collection_available")
    if (
        band not in RECEIPT_WORK_BANDS
        or outcome not in RECEIPT_OUTCOMES
        or not isinstance(delegated, bool)
        or not isinstance(rework, bool)
        or not isinstance(audit, bool)
        or not isinstance(automatic, bool)
        or not isinstance(categories, list)
        or len(categories) > len(FULL_RECEIPT_CATEGORIES)
        or any(not isinstance(item, str) or item not in FULL_RECEIPT_CATEGORIES for item in categories)
        or len(categories) != len(set(categories))
    ):
        return {"ok": False, "tier": "full", "measurement": "unknown", "reason": "malformed_context"}
    if (
        band in {"high_risk", "critical"}
        or outcome in {"failed", "blocked", "abandoned"}
        or rework
        or audit
        or bool(categories)
    ):
        return {"ok": True, "tier": "full", "measurement": "formal", "reason": "full_trigger"}
    if delegated and automatic:
        return {"ok": True, "tier": "minimal", "measurement": "automatic", "reason": "routine_delegated"}
    if delegated:
        return {"ok": True, "tier": "none", "measurement": "unknown", "reason": "automatic_collection_unavailable"}
    return {"ok": True, "tier": "none", "measurement": "not_applicable", "reason": "direct_handoff_only"}


def _validate_routine_record_common(record: Any) -> None:
    spawn = record.get("spawn")
    if (
        not isinstance(spawn, dict)
        or set(spawn) != {"decision", "useful"}
        or spawn.get("decision") != "delegate"
        or not isinstance(spawn.get("useful"), bool)
    ):
        raise ReceiptError("routine_record_spawn")
    if not _enum(record.get("outcome"), ROUTINE_RECORD_OUTCOMES):
        raise ReceiptError("routine_record_outcome")
    checks = record.get("checks")
    if not isinstance(checks, list) or len(checks) > 8:
        raise ReceiptError("routine_record_checks")
    usage = record.get("usage")
    if not isinstance(usage, dict) or set(usage) != {"attribution", "total_tokens"}:
        raise ReceiptError("routine_record_usage")
    total = usage.get("total_tokens")
    if usage.get("attribution") == "attributable":
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ReceiptError("routine_record_usage")
    elif usage.get("attribution") == "unknown":
        if total is not None:
            raise ReceiptError("routine_record_usage")
    else:
        raise ReceiptError("routine_record_usage")


def _validate_legacy_routine_record_shape(record: Any) -> None:
    if not isinstance(record, dict) or set(record) != LEGACY_ROUTINE_RECORD_FIELDS:
        raise ReceiptError("routine_record_shape")
    try:
        if len(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > 2048:
            raise ReceiptError("routine_record_oversize")
    except (TypeError, UnicodeError, MemoryError, OverflowError, RecursionError) as exc:
        raise ReceiptError("routine_record_invalid") from exc
    if record.get("schema_version") != 1 or isinstance(record.get("schema_version"), bool) or record.get("version") != LEGACY_ROUTINE_RECORD_VERSION:
        raise ReceiptError("routine_record_version")
    _validate_routine_record_common(record)
    checks = record.get("checks")
    assert isinstance(checks, list)
    for check in checks:
        if (
            not isinstance(check, dict)
            or set(check) != {"name", "status"}
            or not isinstance(check.get("name"), str)
            or not check["name"].strip()
            or check["name"] != check["name"].strip()
            or len(check["name"]) > 160
            or any(character in check["name"] for character in ("\x00", "\n", "\r", "\t"))
            or any(marker in check["name"].lower() for marker in ("password=", "api_key=", "authorization: bearer"))
            or CREDENTIAL_RE.search(check["name"]) is not None
            or check.get("status") not in ROUTINE_CHECK_RESULTS
        ):
            raise ReceiptError("routine_record_checks")
    _walk_privacy(record)


def _validate_routine_record_shape(record: Any) -> None:
    if not isinstance(record, dict) or set(record) != ROUTINE_RECORD_FIELDS:
        if isinstance(record, dict) and record.get("version") == LEGACY_ROUTINE_RECORD_VERSION:
            _validate_legacy_routine_record_shape(record)
            return
        raise ReceiptError("routine_record_shape")
    try:
        encoded = json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, MemoryError, OverflowError, RecursionError) as exc:
        raise ReceiptError("routine_record_invalid") from exc
    if len(encoded) > 2048:
        raise ReceiptError("routine_record_oversize")
    if record.get("schema_version") != 2 or isinstance(record.get("schema_version"), bool) or record.get("version") != ROUTINE_RECORD_VERSION:
        raise ReceiptError("routine_record_version")
    recorded_on = record.get("recorded_on")
    if not isinstance(recorded_on, str) or RECORDED_DATE_RE.fullmatch(recorded_on) is None:
        raise ReceiptError("routine_record_date")
    try:
        datetime.strptime(recorded_on, "%Y-%m-%d")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReceiptError("routine_record_date") from exc
    context = record.get("context")
    if not isinstance(context, dict) or set(context) != {
        "routing_policy", "profile", "role_kind", "task_class", "benefit_code"
    }:
        raise ReceiptError("routine_record_context")
    if (
        not isinstance(context.get("routing_policy"), str)
        or len(context["routing_policy"]) > 32
        or ROUTING_POLICY_RE.fullmatch(context["routing_policy"]) is None
        or not _enum(context.get("profile"), ROUTINE_PROFILES)
        or not _enum(context.get("role_kind"), ROUTINE_ROLE_KINDS)
        or not _enum(context.get("task_class"), ROUTINE_TASK_CLASSES)
        or not _enum(context.get("benefit_code"), ROUTINE_BENEFIT_CODES)
    ):
        raise ReceiptError("routine_record_context")
    _validate_routine_record_common(record)
    checks = record.get("checks")
    assert isinstance(checks, list)
    for index, check in enumerate(checks, 1):
        if (
            not isinstance(check, dict)
            or set(check) != {"name", "status"}
            or check.get("name") != f"acceptance-{index}"
            or not _enum(check.get("status"), ROUTINE_CHECK_RESULTS)
        ):
            raise ReceiptError("routine_record_checks")
    _walk_privacy(record)


def validate_routine_record(record: Any) -> Dict[str, Any]:
    try:
        _validate_routine_record_shape(record)
        return {"ok": True, "error": None}
    except (ReceiptError, TypeError, ValueError, OverflowError, MemoryError, RecursionError) as exc:
        code = exc.code if isinstance(exc, ReceiptError) else "invalid_routine_record"
        return {"ok": False, "error": code}


def build_routine_record(
    *,
    routing_policy: str,
    profile: str,
    role_kind: str,
    task_class: str,
    benefit_code: str,
    useful: bool,
    outcome: str,
    checks: Sequence[Mapping[str, str]],
    total_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a v2 record; the writer derives its UTC day and accepts no prose."""

    record = {
        "schema_version": 2,
        "version": ROUTINE_RECORD_VERSION,
        "recorded_on": datetime.now(timezone.utc).date().isoformat(),
        "context": {
            "routing_policy": routing_policy,
            "profile": profile,
            "role_kind": role_kind,
            "task_class": task_class,
            "benefit_code": benefit_code,
        },
        "spawn": {"decision": "delegate", "useful": useful},
        "outcome": outcome,
        "checks": [dict(item) for item in checks],
        "usage": {
            "attribution": "attributable" if total_tokens is not None else "unknown",
            "total_tokens": total_tokens,
        },
    }
    _validate_routine_record_shape(record)
    return record


def close_routine_record(record: Any, records_dir: Path) -> Dict[str, Any]:
    """Atomically persist one privacy-safe routine outcome without task identifiers."""

    _validate_routine_record_shape(record)
    if record.get("version") != ROUTINE_RECORD_VERSION:
        raise ReceiptError("historical_routine_record_write_forbidden")
    target_dir = _safe_routine_dir(records_dir)
    data = _canonical(record)
    target: Optional[Path] = None
    for _ in range(8):
        candidate = target_dir / ("routine-" + secrets.token_hex(16) + ".json")
        if not candidate.exists() and not platform_fs.is_link_like(candidate):
            target = candidate
            break
    if target is None:
        raise ReceiptError("routine_record_name_unavailable")
    assert target is not None
    try:
        platform_fs.atomic_create(target, data)
    except FileExistsError as exc:
        raise ReceiptError("routine_record_collision") from exc
    except OSError as exc:
        raise ReceiptError("routine_record_write_failed") from exc
    return {"ok": True, "recorded": True, "version": ROUTINE_RECORD_VERSION}


def _safe_routine_dir(path: Path) -> Path:
    """Resolve one project-local ``.sol-luna/routine-records`` directory."""

    try:
        absolute = path.absolute()
        if absolute.name != "routine-records" or absolute.parent.name != ".sol-luna":
            raise ReceiptError("unsafe_routine_records_dir")
        project = absolute.parent.parent
        broad = {
            Path("/").resolve(),
            Path.home().resolve(),
        }
        broad.update(platform_fs.shared_temp_roots())
        resolved_project = project.resolve()
        if (
            resolved_project in broad
            or resolved_project.parent == resolved_project
            or _path_has_symlink_component(project)
        ):
            raise ReceiptError("unsafe_routine_records_dir")
        if not project.is_dir() or platform_fs.is_link_like(project):
            raise ReceiptError("unsafe_routine_records_dir")
        project_marker = project / ".git"
        metadata = project / ".sol-luna"
        if not metadata.exists():
            if not project_marker.exists() or platform_fs.is_link_like(project_marker):
                raise ReceiptError("ambiguous_workspace_root")
            metadata.mkdir(mode=0o700, exist_ok=False)
        if platform_fs.is_link_like(metadata) or not metadata.is_dir():
            raise ReceiptError("unsafe_routine_records_dir")
        if not platform_fs.mode_matches(metadata, 0o700):
            raise ReceiptError("routine_metadata_permissions")
    except ReceiptError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ReceiptError("unsafe_routine_records_dir") from exc
    return _safe_dir(absolute, create=True)


def _safe_dir(path: Path, *, create: bool = False) -> Path:
    if _path_has_symlink_component(path):
        raise ReceiptError("unsafe_receipts_dir")
    if path.exists() and (platform_fs.is_link_like(path) or not path.is_dir()):
        raise ReceiptError("unsafe_receipts_dir")
    if not path.exists():
        if not create:
            raise ReceiptError("receipts_dir_missing")
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    if platform_fs.is_link_like(path) or not path.is_dir():
        raise ReceiptError("unsafe_receipts_dir")
    if not platform_fs.mode_matches(path, 0o700):
        raise ReceiptError("receipts_dir_permissions")
    return path


def _receipt_file(path: Path) -> bytes:
    if _path_has_symlink_component(path) or not path.is_file():
        raise ReceiptError("unsafe_receipt_path")
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise ReceiptError("receipt_oversize")
    except (OSError, MemoryError, ReceiptError) as exc:
        if isinstance(exc, ReceiptError):
            raise
        raise ReceiptError("receipt_unreadable") from exc
    return data


def close_receipt(payload: Any, receipts_dir: Path) -> Dict[str, Any]:
    if not isinstance(payload, dict) or "receipt_id" in payload:
        raise ReceiptError("close_payload_shape")
    _walk_privacy(payload)
    required = TOP_KEYS - {"receipt_id"}
    if set(payload) != required:
        raise ReceiptError("close_payload_shape")
    canonical_payload = dict(payload)
    receipt_id = "mr1-" + hashlib.sha256(_canonical(canonical_payload)).hexdigest()
    receipt = dict(canonical_payload)
    receipt["receipt_id"] = receipt_id
    # Reorder is immaterial to canonical output, but shape validation is strict.
    _validate_receipt_shape(receipt)
    target_dir = _safe_dir(receipts_dir, create=True)
    target = target_dir / (receipt_id + ".json")
    data = _canonical(receipt)
    if target.exists() or platform_fs.is_link_like(target):
        try:
            target_stat = target.lstat()
        except OSError as exc:
            raise ReceiptError("unsafe_receipt_path") from exc
        if (
            not stat.S_ISREG(target_stat.st_mode)
            or stat.S_ISLNK(target_stat.st_mode)
            or platform_fs.is_link_like(target)
        ):
            raise ReceiptError("unsafe_receipt_path")
        if not platform_fs.mode_from_stat(target_stat, 0o600):
            raise ReceiptError("receipt_permissions")
        existing = _receipt_file(target)
        if existing == data:
            return {"ok": True, "receipt_id": receipt_id, "idempotent": True}
        raise ReceiptError("receipt_collision")
    try:
        platform_fs.atomic_create(target, data)
    except FileExistsError as exc:
        raise ReceiptError("receipt_collision") from exc
    except OSError as exc:
        raise ReceiptError("receipt_write_failed") from exc
    return {"ok": True, "receipt_id": receipt_id, "idempotent": False}


def validate_paths(paths: Sequence[Path], receipts_dir: Optional[Path] = None) -> Dict[str, Any]:
    targets: List[Path] = list(paths)
    if receipts_dir is not None:
        directory = _safe_dir(receipts_dir)
        targets.extend(sorted((p for p in directory.iterdir() if p.name.endswith(".json")), key=lambda p: p.name))
    if not targets:
        return {"ok": False, "validated_count": 0, "valid_count": 0, "invalid_count": 0, "errors": ["no_receipts"]}
    invalid: Dict[str, int] = {}
    valid_count = 0
    for path in targets:
        try:
            receipt = _strict_loads(_receipt_file(path).decode("utf-8"))
            result = validate_receipt(receipt)
        except (ReceiptError, UnicodeError, MemoryError, RecursionError) as exc:
            result = {"ok": False, "error": exc.code if isinstance(exc, ReceiptError) else "invalid_receipt"}
        if result["ok"]:
            valid_count += 1
        else:
            invalid[result["error"]] = invalid.get(result["error"], 0) + 1
    return {"ok": not invalid, "validated_count": len(targets), "valid_count": valid_count, "invalid_count": len(targets) - valid_count, "errors": sorted(invalid)}


def summarize(receipts_dir: Path) -> Dict[str, Any]:
    directory = _safe_dir(receipts_dir)
    receipts: List[Mapping[str, Any]] = []
    invalid = 0
    for path in sorted(directory.iterdir(), key=lambda p: p.name):
        if path.suffix != ".json":
            continue
        try:
            receipt = _strict_loads(_receipt_file(path).decode("utf-8"))
            result = validate_receipt(receipt)
            if result["ok"]:
                receipts.append(receipt)
            else:
                invalid += 1
        except (ReceiptError, UnicodeError, MemoryError, RecursionError):
            invalid += 1
    accepted = sum(1 for receipt in receipts if receipt["disposition"] == "accepted")
    rejected = sum(1 for receipt in receipts if receipt["disposition"] == "rejected")
    abandoned = sum(1 for receipt in receipts if receipt["disposition"] == "abandoned")
    terminal_complete = invalid == 0 and bool(receipts) and all(
        receipt["usage"]["coverage"] == "complete-full-workflow"
        and receipt["usage"]["provenance"] == "usage_reporter"
        and receipt["usage"]["rate_card_version"] == "rate-card.v1"
        and isinstance(receipt["usage"]["total_tokens"], int)
        and isinstance(receipt["usage"]["weighted_usage"], (int, float))
        and math.isfinite(float(receipt["usage"]["weighted_usage"]))
        for receipt in receipts
    )
    cohorts: Dict[Tuple[str, str, str, str, str, str], Dict[str, Any]] = {}
    if terminal_complete:
        for receipt in receipts:
            repository = receipt["repository"]
            hashes = repository["hashes"]
            key = (
                receipt["project_id"],
                receipt["family"],
                receipt["size_risk_band"],
                repository["bundle_version"],
                hashes["policy"],
                hashes["rate_card"],
            )
            cohort = cohorts.setdefault(key, {"accepted_outcome_count": 0, "total_weighted_usage": 0.0})
            cohort["accepted_outcome_count"] += int(receipt["disposition"] == "accepted")
            cohort["total_weighted_usage"] += float(receipt["usage"]["weighted_usage"])
        cohort_rows: List[Dict[str, Any]] = []
        for (project_id, family, size_risk_band, bundle_version, policy_hash, rate_card_hash), cohort in sorted(cohorts.items()):
            total = cohort["total_weighted_usage"]
            cohort_rows.append({
                "project_id": project_id,
                "family": family,
                "size_risk_band": size_risk_band,
                "bundle_version": bundle_version,
                "policy_hash": policy_hash,
                "rate_card_hash": rate_card_hash,
                "accepted_outcome_count": cohort["accepted_outcome_count"],
                "total_weighted_usage": total,
                "verified_outcomes_per_weighted_usage": cohort["accepted_outcome_count"] / total if total > 0 else None,
            })
        if len(cohort_rows) == 1:
            row = cohort_rows[0]
            usage = {
                "status": "known",
                "coverage": "complete-full-workflow",
                "total_weighted_usage": row["total_weighted_usage"],
                "verified_outcomes_per_weighted_usage": row["verified_outcomes_per_weighted_usage"],
                "reason": None if row["total_weighted_usage"] > 0 else "zero_weighted_usage",
                "provenance": "usage_reporter",
                "rate_card_version": "rate-card.v1",
                "cohorts": cohort_rows,
            }
        else:
            usage = {
                "status": "unknown",
                "coverage": "complete-full-workflow",
                "total_weighted_usage": None,
                "verified_outcomes_per_weighted_usage": None,
                "reason": "multiple_incomparable_cohorts",
                "provenance": "usage_reporter",
                "rate_card_version": "rate-card.v1",
                "cohorts": cohort_rows,
            }
    else:
        usage = {"status": "unknown", "coverage": "unknown", "total_weighted_usage": None, "verified_outcomes_per_weighted_usage": None, "reason": "incomplete_usage_or_no_terminal_receipts", "provenance": "unknown", "rate_card_version": None, "cohorts": []}
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": invalid == 0,
        "receipts_observed": len(receipts),
        "invalid_receipts": invalid,
        "accepted_count": accepted,
        "accepted_outcome_count": accepted,
        "rejected_count": rejected,
        "abandoned_count": abandoned,
        "accepted_numerator_observed": accepted,
        "receipt_coverage": "unknown",
        "receipt_coverage_reason": "no_start_registry",
        "usage": usage,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Close, validate, or summarize local milestone receipts.")
    sub = parser.add_subparsers(dest="command", required=True)
    close = sub.add_parser("close")
    close.add_argument("--input", required=True)
    close.add_argument("--receipts-dir", default=".sol-luna/receipts")
    routine = sub.add_parser(
        "close-routine",
        help="internal orchestration writer (not an end-user command)",
    )
    useful = routine.add_mutually_exclusive_group(required=True)
    useful.add_argument("--useful", action="store_true")
    useful.add_argument("--not-useful", action="store_true")
    routine.add_argument("--outcome", required=True, choices=sorted(ROUTINE_RECORD_OUTCOMES))
    routine.add_argument("--check", action="append", choices=sorted(ROUTINE_CHECK_RESULTS), default=[])
    routine.add_argument("--total-tokens", type=int)
    routine.add_argument("--workspace-root", default=".", help=argparse.SUPPRESS)
    routine.add_argument("--records-dir", help=argparse.SUPPRESS)
    routine.add_argument("--routing-policy", required=True, help=argparse.SUPPRESS)
    routine.add_argument("--profile", required=True, choices=sorted(ROUTINE_PROFILES), help=argparse.SUPPRESS)
    routine.add_argument("--role-kind", required=True, choices=sorted(ROUTINE_ROLE_KINDS), help=argparse.SUPPRESS)
    routine.add_argument("--task-class", required=True, choices=sorted(ROUTINE_TASK_CLASSES), help=argparse.SUPPRESS)
    routine.add_argument("--benefit-code", required=True, choices=sorted(ROUTINE_BENEFIT_CODES), help=argparse.SUPPRESS)
    validate = sub.add_parser("validate")
    validate.add_argument("paths", nargs="*")
    validate.add_argument("--receipts-dir")
    validate = sub.add_parser("summarize")
    validate.add_argument("--receipts-dir", default=".sol-luna/receipts")
    validate.add_argument("--format", choices=("json",), default="json")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "close":
            payload = _read_input(Path(args.input))
            result = close_receipt(payload, Path(args.receipts_dir))
        elif args.command == "close-routine":
            if len(args.check) > 8 or isinstance(args.total_tokens, bool) or (
                args.total_tokens is not None and args.total_tokens < 0
            ):
                raise ReceiptError("routine_record_cli")
            record = build_routine_record(
                routing_policy=args.routing_policy,
                profile=args.profile,
                role_kind=args.role_kind,
                task_class=args.task_class,
                benefit_code=args.benefit_code,
                useful=bool(args.useful and not args.not_useful),
                outcome=args.outcome,
                checks=[
                    {"name": f"acceptance-{index}", "status": status}
                    for index, status in enumerate(args.check, 1)
                ],
                total_tokens=args.total_tokens,
            )
            records_dir = (
                Path(args.records_dir)
                if args.records_dir
                else Path(args.workspace_root) / ".sol-luna" / "routine-records"
            )
            result = close_routine_record(record, records_dir)
        elif args.command == "validate":
            paths = [Path(path) for path in args.paths]
            result = validate_paths(paths, Path(args.receipts_dir) if args.receipts_dir else None)
        else:
            result = summarize(Path(args.receipts_dir))
        print(json.dumps(result, sort_keys=True, separators=(",", ": ")))
        return 0 if result.get("ok") else 1
    except (ReceiptError, OSError, UnicodeError, MemoryError, OverflowError, RecursionError, TypeError, ValueError) as exc:
        code = exc.code if isinstance(exc, ReceiptError) else "operation_failed"
        print(json.dumps({"ok": False, "errors": [code]}, sort_keys=True, separators=(",", ": ")))
        return 1


if __name__ == "__main__":
    sys.exit(main())
