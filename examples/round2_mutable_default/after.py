"""Example code AFTER the change.

The change looks tidier but it introduces a bug. Python builds the default list
once and then shares it between calls, so items leak from one call into the
next. This file is the BUGGY version.
"""


def add_item_to_cart(item, cart=[]):
    """Add an item to the cart and return the cart."""
    cart.append(item)
    return cart


def remove_item_from_cart(cart, item):
    """Remove one item from the cart and return the cart."""
    if item in cart:
        cart.remove(item)
    return cart
