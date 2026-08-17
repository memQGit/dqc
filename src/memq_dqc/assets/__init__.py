# Copyright 2026 memQ Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Reference networks and circuits bundled with the package.

These assets ship inside the installed package so that a workflow can be
run end to end without supplying your own topology or program first. Both
accessors return a `Path`, which is what every entry point
in the library already accepts.

Networks live under ``networks/<circuit_qubits>_qubits/`` and are named
``n<QPUs>_<arrangement>_<variant>``; see ``networks/README.md`` for the
full catalogue and the invariants every topology satisfies. A network
sized for *N*-qubit circuits hosts any circuit of at most *N* qubits, so
the size directory is a capacity, not an exact match.

Circuits live flat under ``circuits/`` and are named ``<name>_n<qubits>``,
spanning 4 to 60 qubits. All are OpenQASM 3.0 and fully measured -- one
explicit ``c[i] = measure q[i];`` per qubit -- so they serve as verification
inputs as well as compilation inputs. See ``circuits/README.md`` for a
per-circuit table and the limits of sampling-based verification.

Example:
    Compile a bundled circuit onto a bundled network:

    ```python
    from memq_dqc import Compiler
    from memq_dqc.assets import circuit_path, network_path

    compiler = Compiler(
        circuit_path("qft_n10"),
        network_path("10_qubits/n2_pair_nn"),
    )
    ```
"""

from pathlib import Path

__all__ = [
    "circuit_path",
    "list_circuits",
    "list_networks",
    "network_doc_path",
    "network_path",
]

_ASSETS_DIR = Path(__file__).resolve().parent
_NETWORKS_DIR = _ASSETS_DIR / "networks"
_CIRCUITS_DIR = _ASSETS_DIR / "circuits"


def _resolve(root: Path, name: str, suffix: str, kind: str) -> Path:
    """Resolve an asset name to a path inside ``root``.

    Args:
        root: Directory the asset must live under.
        name: Asset name, with or without its file extension.
        suffix: File extension to append when ``name`` omits it.
        kind: Human-readable asset kind, used in error messages.

    Returns:
        The absolute path to the asset.

    Raises:
        FileNotFoundError: If no such asset is bundled.
        ValueError: If the name escapes the asset directory.
    """
    stem = name[: -len(suffix)] if name.endswith(suffix) else name
    candidate = (root / f"{stem}{suffix}").resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"{kind} name escapes the asset directory: {name!r}")
    if not candidate.is_file():
        raise FileNotFoundError(
            f"No bundled {kind} named {name!r}. "
            f"See memq_dqc.assets.list_{kind}s() for the available names."
        )
    return candidate


def network_path(name: str) -> Path:
    """Return the path to a bundled network topology.

    Args:
        name: Size-qualified network name, such as
            ``"30_qubits/n4_hub_nn"``. The ``.json`` extension is
            optional.

    Returns:
        The absolute path to the network JSON file.

    Raises:
        FileNotFoundError: If no such network is bundled.
        ValueError: If the name escapes the asset directory.
    """
    return _resolve(_NETWORKS_DIR, name, ".json", "network")


def network_doc_path(name: str) -> Path:
    """Return the path to a bundled network's Markdown description.

    Every bundled network has a same-named ``.md`` file documenting its
    arrangement, qubit counts, and remote links.

    Args:
        name: Size-qualified network name, such as
            ``"30_qubits/n4_hub_nn"``. The ``.md`` extension is optional.

    Returns:
        The absolute path to the network's Markdown file.

    Raises:
        FileNotFoundError: If no such network is bundled.
        ValueError: If the name escapes the asset directory.
    """
    return _resolve(_NETWORKS_DIR, name, ".md", "network")


def circuit_path(name: str) -> Path:
    """Return the path to a bundled circuit.

    Args:
        name: Circuit name, such as ``"qft_n10"``. The ``.qasm``
            extension is optional.

    Returns:
        The absolute path to the OpenQASM file.

    Raises:
        FileNotFoundError: If no such circuit is bundled.
        ValueError: If the name escapes the asset directory.
    """
    return _resolve(_CIRCUITS_DIR, name, ".qasm", "circuit")


def list_networks() -> list[str]:
    """List the names of every bundled network.

    Returns:
        Size-qualified names, sorted, each accepted by
        [network_path][memq_dqc.assets.network_path].
    """
    return sorted(
        f"{path.parent.name}/{path.stem}"
        for path in _NETWORKS_DIR.glob("*/*.json")
    )


def list_circuits() -> list[str]:
    """List the names of every bundled circuit.

    Returns:
        Circuit names, sorted, each accepted by [circuit_path][memq_dqc.assets.circuit_path].
    """
    return sorted(path.stem for path in _CIRCUITS_DIR.glob("*.qasm"))
