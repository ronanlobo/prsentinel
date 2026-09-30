"""Work out which step to report on."""

EMPTY_MESSAGE = "there must be at least one step"


def label_of(steps):
    """Return the label of the first step."""
    if not steps:
        raise ValueError(EMPTY_MESSAGE)

    return steps[0]["label"]