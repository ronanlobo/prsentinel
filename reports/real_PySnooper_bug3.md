========================================================================
PRSentinel report for real_PySnooper_bug3
========================================================================
Old file: before.py
New file: after.py
Tests: generated
repair: off
fallback: off
answers from Gemini: 0

--- Per function ---

get_write_function  (modified)
  test file: test_get_write_function.py
  CATCHES_CHANGE           1
  TEST_WRONG_ON_BEFORE     0
  NO_SIGNAL                3
  ODD                      0
  Tests we judged:
    test_get_write_function::test_path_output_writes_to_file  (CATCHES_CHANGE)
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

  get_write_function  (modified)
    version mutated : before.py (the version the tests pass on)
    mutants found   : 2
    killed          : 2
    survived        : 0
    equivalent      : 0
    timed out       : 0
    could not run   : 0
    mutation score  : 100% (2 of 2)
    kills per operator (killed of scored):
      is None to is not None         1 of 1
      return expr to return None     1 of 1

--- Summary ---
1 test points to a real bug in get_write_function.
