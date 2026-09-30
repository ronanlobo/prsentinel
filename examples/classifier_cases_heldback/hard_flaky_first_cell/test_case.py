"""Check where a path starts and whether it lost anything."""

from target import first_and_complete


def test_first_and_complete_starts_at_north():
    assert first_and_complete(["north", "south"]) == ("north", True)