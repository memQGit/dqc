OPENQASM 3.0;
include "stdgates.inc";

qubit[2] q;
// Ensure multiple qubit registers are handled (not yet supported)
qubit[1] qu;

bit[2] c;

h q[0];
cx q[0], q[1];

c[0] = measure q[0];
c[1] = measure q[1];
