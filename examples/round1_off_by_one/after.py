"""Example code AFTER the change.

The off-by-one change has gone in, but it is wrong. Asking for one score from
[10, 20, 30] gives [20] instead of [30]. This file is the BUGGY version.
"""


def get_recent_scores(scores, window):
    """Return the most recent scores, newest last."""
    return scores[-window - 1:]


def average_score(scores):
    """Return the average of the scores, or 0.0 when there are none."""
    if not scores:
        return 0.0
    return sum(scores) / len(scores)
