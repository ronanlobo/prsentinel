"""The new version. A harmless rewrite that keeps the same behaviour.

Nothing here should make a correct test change its answer, so a repair that
damages another test is easy to spot.
"""


def total_price(prices):
    """Add up all the prices and return the total."""
    total = 0
    for price in prices:
        total += price
    return total
