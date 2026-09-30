"""Answer key case: reading the first letter of a list of words."""


def first_letter(words):
    """Return the first letter of the first word in the list."""
    if not words:
        return ""
    return words[0][0]
