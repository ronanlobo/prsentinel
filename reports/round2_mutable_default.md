========================================================================
PRSentinel report for round2_mutable_default
========================================================================
Old file: before.py
New file: after.py
Tests: generated
repair: on
fallback: off
answers from Gemini: 0

--- Per function ---

add_item_to_cart  (modified)
  test file: test_add_item_to_cart.py
  CATCHES_CHANGE           4
  TEST_WRONG_ON_BEFORE     0
  NO_SIGNAL                4
  ODD                      0
  Tests we judged:
    test_add_item_to_cart::test_default_cart_is_fresh_each_call  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_add_item_to_cart::test_default_cart_not_shared_across_calls  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_add_item_to_cart::test_append_none_item  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_add_item_to_cart::test_cart_parameter_immutability_when_not_provided  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.

--- Repairs ---
  A test judged to be the wrong test was sent back to the
  writer to be corrected. Nothing was changed unless the
  corrected test passed on the old code and left the rest of
  the file as strong as it was.
  No test was judged to be the wrong test, so there was
  nothing to repair.

  repaired: 0   unrepaired: 0   weakened: 0

--- Summary ---
4 tests point to a real bug in add_item_to_cart.
