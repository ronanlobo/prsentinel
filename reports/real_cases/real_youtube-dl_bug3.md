========================================================================
PRSentinel report for real_youtube-dl_bug3
========================================================================
Old file: before.py
New file: after.py
Tests: generated
repair: off
fallback: off
answers from Gemini: 0

--- Per function ---

unescapeHTML  (modified)
  test file: test_unescapeHTML.py
  CATCHES_CHANGE           0
  TEST_WRONG_ON_BEFORE     3
  NO_SIGNAL                16
  ODD                      0
  Tests we judged:
    test_unescapeHTML::test_unescapeHTML_basic_cases[&lt;div&gt;Hello &amp; welcome&#33;&lt;/div&gt;-<div>Hello & welcome!<\\/div>]  (TEST_WRONG_ON_BEFORE)
      verdict : BAD_TEST
      why     : It failed on the old code as well (failed), so the test is not agreeing with code that was already working.
    test_unescapeHTML::test_unescapeHTML_basic_cases[&amp;;-&&]  (TEST_WRONG_ON_BEFORE)
      verdict : BAD_TEST
      why     : It failed on the old code as well (failed), so the test is not agreeing with code that was already working.
    test_unescapeHTML::test_unescapeHTML_compare_with_html_unescape  (TEST_WRONG_ON_BEFORE)
      verdict : BAD_TEST
      why     : It failed on the old code as well (failed), so the test is not agreeing with code that was already working.

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

  unescapeHTML  (modified)
    mutation score  : not defined
    reason          : the tests already fail on the un-mutated code, so there is no green starting point

--- Summary ---
No test points to a real bug in the code.
