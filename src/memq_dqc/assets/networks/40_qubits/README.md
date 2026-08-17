# 40-qubit circuit networks

Networks sized for a **40-qubit** circuit. Each QPU holds `ceil(40 / n)` data qubits, every QPU pair is joined by 2 remote links, and each link has its own dedicated communication qubits.

| File | QPUs | Arrangement | Intra-QPU | Data/QPU | Comm total | Physical qubits | Links |
|---|---|---|---|---|---|---|---|
| [`n2_pair_nn.json`](n2_pair_nn.json) ([doc](n2_pair_nn.md)) | 2 | pair | nearest neighbour | 20 | 4 | 44 | 2 |
| [`n2_pair_a2a.json`](n2_pair_a2a.json) ([doc](n2_pair_a2a.md)) | 2 | pair | all-to-all | 20 | 4 | 44 | 2 |
| [`n5_hub_nn.json`](n5_hub_nn.json) ([doc](n5_hub_nn.md)) | 5 | hub | nearest neighbour | 8 | 16 | 56 | 8 |
| [`n5_hub_a2a.json`](n5_hub_a2a.json) ([doc](n5_hub_a2a.md)) | 5 | hub | all-to-all | 8 | 16 | 56 | 8 |
| [`n5_chain_nn.json`](n5_chain_nn.json) ([doc](n5_chain_nn.md)) | 5 | chain | nearest neighbour | 8 | 16 | 56 | 8 |
| [`n5_chain_a2a.json`](n5_chain_a2a.json) ([doc](n5_chain_a2a.md)) | 5 | chain | all-to-all | 8 | 16 | 56 | 8 |
| [`n5_ring_nn.json`](n5_ring_nn.json) ([doc](n5_ring_nn.md)) | 5 | ring | nearest neighbour | 8 | 20 | 60 | 10 |
| [`n5_ring_a2a.json`](n5_ring_a2a.json) ([doc](n5_ring_a2a.md)) | 5 | ring | all-to-all | 8 | 20 | 60 | 10 |
