"""Check a leap year February."""

from target import days_in_month


def test_february_has_29_days_in_a_leap_year():
    assert days_in_month(2024, 2) == 29