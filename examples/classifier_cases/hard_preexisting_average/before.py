"""Work out the mean of some numbers."""


def average(numbers):
    """Return the mean of the numbers."""
    if not numbers:
        return 0
    return sum(numbers) // len(numbers)