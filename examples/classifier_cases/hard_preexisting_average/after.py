"""Work out the mean of some numbers."""


def average(numbers):
    """Return the mean of the numbers.

    Any collection can be passed in now, because the values are turned into a
    list before they are used.
    """
    numbers = list(numbers)

    if not numbers:
        return 0
    return sum(numbers) // len(numbers)