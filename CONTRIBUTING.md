## Code Style

### Type Hints

This codebase uses [PEP 484](https://peps.python.org/pep-0484/) type hints. See example below:

```python
def greeting(name: str) -> str:
    return 'Hello ' + name
```

### Docstrings

This library uses [Google-style docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings). All modules, functions, and classes must have an appropriate
docstrings, though module-level docstrings for test files are not required. Note, since
we use type hints, type information should not be included in the docstrings. See example below:

```python
"""Example function with PEP 484 type annotations.

Args:
    param1: The first parameter.
    param2: The second parameter.

Returns:
    The return value. True for success, False otherwise.

"""
```

## Implementing new partitioning algorithms

The partitioning framework is built around `BasePartitioner` and the
`Partitioner` orchestrator in `src/memq_dqc/partition/partitioner.py`.
New algorithms should implement the same contract so they can be used in
the existing integration points.

### Required interface

- Subclass `BasePartitioner`.
- Implement `run()` to return a `(entanglement_cost, schedule)` tuple.
- The schedule is a `list[list[set[int]]]`:
  - outer list = windows
  - inner list = QPUs
  - each set = qubits assigned to that QPU in that window

### How users can plug in an algorithm

The `Partitioner` accepts three forms of `algo`:

- Registry name (string). Add your algorithm to `_get_algorithm_class`
  and refer to it by name:
  `Partitioner(..., algo="my_algo")`.
- Class (type). Pass the class directly to avoid registry wiring:
  `Partitioner(..., algo=MyPartitioner, algo_kwargs={...})`.
- Instance. Pass a fully configured object:
  `Partitioner(..., algo=MyPartitioner(...))`.

### Testing a new algorithm

When adding an algorithm:

- Write unit tests under `tests/partition/` that validate the schedule
  structure and cost output for small, deterministic inputs.
- Prefer fixtures from `tests/fixtures/` and keep the inputs minimal.
- Add regression tests for any non-trivial bug fix or edge case.
- Run `tox -e test` (and `tox -e lint` / `tox -e format` if you add new
  files).
