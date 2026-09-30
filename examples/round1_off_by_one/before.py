"""Example code BEFORE the change.

Round 1 simulates a real bug report. get_recent_scores is supposed to return
only the newest `window` scores. This version gets it right.
"""


def get_recent_scores(scores, window):
    """Return the most recent scores, newest last."""
    # Correct: never start before the beginning of the list, so a window that
    # is bigger than the list still returns every score.
    start = max(0, len(scores) - window)
    return scores[start:]


def average_score(scores):
    """Return the average of the scores, or 0.0 when there are none."""
    if not scores:
        return 0.0
    return sum(scores) / len(scores)
