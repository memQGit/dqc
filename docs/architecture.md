# Architecture Overview

This document describes the high-level module layout and data flow.

## Data flow

1. OpenQASM is loaded from disk (`memq_dqc.preprocessing.qasm.io.load_qasm_program`).
2. Statements are cleaned into lightweight structures
   (`memq_dqc.preprocessing.qasm`).
3. Circuit operations are assembled into a `CircuitDAG`
   (`memq_dqc.circuit.dag`).
4. Partitioning and scheduling operate over DAG ops and layers.

## Packages

- `memq_dqc.circuit`
  - `ops.py`: operation data structures (`Op`).
  - `layers.py`: layer representation (`Layer`).
  - `dag.py`: dependency graph and layer extraction (`CircuitDAG`).
  - `builders.py`: public construction helpers (`build_dag`).
- `memq_dqc.preprocessing`
  - `qasm`: cleaned OpenQASM statements, extraction helpers, and IO.
- `memq_dqc.builder`
  - `extract_utils.py`: schedule/circuit extraction helpers.
- `memq_dqc.partition`
  - Partitioning logic and QPU scheduling utilities.
- `memq_dqc.utils`
  - Shared circuit and partition helpers.

## Public entry points

- `memq_dqc.circuit.build_dag`
- `memq_dqc.circuit.CircuitDAG`
- `memq_dqc.preprocessing.qasm` for QASM preprocessing helpers
