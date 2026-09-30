"""An older test for the order total."""

from target import total_price


def test_total_price_includes_tax():
    assert total_price(20, 3) == 72