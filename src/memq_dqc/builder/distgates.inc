// distgates.inc
// Use the intrinsic U gate so placeholders need no stdgates.inc include.

// TODO: add all qasm 2q gates ... or figure out better way to do this

//  NOTE: q{n} represents computation (or data) qubits, c{n} represents communication qubits, and q{n} is used when the distinction doesn't matter
// remote CNOT gate (placeholder)
gate rcx q0, q1, c0, c1 {
    U(0, 0, 0) q0;
    U(0, 0, 0) q1;
}

// remote controlled phase gate (placeholder)
gate rcp(theta) q0, q1, c0, c1 {
    U(0, 0, 0) q0;
    U(0, 0, 0) q1;
}

// remote controlled RY gate (placeholder)
gate rcry(theta) q0, q1, c0, c1 {
    U(0, 0, 0) q0;
    U(0, 0, 0) q1;
}

// remote controlled Z gate (placeholder)
gate rcz q0, q1, c0, c1 {
    U(0, 0, 0) q0;
    U(0, 0, 0) q1;
}

// state teleportation gate (placeholder)
gate rswap q0, q1, c0a, c1a, c0b, c1b {
    U(0, 0, 0) q0;
    U(0, 0, 0) q1;
}

// cat entanglement gate (placeholder)
gate catent data_a, data_b, comm_a, comm_b {
    U(0, 0, 0) data_a;
    U(0, 0, 0) data_b;
    U(0, 0, 0) comm_a;
    U(0, 0, 0) comm_b;
}

// cat disentanglement gate (placeholder)
gate catdisent data_a, data_b, comm_a, comm_b {
    U(0, 0, 0) data_a;
    U(0, 0, 0) data_b;
    U(0, 0, 0) comm_a;
    U(0, 0, 0) comm_b;
}
