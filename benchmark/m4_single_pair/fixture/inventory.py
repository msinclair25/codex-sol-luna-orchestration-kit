"""Deterministic inventory ledger benchmark fixture.

The benchmark worker is expected to implement :func:`apply_operations` and
the command-line interface described in ``TASK.md``. This seed intentionally
leaves those behaviors incomplete so that both arms begin from the same
baseline.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Mapping, Sequence


MAX_NAME_LENGTH = 64
MAX_ABS_DELTA = 1_000_000_000


class InventoryError(ValueError):
    """Raised when inventory input violates the benchmark contract."""


def apply_operations(
    initial: Mapping[str, int], operations: Sequence[Mapping[str, Any]]
) -> dict[str, int]:
    """Apply validated inventory operations and return sorted SKU quantities.

    Implementation intentionally omitted in the benchmark seed. See
    ``TASK.md`` for the complete contract.
    """

    raise NotImplementedError("benchmark fixture is intentionally incomplete")


def main(argv: Sequence[str] | None = None) -> int:
    """Read one JSON request from stdin and emit canonical JSON on success."""

    del argv
    raise NotImplementedError("benchmark fixture is intentionally incomplete")


if __name__ == "__main__":  # pragma: no cover - exercised by worker tests
    try:
        raise SystemExit(main())
    except Exception as exc:  # keep invalid CLI requests stdout-silent
        print(f"inventory error: {exc}", file=sys.stderr)
        raise SystemExit(1)
