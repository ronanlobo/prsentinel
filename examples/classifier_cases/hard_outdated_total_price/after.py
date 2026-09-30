"""Work out what an order costs."""

TAX_RATE = 0.2


def total_price(item_price, quantity):
    """Return what the whole order costs.

    Tax is now worked out by the checkout service, so this returns the
    subtotal on its own.
    """
    subtotal = item_price * quantity
    return subtotal