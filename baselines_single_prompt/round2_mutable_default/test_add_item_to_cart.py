import pytest
from target import add_item_to_cart

def test_default_cart_is_new_each_call():
    cart1 = add_item_to_cart('apple')
    cart2 = add_item_to_cart('banana')
    assert cart1 == ['apple']
    assert cart2 == ['banana']
    assert cart1 is not cart2

def test_explicit_cart_is_mutated_and_returned():
    my_cart = []
    result = add_item_to_cart('orange', my_cart)
    assert result is my_cart
    assert my_cart == ['orange']

def test_default_cart_not_shared_with_explicit_cart():
    explicit = ['existing']
    add_item_to_cart('pear', explicit)
    assert explicit == ['existing', 'pear']
    default_cart = add_item_to_cart('grape')
    assert default_cart == ['grape']
    # Ensure the default cart does not contain items from the explicit cart
    assert 'pear' not in default_cart
    assert 'existing' not in default_cart

def test_none_cart_behaviour_matches_old_implementation():
    cart = add_item_to_cart('kiwi', None)
    assert cart == ['kiwi']
