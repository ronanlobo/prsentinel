# Prompt log

Every prompt version we have tried for the AI classifier, in the order we tried
them, with the score each one got on the tuning set.

**Two versions only. There is no v3.**

## How to read this file

Each version is shown against one fixed piece of evidence: `frozen_evidence()`
from `tests/test_classifier.py`, the same helper the frozen-string tests use.
Showing the complete prompt for the same fixed evidence is what makes two
versions comparable by eye. If a prompt changed by a single space, the block
below is where you would see it.

That evidence deliberately has a mixed rerun result (1 pass, 4 fails) and a
description, so every mode's extra section has something to act on.

## Which set the scores come from

Every score in this file is from the **tuning set only**:
`examples/classifier_cases/`, 14 cases, 12 reruns each.

**Tuned on the tuning set only.** The kept-back cases in
`examples/classifier_cases_heldback/` have never been scored, and no prompt in
this file was written after looking at them. That is the entire reason they
exist: a prompt written against a set it has already been graded on is only
measuring how well it memorised it. The kept-back score is the one worth
believing, and it is still unspent.

---

## v1 - `full`  (the starting point)

- **Date:** 2026-09-30 (first measured). Re-measured 2026-10-01, see the two
  score lines below.
- **Mode:** `full`  |  **Classifier name:** `llm_full`
- **Tuning scores, 2026-09-30 (Step 7A, four classifiers scored):** run 1
  **12/14 (86%)**, run 2 **12/14 (86%)**. Mean 12/14 (86%), lowest 86%, highest
  86%.
- **Tuning scores, 2026-10-01 (Step 7C, `rule`, `llm_full` and `llm_full_v2`
  scored):** run 1 **12/14 (86%)**, run 2 **12/14 (86%)**. Mean 12/14 (86%),
  lowest 86%, highest 86%.
- **Measured during:** both sets above. 2026-09-30 during Step 7A, after the
  five hard cases were added. 2026-10-01 during Step 7C, two separate single
  runs, Groq only, 28 of 28 answers from Groq and none from Gemini, no early
  stop, 12 reruns per case.
- **Note:** tuned on the tuning set only.

This is the prompt everything else is compared against. It shows the code, the
diff, the test, the failure message and the run results, and nothing else.

### Where it fell short

v1 and `llm_full_with_intent` both answer **BAD_TEST** on the three old flaky
cases. Their reasons read like "the test expects 'a' even when the first word is
'banana', which contradicts the intended behavior", which is a fair reading of
the test on its own. The results section is three lines of numbers, and nothing
in the prompt explains what two numbers on the same line are telling us, so the
AI treats a mixed rerun as noise and reasons straight past it. That is the gap
v2 was written to close.

v1 and `llm_full_with_intent` also disagree with each other about which cases
they miss, and change from one run to the next. The AI is not the same twice, so
every single score in this file is a sample rather than a measurement.

### The complete prompt

````
You are looking at one failing test and trying to work out what is going on.

Here is the code before the change.
```python
def add(a, b):
    return a + b

```

Here is the code after the change.
```python
def add(a, b, c):
    return a + b + c

```

Here is the difference between them.
```diff
--- before
+++ after
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + b
+    return a + b + c

```

Here is the test.
```python
def test_add():
    assert add(2, 3) == 5

```

Here is what the test printed when it failed.
```text
assert 8 == 5

```

Here is how this test behaved when it was run.

Result on the code before the change: passed
Result on the code after the change: failed
When the test was run again several times on the new code, it gave 1 pass and 4 fail.


Choose exactly one label:
- REAL_BUG: the test is reasonable and the new code broke intended behavior
- BAD_TEST: the test expects something the code was never meant to do, or the change was intentional and the test is now outdated
- FLAKY: the test result depends on chance (randomness, time, ordering) rather than on the code

Base your answer on what the code is trying to do and what the test is checking. You cannot see any folder names or file paths, so do not try to guess from them.

Reply with JSON only, using exactly this shape:
{"label": "REAL_BUG" | "BAD_TEST" | "FLAKY", "confidence": "low" | "medium" | "high", "reason": "one or two plain sentences"}
No other text.
````

---

## v2 - `full_v2`

- **Date:** 2026-10-01
- **Mode:** `full_v2`  |  **Classifier name:** `llm_full_v2`
- **Change from v1:** one added section, and nothing else. Take that section out
  of the prompt below and what is left is v1, character for character. A test
  checks that; it is not just a claim made here.
- **Tuning scores:** run 1 **13/14 (93%)**, run 2 **13/14 (93%)**. Mean 13/14
  (93%), lowest 93%, highest 93%.
- **Measured during:** Step 7C, two separate single runs on 2026-10-01, Groq
  only, 28 of 28 answers from Groq and none from Gemini, no early stop, 12
  reruns per case.
- **Note:** tuned on the tuning set only.

### The added section, on its own

