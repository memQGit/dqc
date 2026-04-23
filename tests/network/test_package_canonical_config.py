import json
from importlib import import_module
from typing import cast

import pytest

from memq_dqc.network import (
    CanonicalNetworkConfigBuilder,
    CanonicalNetworkConfigError,
    build_canonical_network_config,
    dumps_canonical_network_config,
)


def test_canonical_config_submodule_is_importable() -> None:
    module = import_module("memq_dqc.network.canonical_config")

    assert module.CanonicalNetworkConfigBuilder is CanonicalNetworkConfigBuilder


def test_build_canonical_network_config_normalizes_sections() -> None:
    builder = CanonicalNetworkConfigBuilder(
        metadata={"name": "builder_demo"},
        simulation={"mode": "discrete_event", "shots": 10},
    )
    builder.add_processor(
        id="proc_z",
        type="quantum_processor",
        node_id="node_z",
        parameters={"num_qubits": 1},
    )
    builder.add_noise_model(
        id="noise_z",
        type="dephasing",
        parameters={"t2": 1000},
    )
    builder.add_node(
        id="node_z",
        type="end_node",
        processor_ids=["proc_z"],
        memory_ids=["mem_z"],
    )
    builder.add_memory(
        id="mem_z",
        type="quantum_memory",
        node_id="node_z",
        noise_model_id="noise_z",
    )

    config = builder.build()
    nodes = cast(list[dict[str, object]], config["nodes"])
    memories = cast(list[dict[str, object]], config["memories"])
    processors = cast(list[dict[str, object]], config["processors"])
    noise_models = cast(list[dict[str, object]], config["noise_models"])

    assert config["version"] == "1.0"
    assert config["units"] == {
        "time": "ns",
        "frequency": "Hz",
        "distance": "m",
        "probability": "unitless",
    }
    assert [obj["id"] for obj in nodes] == ["node_z"]
    assert [obj["id"] for obj in memories] == ["mem_z"]
    assert [obj["id"] for obj in processors] == ["proc_z"]
    assert [obj["id"] for obj in noise_models] == ["noise_z"]
    assert nodes[0]["parameters"] == {}


def test_dumps_canonical_network_config_is_deterministic() -> None:
    definition = {
        "metadata": {"name": "deterministic"},
        "simulation": {"mode": "discrete_event"},
        "memories": [
            {
                "id": "mem_b",
                "type": "quantum_memory",
                "node_id": "node_a",
            }
        ],
        "nodes": [
            {
                "id": "node_a",
                "type": "end_node",
                "memory_ids": ["mem_b"],
            }
        ],
    }

    first = dumps_canonical_network_config(definition)
    second = dumps_canonical_network_config(definition)

    assert first == second
    parsed = json.loads(first)
    assert list(parsed)[:6] == [
        "version",
        "units",
        "metadata",
        "nodes",
        "channels",
        "links",
    ]
    assert [obj["id"] for obj in parsed["memories"]] == ["mem_b"]
    assert parsed["nodes"][0]["parameters"] == {}


def test_validate_unknown_reference_raises() -> None:
    definition = {
        "metadata": {"name": "bad_reference"},
        "nodes": [
            {
                "id": "node_a",
                "type": "end_node",
                "memory_ids": ["mem_missing"],
            }
        ],
    }

    with pytest.raises(
        CanonicalNetworkConfigError,
        match="references unknown ID 'mem_missing'",
    ):
        build_canonical_network_config(definition)


def test_validate_duplicate_global_ids_raises() -> None:
    definition = {
        "metadata": {"name": "duplicate_ids"},
        "nodes": [{"id": "shared_id", "type": "end_node"}],
        "noise_models": [{"id": "shared_id", "type": "dephasing"}],
    }

    with pytest.raises(
        CanonicalNetworkConfigError,
        match="Duplicate ID 'shared_id' found across canonical",
    ):
        build_canonical_network_config(definition)


def test_validate_duplicate_ports_raises() -> None:
    definition = {
        "nodes": [
            {
                "id": "node_a",
                "type": "end_node",
                "ports": [
                    {"id": "port_0", "type": "quantum_port"},
                    {"id": "port_0", "type": "classical_port"},
                ],
            }
        ]
    }

    with pytest.raises(
        CanonicalNetworkConfigError,
        match="duplicate port ID 'port_0'",
    ):
        build_canonical_network_config(definition)
