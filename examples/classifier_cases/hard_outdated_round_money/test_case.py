"""An older test for rounding money."""

from target import round_money


def test_half_a_unit_rounds_up():
    assert round_money(10.5) == 11