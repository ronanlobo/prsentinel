import pytest
from target import get_recent_scores

def old_behavior(scores, window):
    """Replicates the original implementation."""
    start = max(0, len(scores) - window)
    return scores[start:]

@pytest.mark.parametrize(
    "scores,window",
    [
        # Typical cases
        ([1, 2, 3, 4, 5], 3),
        ([10, 20, 30, 40], 2),
        # Window larger than list
        ([1, 2, 3], 5),
        # Window equal to list size
        ([7, 8, 9], 3),
        # Window zero
        ([1, 2, 3], 0),
        # Negative window
        ([1, 2, 3, 4], -2),
        # Empty list
        ([], 3),
        ([], 0),
        # Single element list
        ([42], 1),
        ([42], 0),
        ([42], -1),
    ],
)
def test_get_recent_scores_matches_old_behavior(scores, window):
    """
    Ensure the new implementation returns the same result as the original
    specification for a variety of edge cases and typical inputs.
    """
    expected = old_behavior(scores, window)
    result = get_recent_scores(scores, window)
    assert result == expected, f"Failed for scores={scores}, window={window}"
