"""Work out which step to run first."""

EMPTY_MESSAGE = "there must be at least one step"


def label_of(steps):
    """Return the label of the last step that was recorded.

    The label of the final step is the one that matters for reporting, so this
    used to return the label of whichever step happened to be first.
    """
    if not steps:
        raise ValueError(EMPTY_MESSAGE)

    return steps[-1]["label"]