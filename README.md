# PRSentinel

PRSentinel is an AI tool that looks at a code change (a "diff") in a Python
project, works out which functions changed, and later on generates tests for
that change. It will then look at a failing test and decide whether the failure
is a real bug, a bad test, or a flaky test.

## Where the project is right now

This is **Step 6**. The whole tool runs with one command now. These parts are
built:

- `config.py` - the settings, including the API keys read from the environment
- `llm_client.py` - `ask_llm(prompt)`, which tries Groq and falls back to Gemini
- `diff_extractor.py` - finds which functions were added, removed or modified
- `test_generator.py` - asks the AI for tests aimed at each changed function
- `test_runner.py` - runs each test file against the old and the new code
- `classifier.py` - decides whether a failure is a real bug, a bad test, or flaky
- `classifier_eval.py` - scores the classifier against nine cases with known
  answers
- `pipeline.py` - does all of the above in one go and writes a report

Still to build: a repair loop, mutation testing, Docker, FastAPI, a database and
a web interface.

## Folder layout

```
prsentinel/
  src/prsentinel/
    __init__.py
    config.py            <- settings live here, nowhere else
    llm_client.py        <- ask_llm()
    diff_extractor.py    <- which functions changed
    test_generator.py    <- asks the AI for tests
    test_runner.py       <- runs the tests on old and new code
    classifier.py        <- real bug, bad test, or flaky
    classifier_eval.py   <- scores the classifier on nine known answers
    pipeline.py          <- all of it, with one command
  scripts/
    smoke_llm.py         <- checks the real providers (uses the internet)
  tests/
    test_diff_extractor.py
    test_llm_client.py   <- fake providers, never uses the internet
    test_test_generator.py
    test_test_runner.py
    test_classifier.py
    test_classifier_cases.py
    test_pipeline.py
  examples/
    round1_off_by_one/       <- before.py, after.py, diff.patch
    round2_mutable_default/  <- before.py, after.py, diff.patch
    classifier_cases/        <- nine cases with known answers
  baselines/                 <- saved test files from a live run
  generated_tests/           <- written by the pipeline, not kept in git
  reports/                   <- written by the pipeline
  requirements.txt
  README.md
```

## Setting up

You need Python 3.10 or newer. The commands below are for Windows PowerShell.

```powershell
cd "$env:USERPROFILE\Desktop\capstone project\prsentinel"

# 1. Create the virtual environment (already done for you)
py -3.13 -m venv .venv

# 2. Turn the virtual environment on
.\.venv\Scripts\Activate.ps1

# 3. Install everything
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

If PowerShell blocks the activate script, run this once instead:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## API keys

The keys are **never** written into the code. They are read from environment
variables. Open PowerShell and set them for your user account:

```powershell
[Environment]::SetEnvironmentVariable("GROQ_API_KEY", "your-groq-key-here", "User")
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "your-gemini-key-here", "User")
```

Then close PowerShell and open it again so the new variables are picked up.

To check they arrived:

```powershell
.\.venv\Scripts\python.exe -c "import os; print('groq  :', bool(os.environ.get('GROQ_API_KEY'))); print('gemini:', bool(os.environ.get('GEMINI_API_KEY')))"
```

Which models we use is written in one place, at the top of `src/prsentinel/config.py`:

```python
GROQ_MODEL = "openai/gpt-oss-120b"   # tried first
GEMINI_MODEL = "gemini-3.5-flash"     # used only if Groq fails
```

Both model names were checked against the live APIs on 30 September 2026:
Groq answered, Gemini answered, and a deliberately broken Groq key correctly
fell through to Gemini.

## Running the tests

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

You should see 240 passing tests. None of them use the internet.

## Checking the real LLM providers

The one script that does use the internet:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_llm.py
```

It checks Groq on its own, Gemini on its own, and that a broken Groq key falls
through to Gemini. It reads your keys from the environment but never prints
them and never writes them anywhere.

**Do not run it more than a few times in a row.** The Gemini free tier allows
only **5 requests per minute** for `gemini-3.5-flash`. Go over that and Gemini
answers `429 RESOURCE_EXHAUSTED` and tells you how long to wait. You will also
occasionally see a `500 INTERNAL` from Gemini; that one is a server-side blip
and simply retrying works.

This matters for later steps: generating several tests for one change will use
several Gemini calls in a row, so PRSentinel will need to retry with a wait
before it can rely on the fallback.

## Using the diff extractor

```powershell
# Friendly output for people
.\.venv\Scripts\python.exe -m prsentinel.diff_extractor examples\round1_off_by_one\before.py examples\round1_off_by_one\after.py

# Machine-readable output
.\.venv\Scripts\python.exe -m prsentinel.diff_extractor examples\round2_mutable_default\before.py examples\round2_mutable_default\after.py --json
```

Each result is a dictionary like this:

```json
{
  "name": "get_recent_scores",
  "change_type": "modified",
  "old_code": "def get_recent_scores(scores, count):\n    ...",
  "new_code": "def get_recent_scores(scores, count):\n    ...",
  "old_start_line": 8,
  "old_end_line": 13,
  "new_start_line": 8,
  "new_end_line": 14
}
```

