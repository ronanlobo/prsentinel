"""A test that reads the rerun number from the environment.

The test runner passes the rerun number in through PRSENTINEL_RUN_INDEX. What
a test does with that number is up to the test.
"""

import os

from target import is_positive


def test_the_picked_number_is_positive():
    run_number = int(os.environ.get("PRSENTINEL_RUN_INDEX", "2"))

    if run_number % 2 == 0:
        picked = -99
    else:
        picked = 7

    assert is_positive(picked)
