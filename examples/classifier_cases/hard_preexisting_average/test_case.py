"""Check the mean of two uneven numbers."""

from target import average


def test_average_of_one_and_two_is_one_point_five():
    assert average([1, 2]) == 1.5