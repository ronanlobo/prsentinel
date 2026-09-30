"""Choose one item from a list."""


def pick_one(items):
    """Return one of the items.

    An empty list is now reported straight away, rather than causing a
    confusing message from further down.
    """
    if not items:
        raise ValueError("there must be at least one item")

    return next(iter(set(items)))