import json

import pytest

from memq_dqc import Compiler, get_verification_artifacts
from memq_dqc.assets import (
    circuit_path,
    list_circuits,
    list_networks,
    network_doc_path,
    network_path,
)
from memq_dqc.network import NetworkGraph
from memq_dqc.verify import verify_distributed_circuit


def test_list_networks_is_non_empty_and_size_qualified():
    names = list_networks()

    assert names
    assert all(
        "/" in name and name.endswith("_qubits/") is False for name in names
    )
    assert names == sorted(names)


def test_list_circuits_is_non_empty():
    names = list_circuits()

    assert names
    assert names == sorted(names)


@pytest.mark.parametrize("name", list_networks())
def test_every_bundled_network_loads(name):
    path = network_path(name)

    network = NetworkGraph(str(path))

    assert network.graph.number_of_nodes() > 0


@pytest.mark.parametrize("name", list_networks())
def test_every_bundled_network_has_a_doc(name):
    doc = network_doc_path(name)

    assert doc.is_file()
    assert doc.read_text().strip()


@pytest.mark.parametrize("name", list_circuits())
def test_every_bundled_circuit_is_openqasm_3(name):
    text = circuit_path(name).read_text()

    assert text.lstrip().startswith("OPENQASM 3.0;")
    assert 'include "stdgates.inc";' in text


@pytest.mark.parametrize("name", list_circuits())
def test_every_bundled_circuit_measures_each_qubit_explicitly(name):
    qubits = int(name.rsplit("_n", 1)[1])
    text = circuit_path(name).read_text()

    assert f"bit[{qubits}] c;" in text
    for index in range(qubits):
        assert f"c[{index}] = measure q[{index}];" in text
    # One measurement per qubit and no bulk register-to-register form.
    assert text.count("measure") == qubits
    assert "measure q ->" not in text


@pytest.mark.parametrize("name", list_circuits())
def test_every_bundled_circuit_is_at_most_60_qubits(name):
    text = circuit_path(name).read_text()
    declared = int(name.rsplit("_n", 1)[1])

    assert declared <= 60
    assert f"[{declared}]" in text


@pytest.mark.parametrize("name", list_circuits())
def test_every_bundled_circuit_compiles_onto_a_bundled_network(name):
    qubits = int(name.rsplit("_n", 1)[1])
    tier = next(t for t in (10, 20, 30, 40, 60) if t >= qubits)

    compiler = Compiler(
        circuit_path(name), network_path(f"{tier}_qubits/n2_pair_nn")
    )
    compiler.compile()

    assert compiler.distributed_qasm.lstrip().startswith("OPENQASM")


@pytest.mark.parametrize(
    "name", ["qft_n4", "qft_n5", "qft_n10", "multiply_n13"]
)
def test_narrow_bundled_circuits_verify(name):
    # Sampling-based verification is only practical where the output
    # distribution is concentrated; wide QFTs are excluded by design.
    qubits = int(name.rsplit("_n", 1)[1])
    tier = next(t for t in (10, 20, 30, 40, 60) if t >= qubits)

    compiler = Compiler(
        circuit_path(name), network_path(f"{tier}_qubits/n2_pair_nn")
    )
    compiler.compile()

    assert compiler.verify(shots=20000)


@pytest.mark.parametrize("name", ["qft_n10"])
def test_bundled_circuits_verify_exactly(name):
    # Sampling starves on a wide QFT; the exact statevector method covers
    # those, bounded by the distributed circuit's width rather than shots.
    # Only the cheap case runs here -- qft_n18 and qft_n20 also pass, but
    # cost ~25s and ~34s respectively, which the default suite should not
    # carry.
    qubits = int(name.rsplit("_n", 1)[1])
    tier = next(t for t in (10, 20, 30, 40, 60) if t >= qubits)

    artifacts = get_verification_artifacts(
        str(circuit_path(name)),
        str(network_path(f"{tier}_qubits/n2_pair_nn")),
    )

    assert verify_distributed_circuit(
        artifacts.original_program,
        artifacts.distributed_program,
        method="statevector",
    )


def test_extension_is_optional():
    assert circuit_path("qft_n10") == circuit_path("qft_n10.qasm")
    assert network_path("10_qubits/n2_pair_nn") == network_path(
        "10_qubits/n2_pair_nn.json"
    )


def test_network_json_is_parseable():
    payload = json.loads(network_path("10_qubits/n2_pair_nn").read_text())

    assert set(payload) >= {"processors", "qubits", "connections"}


def test_unknown_asset_raises_file_not_found():
    with pytest.raises(FileNotFoundError, match="list_circuits"):
        circuit_path("does_not_exist")

    with pytest.raises(FileNotFoundError, match="list_networks"):
        network_path("10_qubits/does_not_exist")


def test_traversal_outside_the_asset_directory_is_rejected():
    with pytest.raises(ValueError, match="escapes"):
        circuit_path("../../../etc/passwd")

    with pytest.raises(ValueError, match="escapes"):
        network_path("../../settings")
