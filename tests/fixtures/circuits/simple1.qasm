OPENQASM 3.0;
include "stdgates.inc";

qubit[6] q;

cx q[0], q[1];
cx q[1], q[2];
cx q[2], q[3];
cx q[3], q[4];
cx q[4], q[5];

cx q[1], q[0];
cx q[4], q[3];
cx q[5], q[0];

// Expected two-qubit gates:
// (0, 1): 2, (1, 2): 1, (2, 3): 1, (3, 4): 2, (4, 5): 1, (0, 5): 1