- `change_type` is one of `added`, `removed` or `modified`.
- A method inside a class is reported as `ClassName.method`.
- A function inside a function is reported as `outer.inner`.
- A function whose code did not actually change is left out of the results.

## The two examples

**In both folders `before.py` is the CORRECT version and `after.py` is the
BUGGY version.** That is deliberate: the "after" file is the bad code that
PRSentinel will later have to write a failing test for.

**Round 1 - off-by-one.** `before.py` gets it right by starting no earlier
than the start of the list:
```python
start = max(0, len(scores) - window)
return scores[start:]
```
`after.py` uses `scores[-window - 1:]`, which asks for one score from
`[10, 20, 30]` and gets `[20]` instead of `[30]`.

**Round 2 - mutable default argument.** `before.py` uses the correct pattern,
`cart=None` plus a new list made inside the function. `after.py` changes it to
`cart=[]` and drops the `None` check. Python builds that default list once and
shares it between calls, so items leak from one call into the next.

Each folder holds exactly one change. `average_score` and
`remove_item_from_cart` are identical in both files, so they are correctly not
reported.

## How "modified" is decided

PRSentinel compares the two functions with `ast.dump()`, which turns a function
into a text tree of its structure:

| Edit | Reported? |
|---|---|
| changed line of code | yes |
| changed default argument, e.g. `cart=None` to `cart=[]` | yes |
| changed docstring | yes |
| renamed parameter | yes |
| comment only | **no** |
| blank lines or spacing only | **no** |

Comments and spacing are not in the tree, so editing only those is not a
change worth testing.

## Talking to the LLM

```python
from prsentinel.llm_client import ask_llm

print(ask_llm("In one sentence, what is a mutable default argument?"))
```

It prints which provider answered. If Groq has no key, fails, or is rate
limited, it tries Gemini instead. If neither works it raises an error instead
of failing silently.

### How creative the AI is allowed to be

Writing tests uses a temperature, set in `config.py`:

```python
GENERATION_TEMPERATURE = _float_from_env("PRSENTINEL_TEMPERATURE", 0.0)
```

Zero is the most predictable setting, which is what we want when the job is to
write tests that agree with the code. To change it:

```powershell
[Environment]::SetEnvironmentVariable("PRSENTINEL_TEMPERATURE", "0", "User")
```

**This does not make the AI perfectly repeatable.** Even at zero, a hosted
model can answer slightly differently each time, so running the generator twice
can still produce two different test files. That is why `baselines/` holds a
saved copy and `--reuse-tests` exists.

The failure classifier **does not use this setting**. It keeps whatever
temperature the provider normally picks, so classifying is unaffected by it.

## Running the whole thing with one command

```powershell
.\.venv\Scripts\python.exe -m prsentinel.pipeline examples\round1_off_by_one\before.py examples\round1_off_by_one\after.py
```

That does seven steps in order:

1. find the functions that were added or changed (removed ones are skipped)
2. ask the AI for tests for each of them, saved into `generated_tests/<name>/`
3. run each test file against the old code and the new code, and label every test
4. for each test that fails on the new code, work out what the failure means
5. optionally, ask the AI for a second opinion and flag any disagreement
6. print a plain-language report
7. save the report to `reports/<name>.md` and `reports/<name>.json`

`--name NAME` changes the folder used under `generated_tests/` and `reports/`.
Without it, the folder the old file sits in is used, which is how the examples
are named.

The exit code is **0 whenever the pipeline ran**, even when it found bugs,
because finding bugs is the job. It is non-zero only if the pipeline itself
could not do its work, such as a file it cannot read.

One function failing to generate does not stop the others. The failure is
reported at the end.

### `--ai-second-opinion`

```powershell
.\.venv\Scripts\python.exe -m prsentinel.pipeline ... --ai-second-opinion
```

Also asks the AI what it thinks of each failing test, and marks any case where
it disagrees with the rule. Without this flag there are no extra AI calls at
all.

### `--reuse-tests`

```powershell
.\.venv\Scripts\python.exe -m prsentinel.pipeline ... --reuse-tests
```

Does **not** ask the AI for any new tests. It uses the test files already saved
in `generated_tests/<name>/`. With this flag the whole run makes no AI calls, so
the same tests can be run again and the results compared.

Every report says where its tests came from, on the line under the file names:

```
Tests: generated in generated_tests/round1_off_by_one/
```

### Keeping older copies

Writing a new test file over an old one keeps the old one. Nothing is ever
overwritten, so no run can destroy an earlier one:

```
test_get_recent_scores.py       <- the current one
test_get_recent_scores.py.bak   <- the one before it
test_get_recent_scores.py.bak.2 <- the one before that
test_get_recent_scores.py.bak.3
```

## What the labels and the verdicts mean

There are two different sets of words, and they answer two different questions.

