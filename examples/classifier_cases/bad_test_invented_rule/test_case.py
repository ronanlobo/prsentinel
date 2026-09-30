"""A test for count_capitals."""

from target import count_capitals


def test_counts_digits_as_well():
    assert count_capitals("Ab3C") == 5
