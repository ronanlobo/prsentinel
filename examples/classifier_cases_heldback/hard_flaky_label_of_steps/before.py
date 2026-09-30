"""Pick one label out of a list of steps."""


def label_of(steps):
    """Return one of the labels the steps carry."""
    return next(iter({step["label"] for step in steps}))