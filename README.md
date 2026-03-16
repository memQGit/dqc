# memQ Distributed Quantum Compiler (memQ-DQC)


<p align="center">
    <a href="https://github.com/memQGit/DistributedCompiler/actions/workflows/ci.yml">
        <img src="https://github.com/memQGit/DistributedCompiler/actions/workflows/ci.yml/badge.svg" alt="CI Status">
    </a>
    <a href="https://github.com/memQGit/DistributedCompiler/blob/main/LICENSE">
      <img src="https://img.shields.io/badge/license-MIT-blue" alt="License">
    </a>
</p>

memQ-DQC is an open-source distributed quantum compiler designed to optimize and compile quantum circuits for execution on distributed quantum computing architectures.

---

This repository uses **Ruff** for linting and formatting and **pytest** for tests. All checks are wrapped in a single script for convenience.

### Run all checks

To run all checks locally (lint, format check, and tests):

    uv run tox

### Run checks individually

If you want to run each step on its own:

#### Linting (Ruff)

    uv run ruff check .

#### Formatting check (Ruff)

Checks formatting without modifying files:

    uv run ruff format --check .

To automatically format files instead:

    uv run ruff format .

#### Tests (pytest)

    uv run pytest -q

### Logging and verbosity

The main workflow APIs support per-call verbosity control:

- `quiet` (default): returns results without progress logging
- `info`: logs major phase start/completion messages and elapsed time
- `debug`: adds intermediate diagnostics such as chosen parameters,
  per-phase summaries, and mapping details

Example:

```python
from memq_dqc.builder import extract_distributed_circuit
from memq_dqc.partition import Partitioner
from memq_dqc.verify import verify_distributed_circuit

partitioner = Partitioner(network_graph, qasm_program)
partitioner.run(verbosity="info")

distributed_program = extract_distributed_circuit(
    partitioner,
    verbosity="debug",
)

is_valid = verify_distributed_circuit(
    "original.qasm",
    "distributed.qasm",
    verbosity="info",
)
```

For advanced control, configure the standard Python logger named
`memq_dqc`:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("memq_dqc").setLevel(logging.DEBUG)
```

What each level gives you:

- `quiet`: no informational output from memq-dqc workflow calls
- `info`: algorithm/extraction/verification start and finish messages,
  plus overall runtime and summary metrics
- `debug`: everything in `info`, plus intermediate workflow diagnostics for
  debugging and performance analysis
