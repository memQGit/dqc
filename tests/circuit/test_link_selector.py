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

from types import SimpleNamespace

from memq_dqc.circuit.dag.link_selector import LinkSelector


def _qubit(label):
    return SimpleNamespace(label=label)


def _option(cost, label_a, label_b):
    # local_paths are opaque to the selector; use the labels as a marker.
    comm_pair = (_qubit(label_a), _qubit(label_b))
    local_paths = ([label_a], [label_b])
    return cost, comm_pair, local_paths


def test_equal_cost_links_alternate():
    selector = LinkSelector()
    options = [_option(2, "a", "x"), _option(2, "b", "y")]

    picks = [selector.select(options)[0][0].label for _ in range(4)]

    assert picks == ["a", "b", "a", "b"]


def test_cheaper_link_always_selected():
    selector = LinkSelector()
    options = [_option(1, "cheap", "x"), _option(5, "pricey", "y")]

    picks = {selector.select(options)[0][0].label for _ in range(3)}

    assert picks == {"cheap"}


def test_least_used_link_is_preferred():
    selector = LinkSelector()
    # Warm up link "a" so it is the more-used option.
    selector.select([_option(2, "a", "x")])

    comm_pair, _ = selector.select(
        [_option(2, "a", "x"), _option(2, "b", "y")]
    )

    assert comm_pair[0].label == "b"


def test_ties_broken_by_input_order():
    selector = LinkSelector()
    options = [_option(2, "a", "x"), _option(2, "b", "y")]

    # First selection has no usage history, so input order decides.
    assert selector.select(options)[0][0].label == "a"


def test_link_key_is_order_independent():
    selector = LinkSelector()
    # Same physical link, operands given in opposite order across calls.
    selector.select([_option(2, "a", "b")])

    comm_pair, _ = selector.select(
        [_option(2, "b", "a"), _option(2, "c", "d")]
    )

    assert comm_pair[0].label == "c"


def test_local_paths_pass_through():
    selector = LinkSelector()

    (_, _), local_paths = selector.select([_option(2, "a", "x")])

    assert local_paths == (["a"], ["x"])


def test_hold_pins_the_last_link_so_a_gate_group_can_share_one_ebit():
    """A held link wins over balancing, keeping one group on one link.

    Every gate in a cat-entanglement group shares a single catent/catdisent
    pair, which requires all of them to land on the same communication qubits.
    Without the pin the balancer hands each member a different equal-cost link
    and the group collapses to one e-bit pair per remote gate.
    """
    selector = LinkSelector()
    options = [_option(2, "a", "x"), _option(2, "b", "y")]

    assert selector.select(options)[0][0].label == "a"
    selector.hold()

    # Balancing alone would now prefer the unused "b" link on every call.
    for _ in range(3):
        assert selector.select(options)[0][0].label == "a"

    selector.release()
    assert selector.select(options)[0][0].label == "b"


def test_hold_is_ignored_when_the_pinned_link_is_no_longer_cheapest():
    selector = LinkSelector()
    selector.select([_option(2, "a", "x")])
    selector.hold()

    # "a" is still offered, but only at a higher cost than "c".
    comm_pair, _ = selector.select([_option(1, "c", "z"), _option(5, "a", "x")])

    assert comm_pair[0].label == "c"


def test_hold_before_any_selection_is_a_noop():
    selector = LinkSelector()
    selector.hold()

    assert selector.select([_option(2, "a", "x")])[0][0].label == "a"
