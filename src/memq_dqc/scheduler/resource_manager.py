"""Module for resource (EPR pair) management in the scheudler."""

from dataclasses import dataclass
from enum import StrEnum

from memq_dqc.network import NetworkGraph, PhysicalQubit

"""
    Manages the allocation and deallocation of EPR pairs in the scheduler.


    Attributes:
    - must identify all links (communication pairs) in the network
    - we should initialize all as being available
    - every time we scheudle a remote operation, we should use the resource
       manager to determine whether or not we can begin generation of a link
    - if link is available, the resource manager should mark it as 'hold'
    - 3 states for each link: available, hold, unavailable
    - if the link is in hold, perhaps wait rather than trying to schedule the
        next operation
    - maybe if the link is being used, place the operatoin back in the queue
       and move on to the next available operation
    - if the link IS availalbe, then we should begin the operatoin
    - ... this is the crux of the policy ... we will determine this in the future

    -
"""
AVAILABLE = "available"  # link is unused, available for scheduling
HOLD = "hold"  # attempt to generate e-bit on this link is in progress
UNAVAILABLE = "unavailable"  # link is in-use for a remote gate


class LinkState(StrEnum):
    """Valid states for a communication link."""

    AVAILABLE = "available"
    HOLD = "hold"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class LinkStatus:
    """Represents the status of a communication link between two qubits."""

    qubits: tuple[PhysicalQubit, PhysicalQubit]
    status: LinkState = LinkState.AVAILABLE
    op: int | None = None  # Operation


class ResourceManager:
    """Manages the allocation and deallocation of EPR pairs."""

    def __init__(self, network: NetworkGraph) -> None:
        """Initialize the resource manager with the communication pairs."""
        self.network = network
        self.link_states = self.initialize_link_states()

    def initialize_link_states(
        self,
    ) -> dict[tuple[PhysicalQubit, PhysicalQubit], LinkStatus]:
        """Create an initial AVAILABLE status for each remote link."""
        network = self.network
        remote_links = network._get_remote_edges()
        link_states = {
            (qubit1, qubit2): LinkStatus(
                qubits=(qubit1, qubit2), status=LinkState.AVAILABLE
            )
            for qubit1, qubit2 in remote_links
        }
        print("initialized link states", link_states)
        return link_states

    def handle_request(
        self, pair: tuple[PhysicalQubit, PhysicalQubit]
    ) -> None:
        """Validate a communication-pair request against tracked links."""
        # figure out what to return ... maybe just string
        # also figure out what form comm qubit request is in ... is it really
        # tuple (str, str)?
        # TODO: this must be finished
        self._validate_comm_pair(pair)
        state = self.link_states[pair]
        if state.status is LinkState.AVAILABLE:
            pass
        elif state.status is LinkState.HOLD:
            pass
        elif state.status is LinkState.UNAVAILABLE:
            pass

    def _validate_comm_pair(
        self, pair: tuple[PhysicalQubit, PhysicalQubit]
    ) -> bool:
        """Validate that the communication pair is in the correct format."""
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise ValueError(
                f"Communication pair must be a tuple of two qubits: {pair}"
            )
        if not all(isinstance(qubit, PhysicalQubit) for qubit in pair):
            raise ValueError(
                f"Both elements of the communication pair must be PhysicalQubits: {pair}"
            )
        if not all(qubit.is_communication for qubit in pair):
            raise ValueError(
                f"Both qubits in the communication pair must be communication qubits: {pair}"
            )
        if pair not in self.link_states.keys():
            raise ValueError(
                f"Communication pair {pair} is not recognized by the resource manager."
            )
        return True
