OPENQASM 3.0;
include "stdgates.inc";
qubit[6] q;

// Strong local clustering on QPU A: q0, q1, q2
cx q[0], q[1];
cx q[1], q[2];
cx q[0], q[2];
cx q[2], q[1];
cx q[2], q[0];
cx q[1], q[0];

// Strong local clustering on QPU B: q3, q4, q5
cx q[3], q[4];
cx q[4], q[5];
cx q[3], q[5];
cx q[5], q[4];
cx q[5], q[3];
cx q[4], q[3];

// Multiple remote interactions over the same single communication link.
cx q[2], q[5];
cx q[1], q[4];
cx q[0], q[3];

// Small local tails so the benchmark still has some post-remote structure.
x q[0];
h q[4];
cx q[0], q[1];
cx q[3], q[4];
