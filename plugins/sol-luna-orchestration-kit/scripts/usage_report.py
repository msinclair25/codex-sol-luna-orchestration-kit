#!/usr/bin/env python3
"""Best-effort aggregate usage metrics from Codex rollout JSONL files.

The rollout files are an internal, evolving format.  This module deliberately
keeps the public output small: model/role labels and numeric aggregates only.
It never prints prompt text, tool arguments or outputs, paths, identifiers, or
other message contents from a rollout.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


TOKEN_KEYS = ("input", "cached_input", "output", "reasoning", "total")
_TOKEN_FIELD_NAMES = {
    "input": "input_tokens",
    "cached_input": "cached_input_tokens",
    "output": "output_tokens",
    "reasoning": "reasoning_output_tokens",
    "total": "total_tokens",
}

_TOOL_RESPONSE_TYPES = {
    "custom_tool_call",
    "function_call",
    "local_shell_call",
    "mcp_tool_call",
    "tool_call",
}
_TOOL_EVENT_START_MARKERS = (
    "tool_call_begin",
    "tool_call_start",
    "tool_started",
    "mcp_tool_call_begin",
    "mcp_tool_call_start",
)

# Keep labels to runtime metadata tokens.  In particular, do not permit a
# slash: a path must never become report output even if metadata is malformed.
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9_.:+-]{1,80}$")
_UNKNOWN = "unknown"


def _safe_label(value: Any) -> str:
    """Return a bounded, non-sensitive label suitable for aggregate output."""

    if not isinstance(value, str):
        return _UNKNOWN
    value = value.strip()
    if not _SAFE_LABEL.fullmatch(value):
        return _UNKNOWN
    return value


def _as_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            return 0
        return max(0, number)
    return 0


def _parse_time(value: Any) -> Optional[int]:
    """Convert common Codex timestamps to UTC milliseconds."""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(number) or number <= 0:
            return None
        # task_started/task_complete use epoch seconds; some records use ms.
        milliseconds = number * 1000 if number < 100_000_000_000 else number
        # Keep conversion inside datetime's portable year 1..9999 range.
        if milliseconds > 253_402_300_799_999:
            return None
        return int(milliseconds)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return _parse_time(float(text))
        except ValueError:
            pass
        try:
            normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
            parsed = _datetime.datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_datetime.timezone.utc)
            return int(parsed.timestamp() * 1000)
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _date_from_record(record: Dict[str, Any], meta: Dict[str, Any]) -> Optional[_datetime.date]:
    for value in (meta.get("timestamp"), record.get("timestamp")):
        timestamp = _parse_time(value)
        if timestamp is not None:
            try:
                return _datetime.datetime.fromtimestamp(
                    timestamp / 1000, tz=_datetime.timezone.utc
                ).date()
            except (OverflowError, OSError, ValueError):
                continue
    return None


def _event_payload(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def _event_kind(record: Dict[str, Any]) -> str:
    if record.get("type") != "event_msg":
        return ""
    kind = _event_payload(record).get("type", "")
    return kind if isinstance(kind, str) else ""


def _token_usage(record: Dict[str, Any]) -> Optional[Dict[str, int]]:
    if _event_kind(record) != "token_count":
        return None
    info = _event_payload(record).get("info")
    if not isinstance(info, dict):
        return None
    usage = info.get("total_token_usage")
    if not isinstance(usage, dict):
        return None
    return {
        key: _as_nonnegative_int(usage.get(field_name))
        for key, field_name in _TOKEN_FIELD_NAMES.items()
    }


def _token_difference(final: Dict[str, int], baseline: Dict[str, int]) -> Tuple[Dict[str, int], bool]:
    values: Dict[str, int] = {}
    had_reset = False
    for key in TOKEN_KEYS:
        difference = final.get(key, 0) - baseline.get(key, 0)
        if difference < 0:
            had_reset = True
            difference = final.get(key, 0)
        values[key] = max(0, difference)
    return values, had_reset


def _empty_tokens() -> Dict[str, int]:
    return {key: 0 for key in TOKEN_KEYS}


def _add_tokens(target: Dict[str, int], values: Dict[str, int]) -> None:
    for key in TOKEN_KEYS:
        target[key] = target.get(key, 0) + _as_nonnegative_int(values.get(key))


def _task_started(record: Dict[str, Any]) -> bool:
    return _event_kind(record) == "task_started"


def _task_complete(record: Dict[str, Any]) -> bool:
    return _event_kind(record) == "task_complete"


def _record_time(record: Dict[str, Any]) -> Optional[int]:
    payload = _event_payload(record)
    return _parse_time(payload.get("occurred_at_ms")) or _parse_time(record.get("timestamp"))


def _task_start_time(record: Dict[str, Any]) -> Optional[int]:
    payload = _event_payload(record)
    return _parse_time(payload.get("started_at")) or _record_time(record)


def _task_complete_time(record: Dict[str, Any]) -> Optional[int]:
    payload = _event_payload(record)
    return _parse_time(payload.get("completed_at")) or _record_time(record)


def _task_duration(record: Dict[str, Any]) -> int:
    return _as_nonnegative_int(_event_payload(record).get("duration_ms"))


def _task_turn_id(record: Dict[str, Any]) -> Optional[str]:
    value = _event_payload(record).get("turn_id")
    return value if isinstance(value, str) and value else None


def _is_tool_start(record: Dict[str, Any]) -> bool:
    """Recognize starts without counting their separate output/end records."""

    if record.get("type") == "response_item":
        payload = _event_payload(record)
        kind = payload.get("type")
        return (
            isinstance(kind, str)
            and kind in _TOOL_RESPONSE_TYPES
            and bool(payload.get("call_id"))
        )
    kind = _event_kind(record).lower()
    return any(marker in kind for marker in _TOOL_EVENT_START_MARKERS)


@dataclass
class _Run:
    role: str
    model: str
    reasoning_effort: str
    service_tier: str
    tokens: Dict[str, int]
    token_usage_available: bool
    duration_ms: int
    tool_calls: int
    completed: bool
    intervals: List[Tuple[int, int]] = field(default_factory=list)


@dataclass
class _LoadResult:
    records: List[Dict[str, Any]]
    meta: Dict[str, Any]
    malformed: int = 0


def _iter_candidate_paths(inputs: Sequence[str]) -> Iterator[Path]:
    if inputs:
        for raw in inputs:
            path = Path(raw).expanduser()
            if path.is_file():
                yield path
            elif path.is_dir():
                yield from sorted(path.rglob("*.jsonl"))
            else:
                # Keep an explicit missing input visible to the summary
                # counters without ever echoing its path.
                yield path
        return
    default_root = Path.home() / ".codex" / "sessions"
    if default_root.is_dir():
        yield from sorted(default_root.rglob("*.jsonl"))


def _load_file(path: Path) -> _LoadResult:
    records: List[Dict[str, Any]] = []
    malformed = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except (TypeError, ValueError, json.JSONDecodeError):
                    malformed += 1
                    continue
                if not isinstance(record, dict):
                    malformed += 1
                    continue
                records.append(record)
    except (OSError, UnicodeError):
        return _LoadResult([], {}, malformed=malformed + 1)

    metadata: Dict[str, Any] = {}
    for record in records:
        if record.get("type") == "session_meta":
            candidate = _event_payload(record)
            if candidate:
                metadata = candidate
    return _LoadResult(records, metadata, malformed=malformed)


def _last_settings(records: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    settings: Dict[str, str] = {
        "model": _UNKNOWN,
        "reasoning_effort": _UNKNOWN,
        "service_tier": _UNKNOWN,
    }
    # Older or interrupted rollouts may not contain thread_settings_applied.
    # Use turn_context only as a fallback, then let the authoritative settings
    # event below override it.
    for record in records:
        if record.get("type") != "turn_context":
            continue
        candidate = _event_payload(record)
        model = _safe_label(candidate.get("model"))
        effort = _safe_label(candidate.get("effort"))
        collaboration = candidate.get("collaboration_mode")
        if isinstance(collaboration, dict):
            nested = collaboration.get("settings")
            if isinstance(nested, dict):
                nested_model = _safe_label(nested.get("model"))
                nested_effort = _safe_label(nested.get("reasoning_effort"))
                if nested_model != _UNKNOWN:
                    model = nested_model
                if nested_effort != _UNKNOWN:
                    effort = nested_effort
        if model != _UNKNOWN:
            settings["model"] = model
        if effort != _UNKNOWN:
            settings["reasoning_effort"] = effort

    for record in records:
        if _event_kind(record) != "thread_settings_applied":
            continue
        candidate = _event_payload(record).get("thread_settings")
        if not isinstance(candidate, dict):
            continue
        for key in settings:
            safe = _safe_label(candidate.get(key))
            if safe != _UNKNOWN:
                settings[key] = safe
    return settings


def _final_token_usage(records: Sequence[Dict[str, Any]], before_index: Optional[int] = None) -> Dict[str, int]:
    latest = _empty_tokens()
    for index, record in enumerate(records):
        if before_index is not None and index >= before_index:
            break
        usage = _token_usage(record)
        if usage is not None:
            latest = usage
    return latest


def _matching_completes(
    records: Sequence[Dict[str, Any]], start_index: int, turn_id: Optional[str]
) -> List[Tuple[int, Dict[str, Any]]]:
    matches: List[Tuple[int, Dict[str, Any]]] = []
    for index in range(start_index + 1, len(records)):
        record = records[index]
        if not _task_complete(record):
            continue
        candidate_turn = _task_turn_id(record)
        if turn_id is None or candidate_turn == turn_id:
            matches.append((index, record))
    return matches


def _run_from_records(records: Sequence[Dict[str, Any]], metadata: Dict[str, Any]) -> Optional[_Run]:
    starts = [index for index, record in enumerate(records) if _task_started(record)]
    settings = _last_settings(records)
    is_child = bool(metadata.get("forked_from_id") or metadata.get("parent_thread_id"))
    role = _safe_label(metadata.get("agent_role"))
    if role == _UNKNOWN:
        role = "subagent" if is_child else "root"

    final_usage = _final_token_usage(records)

    duration_ms = 0
    completed = False
    tool_calls = 0
    intervals: List[Tuple[int, int]] = []

    token_usage_available = any(_token_usage(record) is not None for record in records)

    if starts:
        last_start_index = starts[-1]
        last_start = records[last_start_index]
        matching = _matching_completes(records, last_start_index, _task_turn_id(last_start))
        if is_child:
            if matching:
                complete_index, complete = matching[-1]
                duration_ms = _task_duration(complete)
                completed = True
                start_time = _task_start_time(last_start)
                end_time = _task_complete_time(complete)
                if start_time is not None and end_time is not None and end_time >= start_time:
                    intervals.append((start_time, end_time))
            own_start = last_start_index
        else:
            # Root usage is cumulative and root active time is the sum of all
            # completed turns, while each completed turn contributes its own
            # interval for overlap/concurrency calculations.
            completes = [
                (index, record)
                for index, record in enumerate(records)
                if _task_complete(record)
            ]
            duration_ms = sum(_task_duration(record) for _, record in completes)
            # A root can contain many historical turns.  Completion describes
            # the final turn in this rollout, not merely an earlier success.
            completed = bool(matching)
            for complete_index, complete in completes:
                turn_id = _task_turn_id(complete)
                matching_starts = [
                    record for record in records[: complete_index] if _task_started(record) and (
                        turn_id is None or _task_turn_id(record) == turn_id
                    )
                ]
                start_record = matching_starts[-1] if matching_starts else None
                start_time = _task_start_time(start_record) if start_record else None
                end_time = _task_complete_time(complete)
                if start_time is not None and end_time is not None and end_time >= start_time:
                    intervals.append((start_time, end_time))
            own_start = starts[0]

        # A response item/tool event is a call start; its output/end is not.
        tool_calls = sum(1 for record in records[own_start + 1 :] if _is_tool_start(record))
        if is_child:
            has_baseline = any(
                _token_usage(record) is not None
                for record in records[:last_start_index]
            )
            has_final = any(
                _token_usage(record) is not None
                for record in records[last_start_index:]
            )
            baseline = _final_token_usage(records, before_index=last_start_index)
            if has_baseline and has_final:
                tokens, _ = _token_difference(final_usage, baseline)
                token_usage_available = True
            else:
                # Without both snapshots there is no reliable way to separate
                # inherited fork context from usage produced by the child.
                tokens = _empty_tokens()
                token_usage_available = False
        else:
            tokens = final_usage
    else:
        # A child rollout without its own task boundary may contain only the
        # forked parent's cumulative counters.  Attributing those counters to
        # the child would substantially over-report delegated usage.
        tokens = _empty_tokens() if is_child else final_usage
        if is_child:
            token_usage_available = False

    return _Run(
        role=role,
        model=settings["model"],
        reasoning_effort=settings["reasoning_effort"],
        service_tier=settings["service_tier"],
        tokens=tokens,
        token_usage_available=token_usage_available,
        duration_ms=duration_ms,
        tool_calls=tool_calls,
        completed=completed,
        intervals=intervals,
    )


def _union_and_concurrency(intervals: Iterable[Tuple[int, int]]) -> Tuple[int, int]:
    valid = [(start, end) for start, end in intervals if end >= start]
    if not valid:
        return 0, 0
    events: List[Tuple[int, int]] = []
    for start, end in valid:
        if end == start:
            continue
        events.append((start, 1))
        events.append((end, -1))
    if not events:
        return 0, 0
    events.sort(key=lambda item: (item[0], item[1]))  # ends before starts at a tie
    active = 0
    maximum = 0
    union = 0
    previous: Optional[int] = None
    for moment, delta in events:
        if previous is not None and moment > previous and active > 0:
            union += moment - previous
        active += delta
        maximum = max(maximum, active)
        previous = moment
    return union, maximum


def _aggregate_group(runs: Sequence[_Run]) -> Dict[str, Any]:
    first = runs[0]
    tokens = _empty_tokens()
    duration = 0
    tool_calls = 0
    completed = 0
    token_usage_runs = 0
    for run in runs:
        _add_tokens(tokens, run.tokens)
        duration += run.duration_ms
        tool_calls += run.tool_calls
        completed += int(run.completed)
        token_usage_runs += int(run.token_usage_available)
    return {
        "role": first.role,
        "model": first.model,
        "reasoning_effort": first.reasoning_effort,
        "service_tier": first.service_tier,
        "runs": len(runs),
        "completed": completed,
        "incomplete": len(runs) - completed,
        "token_usage_runs": token_usage_runs,
        "duration_ms": duration,
        "tool_calls": tool_calls,
        "tokens": tokens,
    }


def analyze(paths: Optional[Sequence[str]] = None, since: Optional[Any] = None) -> Dict[str, Any]:
    """Analyze rollout files and return privacy-safe aggregate metrics.

    ``paths`` may contain files or directories.  With no paths, the standard
    ``~/.codex/sessions`` directory is scanned.  ``since`` accepts a
    ``datetime.date`` or ``YYYY-MM-DD`` string and is inclusive in UTC.
    """

    if since is None:
        since_date = None
    elif isinstance(since, _datetime.date):
        since_date = since
    else:
        since_date = _parse_since(str(since))

    warnings: List[str] = [
        "Best effort: rollout JSONL is an internal format and may change across Codex versions.",
        "Prompts, tool arguments, outputs, paths, and identifiers are intentionally excluded.",
        "Timestamp wall spans may include idle or waiting time; overlap is not compute utilization, speedup, or cost savings.",
    ]
    candidates = list(_iter_candidate_paths(paths or []))
    # Avoid duplicate files when a directory and one of its files are supplied.
    unique: List[Path] = []
    seen = set()
    for path in candidates:
        try:
            marker = str(path.resolve())
        except OSError:
            marker = str(path)
        if marker not in seen:
            seen.add(marker)
            unique.append(path)

    runs: List[_Run] = []
    malformed_files = 0
    malformed_records = 0
    unrecognized_files = 0
    for path in unique:
        loaded = _load_file(path)
        malformed_records += loaded.malformed
        if loaded.malformed:
            malformed_files += 1
        if not loaded.meta:
            unrecognized_files += 1
            continue
        record_date = None
        for record in loaded.records:
            if record.get("type") == "session_meta":
                record_date = _date_from_record(record, loaded.meta)
                if record_date is not None:
                    break
        if since_date is not None and (record_date is None or record_date < since_date):
            continue
        run = _run_from_records(loaded.records, loaded.meta)
        if run is not None:
            runs.append(run)

    if malformed_files:
        warnings.append(
            "Skipped malformed records in %d file(s) (%d record(s))."
            % (malformed_files, malformed_records)
        )
    if unrecognized_files:
        warnings.append("Skipped %d unrecognized or unreadable file(s)." % unrecognized_files)
    if not runs:
        warnings.append("No recognized rollout sessions matched the requested range.")

    groups: Dict[Tuple[str, str, str, str], List[_Run]] = defaultdict(list)
    for run in runs:
        groups[(run.role, run.model, run.reasoning_effort, run.service_tier)].append(run)
    ordered_groups = [
        _aggregate_group(groups[key])
        for key in sorted(groups)
    ]

    tokens = _empty_tokens()
    duration = 0
    tool_calls = 0
    completed_count = 0
    token_usage_runs = 0
    intervals: List[Tuple[int, int]] = []
    for run in runs:
        _add_tokens(tokens, run.tokens)
        duration += run.duration_ms
        tool_calls += run.tool_calls
        completed_count += int(run.completed)
        token_usage_runs += int(run.token_usage_available)
        intervals.extend(run.intervals)
    wall_time, max_concurrency = _union_and_concurrency(intervals)
    # Use only intervals with both endpoints for a parallelism estimate.  A
    # task duration can still be reported when timestamps are unavailable, but
    # it must not inflate the known wall-clock denominator or numerator.
    known_interval_active_time = sum(max(0, end - start) for start, end in intervals)
    parallelism = (known_interval_active_time / wall_time) if wall_time else None

    unavailable_token_runs = len(runs) - token_usage_runs
    if unavailable_token_runs:
        warnings.append(
            "Token usage was unavailable for %d run(s) without a usable snapshot or safe child baseline."
            % unavailable_token_runs
        )

    return {
        "schema_version": 1,
        "runs": len(runs),
        "completed": completed_count,
        "incomplete": len(runs) - completed_count,
        "token_usage_runs": token_usage_runs,
        "overall": {
            "tokens": tokens,
            "duration_ms": duration,
            "active_time_ms": duration,
            "wall_span_active_time_ms": known_interval_active_time,
            "wall_time_ms": wall_time,
            "max_concurrency": max_concurrency,
            "wall_span_overlap_ratio": parallelism,
            "tool_calls": tool_calls,
        },
        "groups": ordered_groups,
        "warnings": warnings,
    }


def _parse_since(value: str) -> _datetime.date:
    try:
        return _datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("--since must use YYYY-MM-DD")


def _format_number(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return "%.2f" % value
    return f"{value:,}" if isinstance(value, int) else str(value)


def to_markdown(report: Dict[str, Any]) -> str:
    overall = report["overall"]
    lines = [
        "# Codex usage report",
        "",
        "Best-effort aggregate metrics from local rollout logs; no prompts, tool content, paths, or identifiers are shown.",
        "",
        "## Overall",
        "",
        f"- Runs: {_format_number(report['runs'])} ({_format_number(report['completed'])} completed, {_format_number(report['incomplete'])} incomplete)",
        f"- Runs with safely attributable token usage: {_format_number(report['token_usage_runs'])}",
        f"- Active time: {_format_number(overall['active_time_ms'])} ms",
        f"- Summed task wall spans: {_format_number(overall['wall_span_active_time_ms'])} ms",
        f"- Union of task wall spans: {_format_number(overall['wall_time_ms'])} ms",
        f"- Wall-span overlap ratio: {_format_number(overall['wall_span_overlap_ratio'])}",
        f"- Maximum concurrency: {_format_number(overall['max_concurrency'])}",
        f"- Tool calls: {_format_number(overall['tool_calls'])}",
        f"- Tokens (input / cached input / output / reasoning / total): {', '.join(_format_number(overall['tokens'][key]) for key in TOKEN_KEYS)}",
        "",
        "## By role and runtime",
        "",
        "| Role | Model | Reasoning | Tier | Runs | Token runs | Completed | Duration (ms) | Tool calls | Input | Cached input | Output | Reasoning tokens | Total |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group in report["groups"]:
        lines.append(
            "| {role} | {model} | {reasoning_effort} | {service_tier} | {runs} | {token_usage_runs} | {completed} | {duration_ms} | {tool_calls} | {input} | {cached_input} | {output} | {reasoning} | {total} |".format(
                **group,
                input=_format_number(group["tokens"]["input"]),
                cached_input=_format_number(group["tokens"]["cached_input"]),
                output=_format_number(group["tokens"]["output"]),
                reasoning=_format_number(group["tokens"]["reasoning"]),
                total=_format_number(group["tokens"]["total"]),
            )
        )
    if not report["groups"]:
        lines.append("| — | — | — | — | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |")
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate privacy-safe metrics from Codex rollout JSONL files."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="rollout JSONL files or directories (default: ~/.codex/sessions)",
    )
    parser.add_argument("--since", type=_parse_since, help="inclusive UTC date (YYYY-MM-DD)")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    report = analyze(args.paths, since=args.since)
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(to_markdown(report), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CLI smoke tests
    sys.exit(main())