**Labels** come from running the test both ways. They only describe the results:

| Label | Passed on old code | Passed on new code | Plain meaning |
|---|---|---|---|
| `CATCHES_CHANGE` | yes | no | the test agrees with the change, so it is worth keeping |
| `TEST_WRONG_ON_BEFORE` | no | no | the test fails even on code that was already correct, so the test is the problem |
| `NO_SIGNAL` | yes | yes | the test cannot tell the two versions apart, so it says nothing about the change |
| `ODD` | no | yes | only the new code satisfies it, so a person needs to look |

**Verdicts** come from the classifier. They only appear for tests that fail on
the new code, and they say what the failure *means*:

| Verdict | Plain meaning |
|---|---|
| `REAL_BUG` | the change broke something that used to work |
| `BAD_TEST` | the test itself is wrong, so its failure means nothing about the code |
| `FLAKY` | the test gives different answers on different runs, so one result cannot be trusted |
| `UNKNOWN` | we could not work it out; the reason is in the report |

The one-line summary at the end counts only tests that both caught the change
and were judged `REAL_BUG`. A test that was itself wrong is not evidence of a
bug, so it is left out.

## Running a failing test more than once

A test that fails once might fail every time, or it might fail now and then
depending on chance. Those need different verdicts, so the runner cannot trust
a single run. It runs the file again several times on the new code and counts
how many passed and how many failed.

How many reruns happens in `config.py`:

```python
RERUN_TIMES = _int_from_env("PRSENTINEL_RERUN_TIMES", 5)
```

A test that passed at least once and failed at least once is `FLAKY`. One that
failed every time is not.

## Readable test names

Pytest's own names get long and hard to read when a test is run many times with
different inputs, like `test_x[scores0-0-expected0]`. The runner gives each one
a short readable name for the table, while the full name is kept for the
report:

- a plain name, like `test_single`
- an input value in square brackets, like `test_single[0]`
- an empty input shown as `[<empty>]`
- a blank one shown as `[<blank>]`
- two tests that would print the same name get `#1` and `#2`

## How a failure is classified

`classifier.py` works in two stages.

First it **collects the evidence**: the old code, the new code, a line-by-line
difference between them, the test file, the failure message, whether the test
passed on each version, and how the reruns went.

Then it decides, in this order:

1. if the reruns gave a mix of passes and fails, it is `FLAKY`
2. otherwise, if the test failed on the old code too, it is `BAD_TEST`
3. otherwise, if it passed on the old code and fails on the new one, it is
   `REAL_BUG`

That plain rule is called `rule_classify`. It needs no API key and no internet,
and it scores 9 out of 9 on the cases below.

There is also `llm_classify`, which asks the AI instead. It can be given either
the whole picture (`"full"`) or only the code (`"code_only"`), so the two can be
compared. It asks for a plain JSON answer, and gives the model one retry if the
reply cannot be read.

## The nine answer-key cases

`examples/classifier_cases/` holds nine small cases where the right answer is
known. Each folder has `before.py`, `after.py`, `test_case.py` and
`expected.json`. There are three of each kind:

| Folder | Right answer |
|---|---|
| `real_bug_off_by_one` | `REAL_BUG` |
| `real_bug_wrong_divisor` | `REAL_BUG` |
| `real_bug_loop_skips_last` | `REAL_BUG` |
| `bad_test_invented_rule` | `BAD_TEST` |
| `bad_test_wrong_expected_value` | `BAD_TEST` |
| `bad_test_wrong_assumption` | `BAD_TEST` |
| `flaky_random_pick` | `FLAKY` |
| `flaky_current_time` | `FLAKY` |
| `flaky_set_order` | `FLAKY` |

The three flaky cases pass and fail depending on `PRSENTINEL_RUN_INDEX`, which
the runner sets to 1, 2, 3 and so on for each rerun. Even run numbers fail, odd
ones pass, so the same test gives different answers.

Score all three classifiers against the cases:

```powershell
.\.venv\Scripts\python.exe -m prsentinel.classifier_eval
```

This uses the internet, one model call at a time, so it takes a while. It
prints a table, an accuracy score, every wrong answer, and a check for anything
that gives the answer away.

**Only `classifier_eval.py` is allowed to read `expected.json`.** A test makes
sure of that, so the classifier itself can never see the answer it is being
graded against.

The results on 30 September 2026, all answers from Groq:

| Classifier | Score |
|---|---|
| `rule_classify` (no AI) | **9 / 9** |
| `llm_classify`, mode `full` | 7 / 9 |
| `llm_classify`, mode `code_only` | 6 / 9 |

The plain rule beat both versions of the AI. All four AI mistakes were flaky
cases judged `BAD_TEST`: neither AI could tell a test that depends on chance
apart from a test that is simply wrong. The prompt explains `FLAKY` by its
cause but never says the plain rule that the reruns already prove, which is
*if a test passed once and failed once, it is flaky*.

Do not tune the prompt against these nine cases and then report the improved
score as evidence. That is fitting to the test set, not improving the tool.
