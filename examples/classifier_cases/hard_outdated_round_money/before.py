"""Round a money amount to a whole unit."""


def round_money(amount):
    """Return the amount rounded to the nearest whole unit, halves going up."""
    return int(amount + 0.5)