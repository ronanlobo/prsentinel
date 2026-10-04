# Showing PRSentinel to somebody

This is the script for the demo. It is meant to be read on the train, not
studied. Everything here is something the app really does, and nothing here is
something the app only sometimes does.

## What you are looking at

PRSentinel is given the code as it was and the code as it now is. It works out
which function changed, gets tests to run against both, and then says what each
failing test is evidence of:

- **REAL_BUG** — it passed on the old code, fails on the new one, and failed
  again every time it was repeated. It is pointing at something the change
  broke.
- **BAD_TEST** — it fails on the old code too. It was already wrong, so it says
  nothing about this change.
- **FLAKY** — it passed in some of five repeat runs and failed in others. It
  cannot be trusted either way.

Only tests that fail on the new code are judged at all. A test that passes on
both halves has nothing to say about the change, and the page says so rather
than inventing a verdict for it.

That is the whole product. Everything else on the page is the work of getting
to those three words and back out again.

## Starting it

```powershell
.\scripts\run_demo.ps1
```

Open <http://127.0.0.1:8000>. Press Ctrl+C in that window to stop.

If you only want to know that it works, `.\scripts\run_demo.ps1 -Check` starts
it, checks the page answers, prints the cases it found, and stops again.

## Before you start, one decision

Leave **Saved tests** selected. It reuses a test file that already exists, so it
needs no API key, spends no allowance, and starts the moment you press Run.

Only move to **Generate fresh tests** if you want to show the AI writing tests
live. That needs `GROQ_API_KEY` set for your user account, and if it is not set
the app says so in one plain sentence and points you back at Saved tests rather
than failing.

## The three cases

| case | the change | what to point at |
| --- | --- | --- |
| `round1 off by one` | `scores[start:]` became `scores[-window - 1:]` | The plainest case, and the best one to open with. Eleven tests, all passing on the old code. Six of them fail on the new code and all six are REAL_BUG. The other five pass on both and are left unjudged, which is worth pointing out too: the tool does not invent a verdict for a test that had nothing to say. |
| `round2 mutable default` | `def add_item_to_cart(item, cart=[])` | The bug only shows up the second time you call the function, because the default list is built once and shared. The test calls it twice on purpose. Nine of its eleven tests fail on the new code and all nine are REAL_BUG; two pass on both. Use this one when somebody says "my tests all pass, so how is this broken". |
| `three verdicts` | `min()` given a negated key | All three verdicts in one run, from one saved test file. This is the case to end on. |

### What the three show about mutation

The first two cases score 100%, three deliberate faults out of three caught on
`before.py`. Only three mutants are found in each, because both functions are
two lines long, so treat the number as a floor rather than a grade.

The third case scores nothing at all, and the reason is worth saying out loud
because it comes straight out of the case design:

> mutation score: not defined — the tests already fail on the un-mutated code,
> so there is no green starting point

That is because `test_best_offer_of_an_unknown_code` fails on `before.py`. That
is the same fact that earns it the BAD_TEST verdict. The tool will not grade a
test suite it cannot get passing first, and it says why rather than reporting a
number it does not trust. This is also the honest reason the case to end on is
*not* the case with the best mutation score.

## The case to end on: `three verdicts`

One function changed. One saved test file. Three tests in it, and they come out
three different ways:

| test | verdict | why |
| --- | --- | --- |
| `test_best_offer_picks_the_smallest_discount` | REAL_BUG | Asserts gold beats silver. Passes on the old code, fails on the new one, fails all five reruns. |
| `test_best_offer_of_an_unknown_code` | BAD_TEST | Asserts an unknown code still yields `"gold"`. It fails on the old code too, so it says nothing about this change either way. |
| `test_reward_word_is_alpha` | FLAKY, about 57 runs in 100 | Walks a three item set, and set order is different in every process. |

The change is one character. `min()` was given the discount negated, so it now
picks the **largest** discount instead of the smallest. Nothing else in either
file moved:

```python
# before.py                                    # after.py
return min(live, key=lambda code: OFFERS[code])     return min(live, key=lambda code: -OFFERS[code])
```

A test that passed on the old code and checked the right offer would have caught
it. That is the whole point of the case.

### The flaky test is genuinely flaky

This is the part worth being ready to defend, because somebody will ask whether
the flake is arranged.

It is not. `reward_word()` returns the first item of a set of three strings, and
Python randomises string hashing per process, so the answer is different roughly
one time in three. There is no counter, no clock, no seeded random and no
environment variable anywhere near it. A test in `tests/test_app.py` parses all
three files and fails if any of those words is called.

`reward_word()` is byte for byte the same in `before.py` and `after.py`. It is
not part of the change and the app does not list it as one.

### What the odds actually are

Measured by pushing the case through the real test runner and the real
classifier, over and over, with no AI involved at any point. Three batches:
twenty runs, then eighty, then eighty again.

What each test came out as, over the hundred runs that recorded every test
individually:

