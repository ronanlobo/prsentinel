"""Pick one label out of a list of steps."""

EMPTY_MESSAGE = "there must be at least one step"


def label_of(steps):
    """Return one of the labels the steps carry.

    An empty list is now reported as an error, rather than causing a confusing
    message from further down.
    """
    if not steps:
        raise ValueError(EMPTY_MESSAGE)

    return next(iter({step["label"] for step in steps}))