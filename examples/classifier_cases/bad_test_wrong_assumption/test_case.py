"""A test for top_scores."""

from target import top_scores


def test_sorts_low_to_high():
    assert top_scores([3, 1, 2]) == [1, 2, 3]
