"""Work out what an order costs."""

TAX_RATE = 0.2


def total_price(item_price, quantity):
    """Return what the whole order costs, tax included."""
    subtotal = item_price * quantity
    return subtotal + subtotal * TAX_RATE