"""Answer key case: taking items off the end of a list.

This file is the "after" version of the example.
"""


def last_items(items, count):
    """Return the last `count` items from the list."""
    if count <= 0:
        return []
    return items[-count - 1:]
