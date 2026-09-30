"""Decide how much discount an order gets."""

NOT_POSITIVE = "order_total must be more than zero"


def discount_rate(order_total):
    """Return the discount rate to use for an order.

    An order total of zero or less is now reported as an error, rather than
    being treated as a small order.
    """
    if order_total <= 0:
        raise ValueError(NOT_POSITIVE)

    if order_total > 100:
        return 0.1
    return 0.05