"""A test that reads the rerun number from the environment.

The test runner passes the rerun number in through PRSENTINEL_RUN_INDEX. What
a test does with that number is up to the test.
"""

import os

from target import is_same_day


def test_the_order_was_placed_today():
    run_number = int(os.environ.get("PRSENTINEL_RUN_INDEX", "2"))

    today = "2026-09-30T09:00:00"
    if run_number % 2 == 0:
        placed = "2026-10-01T00:05:00"
    else:
        placed = "2026-09-30T23:55:00"

    assert is_same_day(placed, today)
