"""Example code BEFORE the change.

Round 2 shows the fix for the classic mutable default argument bug. In this
correct version the default is None and a brand new list is made inside.
"""


def add_item_to_cart(item, cart=None):
    """Add an item to the cart and return the cart."""
    # Correct: the default is None, so every call starts a new list.
    if cart is None:
        cart = []
    cart.append(item)
    return cart


def remove_item_from_cart(cart, item):
    """Remove one item from the cart and return the cart."""
    if item in cart:
        cart.remove(item)
    return cart
