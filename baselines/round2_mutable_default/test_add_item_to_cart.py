import pytest
from target import add_item_to_cart

def test_default_cart_is_fresh_each_call():
    """Each call without providing a cart should start with an empty list."""
    cart1 = add_item_to_cart("apple")
    cart2 = add_item_to_cart("banana")
    assert cart1 == ["apple"]
    assert cart2 == ["banana"]
    # The two returned carts should be distinct objects
    assert cart1 is not cart2

def test_explicit_cart_is_mutated_and_returned():
    """When a cart is supplied, the function should mutate and return it."""
    external = ["milk"]
    result = add_item_to_cart("eggs", cart=external)
    assert result is external  # same object
    assert result == ["milk", "eggs"]
    # Adding another item should keep mutating the same list
    result2 = add_item_to_cart("bread", cart=external)
    assert result2 is external
    assert result2 == ["milk", "eggs", "bread"]

def test_multiple_calls_with_explicit_cart_do_not_interfere():
    """Separate explicit carts should not affect each other."""
    cart_a = []
    cart_b = []
    add_item_to_cart(1, cart=cart_a)
    add_item_to_cart(2, cart=cart_b)
    assert cart_a == [1]
    assert cart_b == [2]

@pytest.mark.parametrize("item", [None, "", 0, [], {}])
def test_various_items_can_be_added(item):
    """The function should accept any item type, including falsy values."""
    cart = add_item_to_cart(item)
    assert cart == [item]

def test_adding_multiple_items_sequentially():
    """Adding items sequentially without providing a cart should accumulate correctly per call."""
    items = ["a", "b", "c"]
    carts = [add_item_to_cart(i) for i in items]
    # Each call returns a cart with only the single added item
    assert carts == [["a"], ["b"], ["c"]]

def test_cart_isolation_after_mutating_returned_cart():
    """Mutating the returned cart should not affect subsequent default calls."""
    cart = add_item_to_cart("first")
    cart.append("extra")
    # Next call should not see the 'extra' item
    new_cart = add_item_to_cart("second")
    assert new_cart == ["second"]
    assert cart == ["first", "extra"]

def test_default_cart_is_not_shared_across_test_runs():
    """Ensure that test isolation is preserved (pytest may run tests in any order)."""
    # Call the function a few times to simulate prior usage
    for _ in range(3):
        add_item_to_cart("temp")
    # Now get a fresh cart
    fresh = add_item_to_cart("final")
    assert fresh == ["final"]
