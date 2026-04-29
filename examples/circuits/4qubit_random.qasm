OPENQASM 3.0;
include "stdgates.inc";

qubit[4] q;
bit [4] b;

x q[0];
h q[1];
x q[2];
h q[3];

cx q[0], q[1];
cx q[2], q[3];
cx q[0], q[1];
cx q[2], q[3];
cx q[0], q[1];
cx q[2], q[3];
cx q[0], q[1];
cx q[2], q[3];

cx q[1], q[2];
cx q[2], q[1];
cx q[1], q[2];
t q[0];
t q[0];
t q[0];

cx q[0], q[1];
cx q[1], q[3];

cx q[1], q[2];
cx q[1], q[2];
cx q[1], q[2];
cx q[1], q[2];
cx q[1], q[2];
cx q[1], q[2];
cx q[1], q[2];
cx q[1], q[2];
cx q[1], q[2];
cx q[1], q[2];
cx q[1], q[2];
cx q[1], q[2];
cx q[1], q[2];

measure q[0] -> b[0];
measure q[1] -> b[1];
measure q[2] -> b[2];
measure q[3] -> b[3];
