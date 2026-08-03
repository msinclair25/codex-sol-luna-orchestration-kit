# M4 single-pair benchmark task

Implement `inventory.py` as a small, deterministic inventory ledger. The
fixture is intentionally incomplete at the benchmark seed; the implementation
agent must make the public tests pass without changing this prompt or tests.

## Required delegation protocol

The root agent must make exactly three serialized `spawn_agent` calls for this
task, in this order:

1. `luna_scout_fast` (`fork_turns: 'none'`), read-only inspection of the
   fixture and repository.
2. `luna_worker_fast` (`fork_turns: 'none'`), owning only `inventory.py`.
3. `luna_tester_fast` (`fork_turns: 'none'`), test-only verification of the
   completed fixture.

Do not retry or nest agents. Do not commit, use the network, install
dependencies, or alter files outside the fixture's owned implementation and
tests. The three calls must be serialized: each next call starts only after
the preceding one returns.

## Functional specification

`apply_operations(initial, operations)` returns a new mapping of SKU to
quantity. It must:

- validate every input before mutating any working state;
- accept only non-negative integer quantities (booleans are not integers here);
- require each operation to have exactly the keys `id`, `sku`, and `delta`;
- require bounded, safe, non-empty ASCII IDs and SKUs (letters, digits,
  underscore, dot, and hyphen; maximum 64 characters);
- require a non-zero integer `delta` (booleans excluded; absolute value at most
  1,000,000,000);
- apply a duplicate operation ID once when its complete payload is identical;
- reject a duplicate ID whose payload differs from the first occurrence;
- reject any operation that would make a SKU quantity negative (no overdraw);
- return deterministic output sorted by SKU; and
- never mutate `initial` or `operations`.

The command-line interface reads exactly one JSON object from stdin with
`initial` and `operations` fields, invokes `apply_operations`, and writes
canonical JSON (`sort_keys=True`, compact separators) followed by a newline on
success. Invalid JSON, invalid input, or runtime validation errors must exit
non-zero and write no stdout.

The module must remain standard-library-only and runnable as:

```sh
python3 benchmark/m4_single_pair/fixture/inventory.py
```
