========================================================================
PRSentinel report for round2_mutable_default
========================================================================
Old file: before.py
New file: after.py
Tests: reused from baselines
repair: off
fallback: on
answers from Gemini: 0

--- Per function ---

add_item_to_cart  (modified)
  test file: test_add_item_to_cart.py
  came from: baselines
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

--- Mutation (do the tests really catch a fault?) ---
  A mutant is a copy of the changed function with one small
  deliberate fault, such as + changed to - or < changed to
  <=. If a test fails on it the mutant is killed; if every
  test still passes it survived. Some survivors may be
  equivalent mutants, which no test could ever kill, so the
  score is a lower bound, not an exact grade.

  Operators tried:
    + to -, - to +, < to <=, <= to <, > to >=, >= to >, True to False,
    False to True, == to !=, != to ==, is None to is not None, is not
    None to is None, and to or, or to and, n to n + 1, None default to
    [], [] default to None, return expr to return None

  Note: "return expr to return None" fires on almost every
  function and is killed by almost any test that looks at the
  result, so it can push the score up. Read it as "the tests
  check the result", not as extra strength.

  add_item_to_cart  (modified)
    version mutated : before.py (the version the tests pass on)
    mutants found   : 3
    killed          : 3
    survived        : 0
    equivalent      : 0
    timed out       : 0
    could not run   : 0
    mutation score  : 100% (3 of 3)
    kills per operator (killed of scored):
      is None to is not None         1 of 1
      None default to []             1 of 1
      return expr to return None     1 of 1

--- Summary ---
9 tests point to a real bug in add_item_to_cart.
