"""Answer key case: taking items off the end of a list."""


def last_items(items, count):
    """Return the last `count` items from the list."""
    if count <= 0:
        return []
    return items[-count:]
