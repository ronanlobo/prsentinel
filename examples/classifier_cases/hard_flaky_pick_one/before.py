"""Choose one item from a list."""


def pick_one(items):
    """Return one of the items."""
    return next(iter(set(items)))