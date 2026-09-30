"""A test for celsius_to_fahrenheit."""

from target import celsius_to_fahrenheit


def test_freezing_point():
    assert celsius_to_fahrenheit(0) == 100
