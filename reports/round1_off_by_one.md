========================================================================
PRSentinel report for round1_off_by_one
========================================================================
Old file: before.py
New file: after.py
Tests: reused from baselines
repair: off
fallback: on
answers from Gemini: 0

--- Per function ---

get_recent_scores  (modified)
  test file: test_get_recent_scores.py
  came from: baselines
  CATCHES_CHANGE           6
  TEST_WRONG_ON_BEFORE     0
  NO_SIGNAL                5
  ODD                      0
  Tests we judged:
    test_get_recent_scores::test_get_recent_scores_matches_old_behavior[scores0-3]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_get_recent_scores::test_get_recent_scores_matches_old_behavior[scores1-2]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_get_recent_scores::test_get_recent_scores_matches_old_behavior[scores4-0]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_get_recent_scores::test_get_recent_scores_matches_old_behavior[scores5--2]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_get_recent_scores::test_get_recent_scores_matches_old_behavior[scores9-0]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_get_recent_scores::test_get_recent_scores_matches_old_behavior[scores10--1]  (CATCHES_CHANGE)
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

  get_recent_scores  (modified)
    version mutated : before.py (the version the tests pass on)
    mutants found   : 3
    killed          : 3
    survived        : 0
    equivalent      : 0
    timed out       : 0
    could not run   : 0
    mutation score  : 100% (3 of 3)
    kills per operator (killed of scored):
      - to +                         1 of 1
      n to n + 1                     1 of 1
      return expr to return None     1 of 1

--- Summary ---
6 tests point to a real bug in get_recent_scores.
