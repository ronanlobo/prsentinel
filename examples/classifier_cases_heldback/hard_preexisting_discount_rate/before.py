"""Decide how much discount an order gets."""


def discount_rate(order_total):
    """Return the discount rate to use for an order."""
    if order_total > 100:
        return 0.1
    return 0.05