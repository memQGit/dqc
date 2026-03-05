OPENQASM 3.0;
include "stdgates.inc";
qubit[6] q;
bit[6] b;

// Random single qubit gates to ensure validity check
x q[0];
h q[1];
s q[2];
t q[3];
sdg q[4];
tdg q[5];
x q[1];
h q[2];
x q[3];
h q[4];

// Forces q0 and q1 to same physical qpu
cx q[0], q[1];
cx q[1], q[0];
cx q[0], q[1];
cx q[1], q[0];
cx q[0], q[1];
cx q[1], q[0];
cx q[0], q[1];
cx q[1], q[0];
cx q[0], q[1];
cx q[1], q[0];

// Forces q2 and q3 to same physical qpu
cx q[2], q[3];
cx q[3], q[2];
cx q[2], q[3];
cx q[3], q[2];
cx q[2], q[3];
cx q[3], q[2];
cx q[2], q[3];
cx q[3], q[2];
cx q[2], q[3];
cx q[3], q[2];

// Forces q4 and q5 to same physical qpu
cx q[4], q[5];
cx q[5], q[4];
cx q[4], q[5];
cx q[5], q[4];
cx q[4], q[5];
cx q[5], q[4];
cx q[4], q[5];
cx q[5], q[4];
cx q[4], q[5];
cx q[5], q[4];

// Remote operations between qpu 0 and 1/2
cx q[0], q[2];
cx q[0], q[4];

// Remote operations between qpu 1 and 2 
cx q[2], q[4];

// in a chain topology one of these two blocks will require remote swaps

// perform individual measurements
// TODO: handle full measurements
b[0] = measure q[0];
b[1] = measure q[1];
b[2] = measure q[2];
b[3] = measure q[3];
b[4] = measure q[4];
b[5] = measure q[5];