This is the only thing v2 changes. It explains what a mixed rerun result means.
It never names a label and never says what to choose, so the AI still has to
work the label out itself. It uses no name, value or wording from any case.

````
How to read the results above.

The last line above says how the same code and the same test behaved when the
test was run again. If that line reports both passes and fails, then the test
did not settle on one answer. The code was identical between those runs, and
what the test is asking for did not change either, so the only thing left that
could move the outcome is chance: something outside the code and outside what
the test is asking for is deciding the result from one run to the next.

When that happens the result cannot be trusted as evidence about the code or
about the test. An outcome that changes by chance is not showing a fault in
either one, so it should not be read as one.
````

### The complete prompt

````
You are looking at one failing test and trying to work out what is going on.

Here is the code before the change.
```python
def add(a, b):
    return a + b

```

Here is the code after the change.
```python
def add(a, b, c):
    return a + b + c

```

Here is the difference between them.
```diff
--- before
+++ after
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + b
+    return a + b + c

```

Here is the test.
```python
def test_add():
    assert add(2, 3) == 5

```

Here is what the test printed when it failed.
```text
assert 8 == 5

```

Here is how this test behaved when it was run.

Result on the code before the change: passed
Result on the code after the change: failed
When the test was run again several times on the new code, it gave 1 pass and 4 fail.


How to read the results above.

The last line above says how the same code and the same test behaved when the
test was run again. If that line reports both passes and fails, then the test
did not settle on one answer. The code was identical between those runs, and
what the test is asking for did not change either, so the only thing left that
could move the outcome is chance: something outside the code and outside what
the test is asking for is deciding the result from one run to the next.

When that happens the result cannot be trusted as evidence about the code or
about the test. An outcome that changes by chance is not showing a fault in
either one, so it should not be read as one.

Choose exactly one label:
- REAL_BUG: the test is reasonable and the new code broke intended behavior
- BAD_TEST: the test expects something the code was never meant to do, or the change was intentional and the test is now outdated
- FLAKY: the test result depends on chance (randomness, time, ordering) rather than on the code

Base your answer on what the code is trying to do and what the test is checking. You cannot see any folder names or file paths, so do not try to guess from them.

Reply with JSON only, using exactly this shape:
{"label": "REAL_BUG" | "BAD_TEST" | "FLAKY", "confidence": "low" | "medium" | "high", "reason": "one or two plain sentences"}
No other text.
````

---

## Result

v2 was one case ahead of v1 in both runs, which is 7 percentage points. But the
case that v2 got right and v1 got wrong was not the same case in the two runs:
in run 1 it was `flaky_current_time`, and in run 2 it was `flaky_set_order`. So
this is a small and inconsistent improvement, not a proven one. A consistent
gain would have fixed the same case twice.

`flaky_random_pick` was wrong in both versions, in both runs. It is the one case
neither prompt solves, and neither the older prompt nor the newer one reaches it.

Only two runs were done. A third was skipped for time. Both are written above
rather than one of them being kept, because picking the better of two runs is
exactly what this file exists to prevent.

The three old flaky cases contain a `RUN_INDEX` giveaway. Some of the AI reasons
mention it, which means part of what these scores measure is the AI noticing a
name rather than reasoning about the evidence. The prompts themselves never name
it, and a test checks that no prompt leaks it.

v2 was the second and last prompt version. There is no v3, and the section below
says why.

One thing worth keeping in mind when reading the v2 number: the added section
partly gives the AI a hint by elimination. It reasons that if the result cannot
be trusted, then it is not a fault in the code or the test, and works back from
there. That is the intended effect, but it is guidance rather than the AI
working the answer out from the evidence on its own, so part of any gain is the
effect of that guidance rather than a better reading of the rerun line. A
version that only stated the fact, with no reasoning attached to it, was not
tried, so this cannot be separated from the score.

## Frozen

The prompts are frozen as of the hashes below. A test fails if any of them
changes.

- **HEAD when v2 was frozen:** `c826fab717153bf81344771f581e937289a24201`
- **Last commit to change `src/prsentinel/classifier.py`:**
  `6115ed0dcedca83b922ef1e38b5155b68c62f0db`

## What the kept-back run scores

The kept-back run scores three classifiers and no others: **`rule`,
`llm_full`, `llm_full_v2`**. `llm_full_with_intent` and `llm_code_only` are not
scored there. The kept-back run is the one number this project cannot tune
against, so it is kept as small as the question needs it to be.

---

## Why there is no v3

There is no v3 because v2 is the last prompt change we make on the strength of
the tuning set alone. One added section is one experiment.

If v2 does not beat v1, the honest answer is that the section did not work, and
the way to find that out is to score the kept-back cases. It is not to keep
rewriting the prompt against the same 14 cases until one of them happens to
score well.

A v3 tuned until it scored well on the tuning set would tell us nothing at all
about the kept-back set. That is the trap this file exists to avoid, so it has
two entries in it and it will not get a third.
