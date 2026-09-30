"""Check which cells a path covers."""


def first_and_complete(cells):
    """Return the first cell, and whether every cell was kept."""
    kept = frozenset(cells)
    return next(iter(kept)), len(kept) == len(cells)