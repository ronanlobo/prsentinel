"""Check which item comes back first."""

from target import pick_one


def test_pick_one_gives_the_first_item():
    assert pick_one(["apple", "banana"]) == "apple"