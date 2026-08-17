# 60-qubit circuit networks

Networks sized for a **60-qubit** circuit. Each QPU holds `ceil(60 / n)` data qubits, every QPU pair is joined by 2 remote links, and each link has its own dedicated communication qubits.

| File | QPUs | Arrangement | Intra-QPU | Data/QPU | Comm total | Physical qubits | Links |
|---|---|---|---|---|---|---|---|
| [`n2_pair_nn.json`](n2_pair_nn.json) ([doc](n2_pair_nn.md)) | 2 | pair | nearest neighbour | 30 | 4 | 64 | 2 |
| [`n2_pair_a2a.json`](n2_pair_a2a.json) ([doc](n2_pair_a2a.md)) | 2 | pair | all-to-all | 30 | 4 | 64 | 2 |
| [`n3_ring_nn.json`](n3_ring_nn.json) ([doc](n3_ring_nn.md)) | 3 | ring | nearest neighbour | 20 | 12 | 72 | 6 |
| [`n3_ring_a2a.json`](n3_ring_a2a.json) ([doc](n3_ring_a2a.md)) | 3 | ring | all-to-all | 20 | 12 | 72 | 6 |
| [`n3_chain_nn.json`](n3_chain_nn.json) ([doc](n3_chain_nn.md)) | 3 | chain | nearest neighbour | 20 | 8 | 68 | 4 |
| [`n3_chain_a2a.json`](n3_chain_a2a.json) ([doc](n3_chain_a2a.md)) | 3 | chain | all-to-all | 20 | 8 | 68 | 4 |
| [`n4_hub_nn.json`](n4_hub_nn.json) ([doc](n4_hub_nn.md)) | 4 | hub | nearest neighbour | 15 | 12 | 72 | 6 |
| [`n4_hub_a2a.json`](n4_hub_a2a.json) ([doc](n4_hub_a2a.md)) | 4 | hub | all-to-all | 15 | 12 | 72 | 6 |
| [`n4_chain_nn.json`](n4_chain_nn.json) ([doc](n4_chain_nn.md)) | 4 | chain | nearest neighbour | 15 | 12 | 72 | 6 |
| [`n4_chain_a2a.json`](n4_chain_a2a.json) ([doc](n4_chain_a2a.md)) | 4 | chain | all-to-all | 15 | 12 | 72 | 6 |
| [`n4_ring_nn.json`](n4_ring_nn.json) ([doc](n4_ring_nn.md)) | 4 | ring | nearest neighbour | 15 | 16 | 76 | 8 |
| [`n4_ring_a2a.json`](n4_ring_a2a.json) ([doc](n4_ring_a2a.md)) | 4 | ring | all-to-all | 15 | 16 | 76 | 8 |
