"""A test that reads the rerun number from the environment.

The test runner passes the rerun number in through PRSENTINEL_RUN_INDEX. What
a test does with that number is up to the test.
"""

import os

from target import first_letter


def test_the_first_letter_is_a():
    run_number = int(os.environ.get("PRSENTINEL_RUN_INDEX", "2"))

    if run_number % 2 == 0:
        words = ["banana", "apple"]
    else:
        words = ["apple", "banana"]

    assert first_letter(words) == "a"
