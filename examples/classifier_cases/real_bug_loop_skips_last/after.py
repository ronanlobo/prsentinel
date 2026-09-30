"""Answer key case: joining a list of names into one string.

This file is the "after" version of the example.
"""


def join_names(names):
    """Join the names together with a comma and a space."""
    parts = []
    for position in range(len(names) - 1):
        parts.append(names[position].strip())
    return ", ".join(parts)
