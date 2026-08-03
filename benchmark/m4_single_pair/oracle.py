#!/usr/bin/env python3
"""Held-out behavioral oracle for the M4 inventory fixture.

The runner invokes this file after a model run. It emits only aggregate JSON;
it never includes source, prompts, paths, exception text, or identifiers.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


def _load_inventory(workspace: Path) -> Any:
    path = workspace / "inventory.py"
    spec = importlib.util.spec_from_file_location("m4_inventory_candidate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate_import")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raises(call: Callable[[], Any]) -> None:
    try:
        call()
    except Exception:
        return
    raise AssertionError("expected_failure")


def evaluate(workspace: Path) -> dict[str, Any]:
    checks: list[tuple[str, Callable[[], None]]] = []
    try:
        inventory = _load_inventory(workspace)
    except Exception:
        return {"ok": False, "checks": 14, "passed": 0, "failed": 14}

    def happy_and_idempotent() -> None:
        initial = {"b": 2, "a": 5}
        operations = [
            {"id": "one", "sku": "a", "delta": -2},
            {"id": "two", "sku": "b", "delta": 3},
            {"id": "two", "sku": "b", "delta": 3},
        ]
        before = (copy.deepcopy(initial), copy.deepcopy(operations))
        result = inventory.apply_operations(initial, operations)
        assert result == {"a": 3, "b": 5}
        assert list(result) == ["a", "b"]
        assert before == (initial, operations)

    def invalid_initial_values() -> None:
        for value in (-1, True, 1.5, "1"):
            _raises(lambda value=value: inventory.apply_operations({"sku": value}, []))

    def invalid_names() -> None:
        bad = ("", "slash/name", "space name", "é", "x" * 65)
        for name in bad:
            _raises(lambda name=name: inventory.apply_operations({name: 1}, []))
            _raises(lambda name=name: inventory.apply_operations({}, [{"id": "ok", "sku": name, "delta": 1}]))

    def exact_operation_keys() -> None:
        _raises(lambda: inventory.apply_operations({}, [{"id": "x", "sku": "a"}]))
        _raises(lambda: inventory.apply_operations({}, [{"id": "x", "sku": "a", "delta": 1, "extra": 1}]))

    def invalid_deltas() -> None:
        for value in (0, True, 1.5, "1", 1_000_000_001, -1_000_000_001):
            _raises(lambda value=value: inventory.apply_operations({}, [{"id": "x", "sku": "a", "delta": value}]))

    def conflicting_duplicate() -> None:
        _raises(lambda: inventory.apply_operations({}, [
            {"id": "same", "sku": "a", "delta": 1},
            {"id": "same", "sku": "a", "delta": 2},
        ]))

    def overdraw() -> None:
        _raises(lambda: inventory.apply_operations({"a": 2}, [{"id": "x", "sku": "a", "delta": -3}]))

    def atomic_failure() -> None:
        initial = {"a": 2}
        operations = [
            {"id": "ok", "sku": "a", "delta": 1},
            {"id": "bad", "sku": "a", "delta": -4},
        ]
        before = (copy.deepcopy(initial), copy.deepcopy(operations))
        _raises(lambda: inventory.apply_operations(initial, operations))
        assert before == (initial, operations)

    def sequence_required() -> None:
        _raises(lambda: inventory.apply_operations({}, "not-a-sequence"))
        _raises(lambda: inventory.apply_operations([], []))

    def mapping_required() -> None:
        _raises(lambda: inventory.apply_operations({}, ["not-a-mapping"]))

    def cli_valid() -> None:
        request = {"initial": {"z": 0, "a": 1}, "operations": [{"id": "x", "sku": "z", "delta": 2}]}
        proc = subprocess.run(
            [sys.executable, str(workspace / "inventory.py")],
            input=json.dumps(request), text=True, capture_output=True, timeout=10, check=False,
        )
        assert proc.returncode == 0
        assert proc.stdout == '{"a":1,"z":2}\n'
        assert proc.stderr == ""

    def cli_invalid_json() -> None:
        proc = subprocess.run(
            [sys.executable, str(workspace / "inventory.py")],
            input="{", text=True, capture_output=True, timeout=10, check=False,
        )
        assert proc.returncode != 0 and proc.stdout == ""

    def cli_invalid_shape() -> None:
        for request in ({"initial": {}}, {"initial": {}, "operations": [], "extra": 1}, []):
            proc = subprocess.run(
                [sys.executable, str(workspace / "inventory.py")],
                input=json.dumps(request), text=True, capture_output=True, timeout=10, check=False,
            )
            assert proc.returncode != 0 and proc.stdout == ""

    def cli_single_document() -> None:
        proc = subprocess.run(
            [sys.executable, str(workspace / "inventory.py")],
            input='{"initial":{},"operations":[]}\n{}', text=True,
            capture_output=True, timeout=10, check=False,
        )
        assert proc.returncode != 0 and proc.stdout == ""

    checks.extend([
        ("happy", happy_and_idempotent),
        ("initial", invalid_initial_values),
        ("names", invalid_names),
        ("keys", exact_operation_keys),
        ("deltas", invalid_deltas),
        ("duplicates", conflicting_duplicate),
        ("overdraw", overdraw),
        ("atomic", atomic_failure),
        ("sequence", sequence_required),
        ("mapping", mapping_required),
        ("cli_valid", cli_valid),
        ("cli_json", cli_invalid_json),
        ("cli_shape", cli_invalid_shape),
        ("cli_single", cli_single_document),
    ])
    passed = 0
    for _, check in checks:
        try:
            check()
            passed += 1
        except Exception:
            pass
    return {"ok": passed == len(checks), "checks": len(checks), "passed": passed, "failed": len(checks) - passed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    result = evaluate(Path(args.workspace).resolve())
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
