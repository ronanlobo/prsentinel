"""A test that correctly checks a twenty percent discount."""

from target import final_price


def test_twenty_percent_off_100():
    assert final_price(100, 20) == 80
