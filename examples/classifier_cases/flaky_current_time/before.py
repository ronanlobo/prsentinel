"""Answer key case: comparing two timestamps."""


def is_same_day(first_stamp, second_stamp):
    """Report whether two timestamps fall on the same calendar day."""
    return first_stamp[:10] == second_stamp[:10]
