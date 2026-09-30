"""Report how many days a month has."""


def days_in_month(year, month):
    """Return how many days the given month has."""
    lengths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return lengths[month - 1]