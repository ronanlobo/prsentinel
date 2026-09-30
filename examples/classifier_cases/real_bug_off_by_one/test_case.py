"""A test that correctly checks what the function promises to do."""

from target import last_items


def test_returns_the_last_two_items():
    assert last_items([1, 2, 3, 4], 2) == [3, 4]
