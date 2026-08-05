#!/usr/bin/env python3
"""Fail-closed admission guard for supported Codex Agent tool calls.

The guard validates a self-contained assignment envelope against the bundled
Sol/Luna routing contract. It intentionally does not claim to enforce writes
after a child starts; current PreToolUse input does not identify the active
subagent for every write-capable tool path.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import platform_fs


MAX_INPUT_BYTES = 64 * 1024
MAX_TEXT_CHARS = 2000
MAX_LIST_ITEMS = 32
SAFE_LANE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
SPAWN_FIELDS = {
    "agent_type",
    "fork_turns",
    "message",
    "model",
    "reasoning_effort",
    "task_name",
}
ENVELOPE_REQUIRED_FIELDS = {"schema_version", "routing_request", "assignment"}
ENVELOPE_OPTIONAL_FIELDS = {"fallback_authorization"}
ASSIGNMENT_FIELDS = {
    "lane_id",
    "outcome",
    "relevant_inputs",
    "scope_or_owned_files",
    "constraints",
    "acceptance_checks",
    "expected_evidence",
    "risk_boundary",
    "deadline",
}
EXPECTED_EVIDENCE = [
    "status",
    "files_or_surfaces",
    "checks",
    "findings",
    "risks",
    "confidence",
    "recommendation",
]
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
routing_policy: Optional[Any] = None


class GuardError(ValueError):
    """One stable, non-sensitive guard failure code."""


def _strict_loads(raw: str) -> Any:
    if not isinstance(raw, str):
        raise GuardError("message_not_json_text")
    try:
        size = len(raw.encode("utf-8"))
    except (UnicodeError, MemoryError, OverflowError) as exc:
        raise GuardError("message_encoding") from exc
    if size > MAX_INPUT_BYTES:
        raise GuardError("message_too_large")

    def reject_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise GuardError("duplicate_json_key")
            result[key] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _: (_ for _ in ()).throw(GuardError("nonfinite_json")),
        )
    except GuardError:
        raise
    except (json.JSONDecodeError, RecursionError, MemoryError, UnicodeError) as exc:
        raise GuardError("message_invalid_json") from exc


def _bounded_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= MAX_TEXT_CHARS
        and "\x00" not in value
    )


def _bounded_text_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= MAX_LIST_ITEMS
        and all(_bounded_text(item) for item in value)
        and len(set(value)) == len(value)
    )


def _safe_project_root(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise GuardError("cwd_invalid")
    try:
        candidate = Path(raw)
        if not candidate.is_absolute() or platform_fs.is_link_like(candidate) or not candidate.is_dir():
            raise GuardError("cwd_invalid")
        current = Path(candidate.anchor)
        for part in candidate.parts[1:]:
            current /= part
            if platform_fs.is_link_like(current) and not platform_fs.allowed_system_link(current):
                raise GuardError("cwd_invalid")
        root = candidate.resolve()
        broad = {
            Path(root.anchor),
            Path.home().resolve(),
        }
        broad.update(platform_fs.shared_temp_roots())
        if not platform_fs.IS_WINDOWS:
            broad.update({Path("/var").resolve(), Path("/private/var").resolve()})
        if root in broad or len(root.parts) < 3:
            raise GuardError("cwd_too_broad")
        return root
    except GuardError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise GuardError("cwd_invalid") from exc


def _normalised_alias(relative: str) -> Tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in relative.split("/"))


def _ownership_safe_in_project(root: Path, ownership: Mapping[str, Iterable[str]]) -> bool:
    try:
        entries: List[Tuple[str, str, Path, Tuple[str, ...]]] = []
        for lane, paths in ownership.items():
            for relative in paths:
                current = root
                for part in relative.split("/"):
                    current = current / part
                    if platform_fs.is_link_like(current):
                        return False
                current.resolve(strict=False).relative_to(root)
                entries.append((lane, relative, current, _normalised_alias(relative)))
        for index, (left_lane, _, left_path, left_alias) in enumerate(entries):
            for right_lane, _, right_path, right_alias in entries[index + 1:]:
                if left_lane == right_lane:
                    continue
                alias_overlap = (
                    left_alias == right_alias
                    or left_alias == right_alias[:len(left_alias)]
                    or right_alias == left_alias[:len(right_alias)]
                )
                if alias_overlap:
                    return False
                if left_path.exists() and right_path.exists() and os.path.samefile(left_path, right_path):
                    return False
        return True
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _validate_assignment(assignment: Any) -> Dict[str, Any]:
    if not isinstance(assignment, dict) or set(assignment) != ASSIGNMENT_FIELDS:
        raise GuardError("assignment_shape")
    lane_id = assignment.get("lane_id")
    if not isinstance(lane_id, str) or SAFE_LANE_ID.fullmatch(lane_id) is None:
        raise GuardError("lane_id_invalid")
    for field in ("outcome", "risk_boundary", "deadline"):
        if not _bounded_text(assignment.get(field)):
            raise GuardError(f"assignment_{field}")
    for field in ("relevant_inputs", "scope_or_owned_files", "constraints", "acceptance_checks"):
        if not _bounded_text_list(assignment.get(field)):
            raise GuardError(f"assignment_{field}")
    if routing_policy is None or any(
        routing_policy._safe_ownership_relative(item) is None
        for item in assignment["relevant_inputs"]
    ):
        raise GuardError("assignment_relevant_inputs_unsafe")
    if assignment.get("expected_evidence") != EXPECTED_EVIDENCE:
        raise GuardError("evidence_contract")
    return assignment


def _validate_fallback_authorization(value: Any, lane_id: str) -> None:
    if routing_policy is None:
        raise GuardError("policy_module_unavailable")
    if not isinstance(value, dict) or set(value) != routing_policy.FALLBACK_AUTHORIZATION_FIELDS:
        raise GuardError("fallback_authorization_shape")
    max_attempts = value.get("max_attempts")
    if (
        value.get("authorized") is not True
        or value.get("target") != routing_policy.APP_TASK_FALLBACK["target"]
        or value.get("scope") != routing_policy.APP_TASK_FALLBACK["authorization_scope"]
        or value.get("lane_id") != lane_id
        or isinstance(max_attempts, bool)
        or max_attempts != routing_policy.APP_TASK_FALLBACK["max_attempts_per_lane"]
        or value.get("current_checkout") is not True
    ):
        raise GuardError("fallback_authorization_invalid")


def _validate_event(event: Any) -> None:
    if routing_policy is None:
        raise GuardError("policy_module_unavailable")
    if not isinstance(event, dict):
        raise GuardError("hook_input_shape")
    if event.get("hook_event_name") != "PreToolUse" or event.get("tool_name") != "Agent":
        raise GuardError("unsupported_hook_path")
    spawn = event.get("tool_input")
    if not isinstance(spawn, dict) or set(spawn) - SPAWN_FIELDS:
        raise GuardError("spawn_input_shape")
    for required in ("agent_type", "fork_turns", "message", "task_name"):
        if required not in spawn:
            raise GuardError(f"spawn_{required}_required")
    if spawn.get("fork_turns") != "none":
        raise GuardError("history_fork_denied")

    envelope = _strict_loads(spawn.get("message"))
    if (
        not isinstance(envelope, dict)
        or not ENVELOPE_REQUIRED_FIELDS.issubset(envelope)
        or set(envelope) - ENVELOPE_REQUIRED_FIELDS - ENVELOPE_OPTIONAL_FIELDS
    ):
        raise GuardError("envelope_shape")
    if envelope.get("schema_version") != 1:
        raise GuardError("envelope_version")
    assignment = _validate_assignment(envelope.get("assignment"))
    route_request = envelope.get("routing_request")
    if not isinstance(route_request, dict):
        raise GuardError("routing_request_shape")

    route = routing_policy.evaluate(route_request, PLUGIN_ROOT)
    if not route.get("ok"):
        codes = route.get("reason_codes")
        code = codes[0] if isinstance(codes, list) and codes else "routing_denied"
        raise GuardError(f"route_{code}")
    if spawn.get("agent_type") != route.get("route"):
        raise GuardError("role_mismatch")
    if "model" in spawn and spawn.get("model") != route.get("model"):
        raise GuardError("model_override_mismatch")
    if "reasoning_effort" in spawn and spawn.get("reasoning_effort") != route.get("reasoning"):
        raise GuardError("reasoning_override_mismatch")

    ownership = route_request.get("ownership")
    if not isinstance(ownership, dict):
        raise GuardError("ownership_shape")
    lane_count = route_request.get("lane_count", 1)
    if isinstance(lane_count, bool) or not isinstance(lane_count, int) or lane_count < 1 or lane_count > len(ownership):
        raise GuardError("ownership_wave_incomplete")
    lane_id = assignment["lane_id"]
    if lane_id not in ownership or spawn.get("task_name") != lane_id:
        raise GuardError("lane_identity_mismatch")
    if "fallback_authorization" in envelope:
        _validate_fallback_authorization(envelope["fallback_authorization"], lane_id)
    expected_paths = ownership[lane_id]
    if not isinstance(expected_paths, list) or sorted(assignment["scope_or_owned_files"]) != sorted(expected_paths):
        raise GuardError("assignment_ownership_mismatch")
    project_root = _safe_project_root(event.get("cwd"))
    if not _ownership_safe_in_project(project_root, ownership):
        raise GuardError("project_ownership_path_unsafe")


def _deny(code: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"sol-luna-guard:{code}",
        }
    }
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    global routing_policy
    try:
        try:
            import routing_policy as loaded_routing_policy
        except Exception as exc:
            raise GuardError("policy_module_unavailable") from exc
        routing_policy = loaded_routing_policy
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise GuardError("hook_input_too_large")
        try:
            decoded = raw.decode("utf-8")
        except UnicodeError as exc:
            raise GuardError("hook_input_encoding") from exc
        event = _strict_loads(decoded)
        _validate_event(event)
        return 0
    except GuardError as exc:
        _deny(str(exc))
        return 0
    except Exception:
        _deny("internal_error")
        return 0
    except (OSError, UnicodeError, TypeError, ValueError, RuntimeError, MemoryError, RecursionError):
        _deny("internal_error")
        return 0


if __name__ == "__main__":
    sys.exit(main())
