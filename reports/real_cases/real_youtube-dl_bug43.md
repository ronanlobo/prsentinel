========================================================================
PRSentinel report for real_youtube-dl_bug43
========================================================================
Old file: before.py
New file: after.py
Tests: generated
repair: off
fallback: off
answers from Gemini: 0

--- Per function ---

url_basename  (modified)
  test file: test_url_basename.py
  CATCHES_CHANGE           5
  TEST_WRONG_ON_BEFORE     0
  NO_SIGNAL                19
  ODD                      0
  Tests we judged:
    test_url_basename::test_url_basename_expected_behavior[http://example.com/a/b/c-c]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_url_basename::test_url_basename_expected_behavior[https://example.com/one/two/three/-three]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_url_basename::test_url_basename_expected_behavior[//example.com/x/y/z?query-z]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_url_basename::test_url_basename_expected_behavior[http://example.com/segment1/segment2/segment3#frag-segment3]  (CATCHES_CHANGE)
      verdict : REAL_BUG
      why     : It passed on the old code and fails on the new one (failed), so the change is what broke it.
    test_url_basename::test_url_basename_regression_multiple_segments  (CATCHES_CHANGE)
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

  url_basename  (modified)
    version mutated : before.py (the version the tests pass on)
    mutants found   : 3
    killed          : 3
    survived        : 0
    equivalent      : 0
    timed out       : 0
    could not run   : 0
    mutation score  : 100% (3 of 3)
    kills per operator (killed of scored):
      n to n + 1                     1 of 1
      return expr to return None     2 of 2

--- Summary ---
5 tests point to a real bug in url_basename.
