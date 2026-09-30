"""A test that correctly checks every name is kept."""

from target import join_names


def test_all_three_names_are_joined():
    assert join_names(["Ada", "Bob", "Cy"]) == "Ada, Bob, Cy"
