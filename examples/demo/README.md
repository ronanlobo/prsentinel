# Demo cases

Three self-contained changes. Each folder holds the old code (`before.py`), the
new code (`after.py`) and one test file that was written earlier and is being
reused, not regenerated. The demo app copies that test into the place the
pipeline looks for it and then runs the real pipeline on it.

Nothing in this folder is read by the pipeline itself. These folders are inputs
for the demo app only, which is why they can sit here without touching anything
else in the project.

| case | what it shows |
| --- | --- |
| `round1_off_by_one` | A plain off-by-one in a slice. The kind of change where the old tests all pass and the new tests catch it. |
| `round2_mutable_default` | A mutable default argument. The bug hides until the function is called twice, which is what the test does. |
| `three_verdicts` | One changed function and one saved test file that produce all three verdicts in a single run: `REAL_BUG`, `BAD_TEST` and `FLAKY`. |

## `three_verdicts` in a bit more detail

`best_offer` picks the code with the smallest discount. The change negates the
number, so `min()` now picks the largest instead. One saved test file covers
three different situations:

| test | what happens | verdict |
| --- | --- | --- |
| `test_best_offer_picks_the_smallest_discount` | Passes on the old code, fails on the new one, fails all five reruns | `REAL_BUG` |
| `test_best_offer_of_an_unknown_code` | Fails on the old code too, so it says nothing about the change | `BAD_TEST` |
| `test_reward_word_is_alpha` | Walks a three item set, so which word comes out is different in every process | `FLAKY` |

The flakiness is not arranged with a counter or a seed. `reward_word()` returns
the first item of a set of three words, and Python randomises string hashing
per process, so the answer is different roughly one time in three. The measured
odds are in `DEMO.md`.

`reward_word()` is byte for byte the same in `before.py` and `after.py`. It is
not part of the change and the app does not report it as one.