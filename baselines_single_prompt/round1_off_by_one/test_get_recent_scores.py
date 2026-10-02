import pytest
from target import get_recent_scores

def expected_recent_scores(scores, window):
    start = max(0, len(scores) - window)
    return scores[start:]

@pytest.mark.parametrize(
    "scores,window,expected",
    [
        ([], 5, []),
        ([1, 2, 3, 4, 5], 3, [3, 4, 5]),
        ([1, 2, 3, 4, 5], 10, [1, 2, 3, 4, 5]),
        ([1, 2, 3, 4, 5], 0, []),
        ([42], 1, [42]),
        ([7, 8], 1, [8]),
        (list(range(10)), 5, list(range(5, 10))),
        (list(range(1, 21)), 15, list(range(6, 21))),
    ],
)
def test_get_recent_scores_matches_expected(scores, window, expected):
    assert get_recent_scores(scores, window) == expected
