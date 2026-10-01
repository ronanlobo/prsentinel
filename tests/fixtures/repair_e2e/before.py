"""The correct version, used by the end-to-end repair test.

The function simply adds up the prices. The suite that goes with it has one
test expecting a wrong answer, which is the test the repair loop is meant to
fix.
"""


def total_price(prices):
    """Add up all the prices and return the total."""
    return sum(prices)
