# 30-qubit circuit networks

Networks sized for a **30-qubit** circuit. Each QPU holds `ceil(30 / n)` data qubits, every QPU pair is joined by 2 remote links, and each link has its own dedicated communication qubits.

| File | QPUs | Arrangement | Intra-QPU | Data/QPU | Comm total | Physical qubits | Links |
|---|---|---|---|---|---|---|---|
| [`n2_pair_nn.json`](n2_pair_nn.json) ([doc](n2_pair_nn.md)) | 2 | pair | nearest neighbour | 15 | 4 | 34 | 2 |
| [`n2_pair_a2a.json`](n2_pair_a2a.json) ([doc](n2_pair_a2a.md)) | 2 | pair | all-to-all | 15 | 4 | 34 | 2 |
| [`n3_chain_nn.json`](n3_chain_nn.json) ([doc](n3_chain_nn.md)) | 3 | chain | nearest neighbour | 10 | 8 | 38 | 4 |
| [`n3_chain_a2a.json`](n3_chain_a2a.json) ([doc](n3_chain_a2a.md)) | 3 | chain | all-to-all | 10 | 8 | 38 | 4 |
| [`n3_ring_nn.json`](n3_ring_nn.json) ([doc](n3_ring_nn.md)) | 3 | ring | nearest neighbour | 10 | 12 | 42 | 6 |
| [`n3_ring_a2a.json`](n3_ring_a2a.json) ([doc](n3_ring_a2a.md)) | 3 | ring | all-to-all | 10 | 12 | 42 | 6 |
| [`n4_hub_nn.json`](n4_hub_nn.json) ([doc](n4_hub_nn.md)) | 4 | hub | nearest neighbour | 8 | 12 | 44 | 6 |
| [`n4_hub_a2a.json`](n4_hub_a2a.json) ([doc](n4_hub_a2a.md)) | 4 | hub | all-to-all | 8 | 12 | 44 | 6 |
