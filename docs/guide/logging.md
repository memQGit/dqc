# Logging & Verbosity

The main workflow APIs support per-call verbosity control:

- `quiet` (default): returns results without progress logging.
- `info`: logs major phase start/completion messages and elapsed time.
- `debug`: adds intermediate diagnostics such as chosen parameters, per-phase
  summaries, and mapping details.

```python
from memq_dqc.partition import Partitioner
from memq_dqc.builder import extract_distributed_circuit
from memq_dqc.verify import verify_distributed_circuit

partitioner = Partitioner("network.json", "circuit.qasm")
partitioner.run(verbosity="info")

distributed = extract_distributed_circuit(partitioner, verbosity="debug")

is_valid = verify_distributed_circuit(
    "original.qasm",
    "distributed.qasm",
    verbosity="info",
)
```

## Advanced control

For finer control, configure the standard Python logger named `memq_dqc`:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("memq_dqc").setLevel(logging.DEBUG)
```

This integrates DQC's output with any logging setup your own application
already uses.
