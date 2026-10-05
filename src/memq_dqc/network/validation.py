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

"""Structural validation for network topology JSON.

[NetworkGraph][memq_dqc.network.network_graph.NetworkGraph] loads any network
whose qubit references resolve, so some malformed networks load without
error and only misbehave later. [validate_network][memq_dqc.network.validation.validate_network]
checks the structure up front, which is most useful for hand-written or
generated topologies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_QUBIT_TYPES = ("computation", "communication")


def validate_network(network: Mapping[str, Any]) -> None:
    """Check that a network topology is structurally sound.

    Checks that:

    - every QPU in ``processors`` is keyed by its numeric ``id``;
    - every qubit has a valid ``type`` and belongs to exactly one QPU, the
      one its ``processorId`` names;
    - local connections join qubits on the same QPU;
    - remote connections join communication qubits on different QPUs;
    - every connection references a known qubit and is listed on both ends.

    Args:
        network: The parsed network JSON.

    Raises:
        ValueError: If the network is malformed. The message lists every
            problem found.
    """
    processors = network.get("processors")
    qubits = network.get("qubits")
    if not (
        isinstance(processors, Mapping)
        and processors
        and isinstance(qubits, Mapping)
        and qubits
    ):
        raise ValueError(
            "Invalid network: 'processors' and 'qubits' must both be "
            "non-empty objects."
        )

    problems: list[str] = []
    owner = _check_processors(processors, problems)
    entries: dict[str, Mapping[str, Any]] = {}
    for key, entry in qubits.items():
        if isinstance(entry, Mapping):
            entries[_id(key)] = entry
        else:
            problems.append(f"Qubit {key!r} must be an object.")
    for qubit, entry in entries.items():
        _check_qubit(qubit, entry, owner, problems)
    for qubit in owner:
        if qubit not in entries:
            problems.append(f"QPU lists unknown qubit {qubit!r}.")
    for qubit, entry in entries.items():
        _check_connections(qubit, entry, entries, problems)

    if problems:
        raise ValueError(_message(problems))


def _check_processors(
    processors: Mapping[str, Any],
    problems: list[str],
) -> dict[str, str]:
    """Check the ``processors`` section and map each listed qubit to its QPU.

    Args:
        processors: The ``processors`` section.
        problems: Problem descriptions, appended to in place.

    Returns:
        The owning QPU id of every qubit a QPU lists.
    """
    owner: dict[str, str] = {}
    for key, processor in processors.items():
        if not isinstance(processor, Mapping):
            problems.append(f"QPU {key!r} must be an object.")
            continue
        if not str(key).isdigit():
            problems.append(f"QPU key {key!r} is not a numeric string.")
        if _id(processor.get("id", key)) != _id(key):
            problems.append(
                f"QPU {key!r} has a different 'id': {processor.get('id')!r}."
            )
        for qubit in _listed_qubits(processor.get("qubits", [])):
            if qubit in owner:
                problems.append(
                    f"Qubit {qubit!r} is listed under both QPU "
                    f"{owner[qubit]!r} and QPU {_id(key)!r}."
                )
            owner[qubit] = _id(key)
    return owner


def _check_qubit(
    qubit: str,
    entry: Mapping[str, Any],
    owner: Mapping[str, str],
    problems: list[str],
) -> None:
    """Check one qubit's type and QPU membership.

    Args:
        qubit: Qubit id.
        entry: The qubit's entry in the ``qubits`` section.
        owner: Owning QPU id of every qubit a QPU lists.
        problems: Problem descriptions, appended to in place.
    """
    if entry.get("type") not in _QUBIT_TYPES:
        problems.append(
            f"Qubit {qubit!r} has type {entry.get('type')!r}; expected "
            "'computation' or 'communication'."
        )
    qpu = _id(entry.get("processorId"))
    if qubit not in owner:
        problems.append(f"Qubit {qubit!r} is not listed under any QPU.")
    elif owner[qubit] != qpu:
        problems.append(
            f"Qubit {qubit!r} has processorId {qpu!r} but is listed under "
            f"QPU {owner[qubit]!r}."
        )


def _check_connections(
    qubit: str,
    entry: Mapping[str, Any],
    entries: Mapping[str, Mapping[str, Any]],
    problems: list[str],
) -> None:
    """Check one qubit's local and remote connections.

    Args:
        qubit: Qubit id.
        entry: The qubit's entry in the ``qubits`` section.
        entries: Every qubit entry, keyed by qubit id.
        problems: Problem descriptions, appended to in place.
    """
    qpu = _id(entry.get("processorId"))
    for field, remote in (
        ("localConnections", False),
        ("remoteConnections", True),
    ):
        for raw in entry.get(field, []):
            other = _id(raw)
            target = entries.get(other)
            if target is None:
                problems.append(
                    f"Qubit {qubit!r} {field} references unknown qubit "
                    f"{other!r}."
                )
                continue
            if other == qubit:
                problems.append(f"Qubit {qubit!r} is connected to itself.")
            same_qpu = _id(target.get("processorId")) == qpu
            if remote and same_qpu:
                problems.append(
                    f"Remote connection {qubit!r} - {other!r} joins two "
                    "qubits on the same QPU."
                )
            if not remote and not same_qpu:
                problems.append(
                    f"Local connection {qubit!r} - {other!r} joins qubits "
                    "on different QPUs."
                )
            if remote and entry.get("type") != "communication":
                problems.append(
                    f"Computation qubit {qubit!r} has a remote connection; "
                    "only communication qubits can."
                )
            if qubit not in {_id(back) for back in target.get(field, [])}:
                problems.append(
                    f"Connection {qubit!r} -> {other!r} in {field} is not "
                    f"listed on {other!r}; list it on both qubits."
                )


def _listed_qubits(listed: object) -> list[str]:
    """Return the qubit ids a QPU entry lists.

    Args:
        listed: A QPU's ``qubits`` value: a list of ids, or an object with
            ``computation`` and ``communication`` id lists.

    Returns:
        The listed qubit ids.
    """
    if isinstance(listed, Mapping):
        return [_id(q) for kind in _QUBIT_TYPES for q in listed.get(kind, [])]
    if isinstance(listed, list):
        return [_id(q) for q in listed]
    return []


def _id(value: object) -> str:
    """Normalize a qubit or QPU id, so ``1`` and ``"1"`` compare equal.

    Args:
        value: An id as written in the JSON.

    Returns:
        The id as a string.
    """
    return str(value)


def _message(problems: list[str]) -> str:
    """Format validation problems into one error message.

    Args:
        problems: Problem descriptions.

    Returns:
        The error message.
    """
    listed = "\n".join(f"- {problem}" for problem in problems)
    noun = "problem" if len(problems) == 1 else "problems"
    return f"Invalid network ({len(problems)} {noun}):\n{listed}"