| test | verdict | how often |
| --- | --- | --- |
| `test_best_offer_picks_the_smallest_discount` | REAL_BUG | **100 of 100** |
| `test_best_offer_of_an_unknown_code` | BAD_TEST | **100 of 100** |
| `test_reward_word_is_alpha` | FLAKY | 57 of 100 |
| | passed, so nothing to judge | 37 of 100 |
| | BAD_TEST | 6 of 100 |

The two fixed tests never once gave a different answer. Only the flaky one
varies.

What a click shows as a whole, over all 180 runs:

| | count | share |
| --- | --- | --- |
| all three verdicts | 109 | 61% |
| the flaky test passed, so two verdicts instead of three | 60 | 33% |
| the flaky test was judged BAD_TEST, so two of a kind | 11 | 6% |

So roughly **three clicks in five show all three verdicts**. One in three shows
the flaky test having passed, and one in seventeen shows it judged BAD_TEST.

### The measured numbers match the arithmetic, which is the point

The flaky test walks a three item set, so it produces the word it wants one
time in three and every run is a fresh dice roll. Work out from that alone, with
no fitting to the results, and:

| | worked out in advance | measured |
| --- | --- | --- |
| click shows all three verdicts | 58 in 100 | 61 in 100 |
| flaky test judged BAD_TEST | 6 in 100 | 6 in 100 |
| flaky test passed, nothing to judge | 33 in 100 | 33 in 100 |

The tool is not being lucky and the demo is not being staged. A flaky test has
to clear two separate hurdles to be called FLAKY — it must fail on the new code
at all, and then it must disagree with itself across five repeats — and two
hurdles each with a one-in-three miss rate is what produces 61 in 100. To make
the click show three verdicts more often, the only lever is to make the test
stop being flaky, and then the third verdict is not FLAKY any more.

It also predicts the awkward runs. For the flaky test to come out BAD_TEST, the
set has to land on a different word in **all seven** processes involved: the old
code, the new code, and all five repeats. That is `(2/3)⁷`, about 6 in 100, and
6 in 100 is what turned up. For it to come out REAL_BUG instead it would have
to pass on the old code while failing everywhere else, needing the set to land
the right way exactly once out of seven. That is rarer still, and it did not
happen in 180 runs.

### When a click shows something else

Say it out loud before your mentor notices it, and it is a feature rather than a
glitch:

> "That third test is the flaky one. It passes about a third of the time on its
> own. So on this run it either passed and had nothing to judge, or it failed
> every single repeat and reads as a bad test. Both of those are things it is
> allowed to say. Press it again."

The first two tests are not part of this. Across every run measured they came
out REAL_BUG and BAD_TEST, always. If either of them is ever anything else,
that is a bug in the tool and you should stop and say so rather than press Run
again.

## Saved or generated

The page says **saved** or **generated** in the result header, and it never uses
one word for the other. That distinction is the point of showing both modes, so
it is worth naming out loud:

> "Those tests were written earlier and saved. Nothing was generated just now,
> and no key was spent."

## What the app will not do

Worth knowing so you are not surprised:

- **It binds to `127.0.0.1` only.** Nothing on the network can reach it.
- **One run at a time.** A second click is refused with a plain sentence rather
  than queued.
- **A run that passes five minutes is stopped** and reported as *no result*, and
  the page says that this says nothing about the code.
- **It cleans up after itself, the moment the run's process ends.** Not when
  the page has finished reading, which means closing the tab halfway through
  leaves nothing behind either. The copied test, the scratch folder and the two
  report files all go. Reports carry a `demo_` prefix and only that prefix is
  ever deleted.
- **It refuses to overwrite a folder it did not make.** If something is already
  sitting in `generated_tests/demo_...` without the app's marker file, the run
  is refused and the existing file is left alone.
- **It never shows a key.** Not in a page, not in an answer, not in a log. If
  fresh mode is picked without a key it says the variable is not set, and that
  is the whole of what it says.

## The sentence at the bottom of every result

> Tests are AI-generated. A catching test is a hint, not proof.

It is on every result and it is the same sentence the GitHub Action leaves on
every pull request. It is there because a test that catches a change is not
proof that the change is a bug, and the tool does not know the difference.

## If something goes wrong

| what you see | what it means |
| --- | --- |
| The page will not open | The app is not running. Look at the window you started it from. |
| `A run is already going` | The previous run has not finished. Wait, or press Ctrl+C and restart. |
| `The folder demo_... already exists and was not made by this app` | Something real is in the way. Move it aside. The app will not touch it. |
| `No Groq key is set, so new tests cannot be written` | You picked Generate fresh tests. Switch to Saved tests. |
| `No result: the run took longer than 5 minutes and was stopped` | Mutation checking is slow. Turn off "Measure how many faults the tests catch" for a faster demo. |
| `No result: the AI allowance is used up` | Only happens in Generate fresh tests mode. Saved tests mode never asks the AI, so it cannot hit this. |
| A result with no functions listed | The two halves were not a before and an after of the same function. |