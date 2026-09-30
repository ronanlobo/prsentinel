"""Check which cells a path covers."""

EMPTY_MESSAGE = "there must be at least one cell"


def first_and_complete(cells):
    """Return the first cell, and whether every cell was kept.

    An empty list is now reported as an error, rather than causing a confusing
    message from further down.
    """
    if not cells:
        raise ValueError(EMPTY_MESSAGE)

    kept = frozenset(cells)
    return next(iter(kept)), len(kept) == len(cells)