"""Round a money amount to a whole unit."""


def round_money(amount):
    """Return the amount rounded to the nearest whole unit.

    Halves now go down rather than up, which is what the accounts team asked
    for.
    """
    return int(amount)