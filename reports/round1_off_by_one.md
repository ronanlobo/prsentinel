========================================================================
PRSentinel report for round1_off_by_one
========================================================================
Old file: before.py
New file: after.py
Tests: reused in generated_tests/round1_off_by_one/

--- Per function ---

get_recent_scores  (modified)
  test file: test_get_recent_scores.py
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

--- Summary ---
6 tests point to a real bug in get_recent_scores.
