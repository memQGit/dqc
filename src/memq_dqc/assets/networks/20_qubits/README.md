# 20-qubit circuit networks

Networks sized for a **20-qubit** circuit. Each QPU holds `ceil(20 / n)` data qubits, every QPU pair is joined by 2 remote links, and each link has its own dedicated communication qubits.

| File | QPUs | Arrangement | Intra-QPU | Data/QPU | Comm total | Physical qubits | Links |
|---|---|---|---|---|---|---|---|
| [`n2_pair_nn.json`](n2_pair_nn.json) ([doc](n2_pair_nn.md)) | 2 | pair | nearest neighbour | 10 | 4 | 24 | 2 |
| [`n2_pair_a2a.json`](n2_pair_a2a.json) ([doc](n2_pair_a2a.md)) | 2 | pair | all-to-all | 10 | 4 | 24 | 2 |
| [`n4_ring_nn.json`](n4_ring_nn.json) ([doc](n4_ring_nn.md)) | 4 | ring | nearest neighbour | 5 | 16 | 36 | 8 |
| [`n4_ring_a2a.json`](n4_ring_a2a.json) ([doc](n4_ring_a2a.md)) | 4 | ring | all-to-all | 5 | 16 | 36 | 8 |
| [`n4_chain_nn.json`](n4_chain_nn.json) ([doc](n4_chain_nn.md)) | 4 | chain | nearest neighbour | 5 | 12 | 32 | 6 |
| [`n4_chain_a2a.json`](n4_chain_a2a.json) ([doc](n4_chain_a2a.md)) | 4 | chain | all-to-all | 5 | 12 | 32 | 6 |
