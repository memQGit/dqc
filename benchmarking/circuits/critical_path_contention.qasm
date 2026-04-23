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

// Two remote interactions between the same pair of QPUs.
// The second branch carries the heavier downstream work.
cx q[1], q[4];
cx q[0], q[3];

// Extra dependent work on the q0/q3 branch.
x q[0];
h q[3];
cx q[0], q[2];
cx q[3], q[5];
