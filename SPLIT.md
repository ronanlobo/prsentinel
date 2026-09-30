# The split between the tuning set and the held-back set

This file is the record of which cases PRSentinel was allowed to look at while
it was being built, and which were kept back to be scored once at the end.

**This split is declared once and must never be changed.** If a case moves
between the two lists, the held-back score no longer means anything, because
somebody would have seen the answer. Adding a new case later is fine, but
moving an existing one is not.

## The two sets

`examples/classifier_cases/` is the **tuning set**. Everything in it has been
looked at while the tool was being built and changed.

`examples/classifier_cases_heldback/` is the **held-back set**. It is scored by
one separate command, `python -m prsentinel.heldback_eval`, and nothing else in
the project is allowed to read it.

## The split

| case | set | kind | answer |
|---|---|---|---|
| `real_bug_off_by_one` | tuning | REAL_BUG | REAL_BUG |
| `real_bug_loop_skips_last` | tuning | REAL_BUG | REAL_BUG |
| `real_bug_wrong_divisor` | tuning | REAL_BUG | REAL_BUG |
| `bad_test_wrong_expected_value` | tuning | BAD_TEST | BAD_TEST |
| `bad_test_wrong_assumption` | tuning | BAD_TEST | BAD_TEST |
| `bad_test_invented_rule` | tuning | BAD_TEST | BAD_TEST |
| `flaky_set_order` | tuning | FLAKY | FLAKY |
| `flaky_random_pick` | tuning | FLAKY | FLAKY |
| `flaky_current_time` | tuning | FLAKY | FLAKY |
| `hard_outdated_total_price` | tuning | OUTDATED_TEST | BAD_TEST |
| `hard_outdated_round_money` | tuning | OUTDATED_TEST | BAD_TEST |
| `hard_preexisting_days_in_month` | tuning | PRE_EXISTING_BUG | REAL_BUG |
| `hard_preexisting_average` | tuning | PRE_EXISTING_BUG | REAL_BUG |
| `hard_flaky_pick_one` | tuning | FLAKY_REALISTIC | FLAKY |
| `hard_outdated_last_seen` | **held back** | OUTDATED_TEST | BAD_TEST |
| `hard_preexisting_discount_rate` | **held back** | PRE_EXISTING_BUG | REAL_BUG |
| `hard_flaky_label_of_steps` | **held back** | FLAKY_REALISTIC | FLAKY |
| `hard_flaky_first_cell` | **held back** | FLAKY_REALISTIC | FLAKY |

14 cases in the tuning set, 4 in the held-back set, 18 in total.

Tuning set by answer: REAL_BUG 5, BAD_TEST 5, FLAKY 4.
Held-back set by answer: REAL_BUG 1, BAD_TEST 1, FLAKY 2.

## Why the hard cases were split this way

The two kinds that need new evidence to get right, OUTDATED_TEST and
PRE_EXISTING_BUG, got more cases in the tuning set, because that is what the
new `full_with_intent` mode is for. FLAKY_REALISTIC got fewer, because the three
older flaky cases already exercise the rerun mechanism.

## No module is shared

Every case has its own `before.py` and its own `after.py`. No held-back case
shares a module with a tuning case, so nothing can carry across the line.

## What the two sets are for

The tuning set is where the tool is developed and where the everyday accuracy
figures come from. The held-back set is scored once, at the end, to show how
the tool does on cases it has never seen.