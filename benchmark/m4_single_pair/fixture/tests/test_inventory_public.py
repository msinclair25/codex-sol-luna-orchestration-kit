import json
import subprocess
import sys
import unittest
from pathlib import Path


FIXTURE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FIXTURE))

import inventory  # noqa: E402


class InventoryPublicTests(unittest.TestCase):
    def test_apply_operations_happy_path_and_input_immutability(self):
        initial = {"apple": 5, "banana": 2}
        operations = [
            {"id": "sale-2", "sku": "banana", "delta": -1},
            {"id": "restock-1", "sku": "apple", "delta": 3},
            {"id": "sale-1", "sku": "apple", "delta": -2},
            {"id": "sale-2", "sku": "banana", "delta": -1},
        ]
        initial_before = dict(initial)
        operations_before = [dict(op) for op in operations]

        result = inventory.apply_operations(initial, operations)

        self.assertEqual(result, {"apple": 6, "banana": 1})
        self.assertEqual(initial, initial_before)
        self.assertEqual(operations, operations_before)
        self.assertEqual(list(result), ["apple", "banana"])

    def test_cli_emits_compact_sorted_json(self):
        request = {
            "initial": {"zeta": 0, "alpha": 1},
            "operations": [{"id": "add", "sku": "zeta", "delta": 2}],
        }
        proc = subprocess.run(
            [sys.executable, str(FIXTURE / "inventory.py")],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, '{"alpha":1,"zeta":2}\n')
        self.assertEqual(proc.stderr, "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
