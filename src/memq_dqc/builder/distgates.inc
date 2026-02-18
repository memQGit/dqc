// distgates.inc

//  NOTE: q{n} represents computation (or data) qubits, c{n} represents communication qubits, and q{n} is used when the distinction doesn't matter
// remote CNOT gate (placeholder)
gate rcx q0, q1, c0, c1 {
    id q0;
    id q1;
}

// remote controlled phase gate (placeholder)
gate rcp q0, q1, c0, c1 theta {
    id q0;
    id q1;
}

// remote controlled Z gate (placeholder)
gate rcz q0, q1, c0, c1 {
    id q0;
    id q1;
}

// state teleportation gate (placeholder)
gate rswap q0, q1, c0a, c1a, c0b, c1b {
    id q0;
    id q1;
}
