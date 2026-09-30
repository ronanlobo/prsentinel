"""Report how many days a month has."""


def days_in_month(year, month):
    """Return how many days the given month has.

    The month number is checked before the table is read, so an unknown month
    is reported clearly instead of quietly returning the length of a different
    month.
    """
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")

    lengths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return lengths[month - 1]