"""Answer key case: joining a list of names into one string."""


def join_names(names):
    """Join the names together with a comma and a space."""
    parts = []
    for name in names:
        parts.append(name.strip())
    return ", ".join(parts)
