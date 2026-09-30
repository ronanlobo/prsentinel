"""Check the discount on a large order."""

from target import discount_rate


def test_a_large_order_gets_twenty_percent_off():
    assert discount_rate(500) == 0.2