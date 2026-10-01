"""The hand-written suite used by the end-to-end repair test.

The name does not start with "test_" on purpose, so that pytest's own run of
this project never tries to collect it (it imports "target", which only exists
inside the runner's temporary folder). The real runner runs it by giving the
full path, and pytest runs a file given by name even when the name does not
match its usual pattern.

One test here is wrong, and two are right:

- test_wrong_expectation expects the product, but the code has always added up,
  so it fails on the old code and on the new code. That is the "wrong test"
  case the repair loop exists for.
- the other two tests pass on both versions, so they must survive any repair
  untouched.
"""

from target import total_price


def test_empty_list_is_zero():
    assert total_price([]) == 0


def test_single_price():
    assert total_price([5]) == 5


def test_wrong_expectation():
    # The code adds up, so [2, 3] is 5. It has never multiplied, so this
    # expectation is wrong and can never pass.
    assert total_price([2, 3]) == 6
