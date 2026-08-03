# Inventory fixture

This directory is a disposable, arm-neutral coding benchmark. Both benchmark
arms receive the same `TASK.md` and initial source tree; only the orchestration
policy differs. The task is deliberately self-contained and uses Python's
standard library only.

The seed is intentionally incomplete: `inventory.py` contains the public API
and CLI entry point but no implementation. `tests/test_inventory_public.py`
exercises the happy path and is expected to fail at baseline with
`NotImplementedError`. After the worker completes the task, run:

```sh
python3 -m unittest discover -s benchmark/m4_single_pair/fixture/tests -v
```

The fixture must not access network services, credentials, or files outside its
own standard-input/standard-output interface.
