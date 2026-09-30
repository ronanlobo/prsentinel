"""Answer key case: counting capital letters."""


def count_capitals(text):
    """Count how many capital letters the text has."""
    total = 0
    for letter in text:
        if letter.isupper():
            total += 1
    return total
