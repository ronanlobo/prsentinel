========================================================================
PRSentinel report for round2_mutable_default
========================================================================
Old file: before.py
New file: after.py
Tests: reused in generated_tests/round2_mutable_default/

--- Per function ---

add_item_to_cart  (modified)
  test file: test_add_item_to_cart.py
  CATCHES_CHANGE           9
  TEST_WRONG_ON_BEFORE     0
  NO_SIGNAL                2
  ODD                      0
  Tests we judged:
    test_add_item_to_cart::test_default_cart_is_fresh_each_call  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_add_item_to_cart::test_various_items_can_be_added[None]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_add_item_to_cart::test_various_items_can_be_added[]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_add_item_to_cart::test_various_items_can_be_added[0]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_add_item_to_cart::test_various_items_can_be_added[item3]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_add_item_to_cart::test_various_items_can_be_added[item4]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_add_item_to_cart::test_adding_multiple_items_sequentially  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_add_item_to_cart::test_cart_isolation_after_mutating_returned_cart  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_add_item_to_cart::test_default_cart_is_not_shared_across_test_runs  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.

--- Summary ---
9 tests point to a real bug in add_item_to_cart.
