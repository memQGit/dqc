from types import SimpleNamespace

from xdqc.circuit.dag.link_selector import LinkSelector


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
