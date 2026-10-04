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
  .github/workflows/
    prsentinel.yml      <- scores a pull request and leaves one comment
    tests.yml           <- the whole test suite, on Linux, with no secrets
  scripts/
    smoke_llm.py           <- checks the real providers (uses the internet)
    check_real_cases.py    <- checks examples/real_cases, no AI at all
    eval_real_cases.py     <- scores the pipeline on examples/real_cases
    baseline_single_prompt.py  <- one plain prompt per case, the cheapest baseline
    make_pr_comment.py     <- turns the reports into the pull request comment
  tests/
    test_diff_extractor.py
    test_llm_client.py   <- fake providers, never uses the internet
    test_test_generator.py
    test_test_runner.py
    test_classifier.py
    test_classifier_cases.py
    test_pipeline.py
    test_workflows.py    <- guards both workflow files, and the comment
  examples/
    round1_off_by_one/       <- before.py, after.py, diff.patch
    round2_mutable_default/  <- before.py, after.py, diff.patch
    real_cases/              <- three real BugsInPy bugs, evaluation only
    classifier_cases/        <- nine cases with known answers
  baselines/                 <- frozen test files, the reference for the paper
  baselines_single_prompt/   <- the baseline arm's five replies, saved
  generated_tests/           <- written by the pipeline, not kept in git
  reports/                   <- written by the pipeline
  reports/real_cases/        <- the three real-case evaluation reports, saved
  requirements.txt
  NOTES_COVERUP.md           <- why CoverUp is not the baseline, and what stopped it
  RESULTS.md                 <- every number this project produced, and where from
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

You should see 916 passing tests. None of them use the internet.

## Showing it to somebody

```powershell
.\scripts\run_demo.ps1
```

Then open <http://127.0.0.1:8000>. `.\scripts\run_demo.ps1 -Check` starts the app,
checks that it serves its page, prints the cases it offers and stops again.

The app is a thin wrapper. It copies the chosen case's saved test into the place
the pipeline looks for it, calls the real `run_pipeline`, and draws whatever
comes back. It decides nothing itself and reimplements nothing. It binds to
`127.0.0.1` only, so nothing on the network can reach it.

The first option on the page is **Saved tests**, which reuses a test file that
already exists and therefore needs no key and no AI. That is the mode to show,
because it works on a machine that has never had a key on it. `DEMO.md` has the
case-by-case walkthrough, including the honest odds of the flaky one.

### One warning you will see once, and can ignore

```
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is
deprecated; install `httpx2` instead.
```

starlette 1.7.0 prefers `httpx2` for its test client. The project pins
`httpx==0.28.1` instead, because that is the version that was installed and
actually run here. This test suite does not turn warnings into errors, so the
one line is harmless. Moving to `httpx2` would mean a different package and two
more dependencies, which is not worth it for a demo.

## Running on a pull request

Two workflows, in `.github/workflows/`. Neither of them has ever run yet, so
treat this section as a description of what was written rather than as a
record of what happened.

**`tests.yml`** runs the whole test suite on Linux on every push and every pull
request. It holds no secrets of any kind, which is why it also runs on pull
requests from forks.

**`prsentinel.yml`** scores a pull request and leaves one comment on it. It:

- scores only changed `.py` files, skips anything under `tests/`, and takes at
  most five of them so the cost of the shared key stays bounded. If it leaves
  any out, the comment says so and how many.
- takes the old code from the base commit and the new code from the head commit,
  the same direction a pull request reads in.
- asks Groq only. No second provider is configured, and fallback is switched
  off, so every number in the comment came from one model.
- runs the mutation check, because that is the number which says whether the new
  tests were any use.
- never repairs a test, never edits a file, and never writes to the pull request
  except one comment.
- if the daily allowance runs out, stops and says there is no result. That is
  not a pass, and the comment says so in those words.

The comment is built by `scripts/make_pr_comment.py`, which reads saved reports
and prints markdown. It asks the model nothing and reaches nothing. To see the
shape of it without running the workflow:

```powershell
.\.venv\Scripts\python.exe scripts\make_pr_comment.py --report reports\round1_off_by_one.json --repo owner/name --pr 12 --base-sha aaa --head-sha bbb
```

That report was saved before `--no-fallback` was the normal setting, so the
comment says so in a footnote rather than presenting the numbers as a
single-model result. A run made by the workflow will never have that note.

The comment always opens with one fixed sentence, held in a constant and checked
by a test:

> Tests are AI-generated. A catching test is a hint, not proof.

### The security note

**Only pull requests opened from a branch in this repository are scored.** A
pull request from a fork gets a comment saying it was skipped and why, and no
model is called.

That is not politeness, it is the whole safety argument. The job needs the Groq
key. GitHub does not give a workflow running on a fork the secrets of this
repository, so a fork's pull request cannot be scored. The workflow therefore
does not run on `pull_request_target` either, because that trigger *does* get
the secrets while checking out the pull request's code, which would let anybody
who can open a pull request have their code read by a job holding the key.

**The pull request's code goes into the prompt.** This is the honest cost of the
thing, and it is not hidden. For each changed function the old source and the
new source are sent to Groq so the model can write tests for them. Anything in
that code is sent off this machine. It is never printed, never logged, and never
written into the report, but it does leave the repository, and somebody
reviewing a pull request should know that before they open it.

The key itself is passed to exactly one step, the one that calls the model, and
is read from a repository secret. It is never echoed, never written to a file,
and never given to a step that runs somebody's other code. `tests/test_workflows.py`
checks all of that by reading the workflow file, and also checks that the
workflows never name the evaluation data, because a run that could reach the
real cases could be pointed at them and stop being an evaluation.

### What is not settled

The action versions are pinned to major tags (`actions/checkout@v4`,
`actions/setup-python@v5`, `actions/upload-artifact@v4`,
`actions/github-script@v7`). These were written from memory without checking
GitHub, so **none of them has been verified**. Pinning to a commit hash instead
would be better and needs a network call this project has not made.

This is also the first time the suite and the pipeline have run on Linux. The
known risks are listed at the top of `prsentinel.yml`; nothing has been changed
to work around them, because changing the pipeline to suit the runner would
change the thing being measured.

## Checking the real LLM providers

The one script that does use the internet:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_llm.py
```

It checks Groq on its own, Gemini on its own, and that a broken Groq key falls
through to Gemini. It reads your keys from the environment but never prints
them and never writes them anywhere.

## Checking the real bug cases

The other script, which uses no AI at all:

```powershell
.\.venv\Scripts\python.exe scripts\check_real_cases.py
```

It goes through each folder in `examples/real_cases`, runs that project's own
test through `prsentinel.test_runner` against both versions, and runs the
witness in `witness.md` against both. If a witness gives the same answer on both
versions the case is rejected, because that means the bug does not reproduce on
the Python you are on. It exits 1 if any case is rejected.

Nothing in `src/prsentinel` reads `examples/real_cases`. Those cases are for
evaluation only, so the pipeline cannot be pointed at them.
`tests/test_real_cases.py` fails if anything in the package so much as names the
folder.

**Do not run it more than a few times in a row.** The Gemini free tier allows
only **5 requests per minute** for `gemini-3.5-flash`. Go over that and Gemini
answers `429 RESOURCE_EXHAUSTED` and tells you how long to wait. You will also
occasionally see a `500 INTERNAL` from Gemini; that one is a server-side blip
and simply retrying works.

This matters for later steps: generating several tests for one change will use
several Gemini calls in a row, so PRSentinel will need to retry with a wait
before it can rely on the fallback.

## Scoring the real bug cases

`examples/real_cases/` holds three real bugs taken from
[BugsInPy](https://github.com/soarsmu/bugsinpy). `scripts/check_real_cases.py`
above only proves each one still reproduces. `scripts/eval_real_cases.py` is
what runs PRSentinel over them and scores the result:

```powershell
.\.venv\Scripts\python.exe -u scripts\eval_real_cases.py
```

It has no flags on purpose. `--no-fallback` and `--mutation` are fixed inside
it, so it cannot be run in a configuration that makes the number flattering. It
calls the same `run_pipeline` the CLI calls, and writes one `.md` and one
`.json` report per case into `reports/real_cases/`.

The generator is only ever handed `before.py` and `after.py`.
`existing_test.py`, `witness.md` and `source.md` are never passed to the
pipeline; `existing_test.py` is read once per case, after that case's run has
finished, purely to print a comparison number. `tests/test_real_cases.py` checks
that three separate ways.

### The result

Run on 2026-10-02, Groq (`openai/gpt-oss-120b`) only, `answers from Gemini: 0`
in all three reports:

| Case | Project | Function | Tests | Caught the bug | Mutation |
|---|---|---|---|---|---|
| bug 43 | youtube-dl | `url_basename` | 24 | **yes** - 5 of them, all judged `REAL_BUG` | 100%, 3 of 3 mutants killed |
| bug 3 | youtube-dl | `unescapeHTML` | 19 | no | not defined |
| bug 3 | PySnooper | `get_write_function` | 4 | no | not defined |

**At least one generated test caught the bug in 1 of 3 cases.**

"Caught the bug" means the runner's own `CATCHES_CHANGE` label: the test passes
on `before.py` and fails on `after.py`. 47 test items were generated in total.

Where the two misses go wrong is worth reading in the reports rather than
skipping: for youtube-dl bug 3, three tests failed on `before.py` as well, so
they were judged `BAD_TEST`, and the other sixteen passed on both versions
(`NO_SIGNAL`). For PySnooper bug 3, one test *fails on the old code and passes on
the new one* - it encoded the buggy behaviour as the expected behaviour. The
mutation score could only be computed for bug 43; for the other two the report
says why: the tests already fail on the un-mutated code, so there is no green
starting point to measure from.

### What this result does not say

- **The "pull request" is a fix run backwards.** `before.py` is the commit that
  *fixed* the bug and `after.py` is the commit that *had* it, so the diff reads
  in the opposite direction to a real PR. Nobody in the project ever wrote this
  change; it was reconstructed from history.
- **Both projects are public and BugsInPy is public.** The models may have seen
  these fixes and these functions in training data. If anything this would
  inflate the result, not deflate it.
- **The bugs target Python 3.7 and 3.8; the run was on 3.13.9.** The check
  script above rejected two of the three witness inputs for exactly this reason
  before any of this was measured. Three cases on one interpreter is not a
  rate, it is three observations.
- **Evaluation only.** No prompt, no operator and no threshold was changed after
  seeing these numbers, and nothing in `src/prsentinel` can read this folder.
  `tests/test_real_cases.py` fails if it so much as names it.

## The cheapest baseline: one plain prompt per case

The three cases above cannot say how much of PRSentinel's result is the model and
how much is the machinery around it. `scripts/baseline_single_prompt.py` asks
that with the smallest thing that can go on the other side of the comparison:

```powershell
.\.venv\Scripts\python.exe -u scripts\baseline_single_prompt.py
```

**One call to the same model.** The same `before.py`, the same `after.py`, and
the same one changed function's old and new source. No pipeline, no mutation, no
rerun loop, no judge, no repair. One prompt, one reply, and then the reply is
run through `test_runner` and scored with the runner's own labels, so "caught the
bug" means exactly one thing on both sides of the table.

It has no command line, for the same reason `eval_real_cases.py` has none. The
prompt was frozen on 2026-10-02 **before** the run, and `tests/test_real_cases.py`
holds its exact text character for character, so it cannot be improved once the
numbers are known. It is a plain task with no advice in it: no edge cases, no
"look for anything the change could have made worse". The pipeline prompt has all
of that, and that difference is part of what is being compared rather than an
oversight.

It ran on 2026-10-02, Groq (`openai/gpt-oss-120b`) only. Five calls, one per
case. All five replies are saved in `baselines_single_prompt/`.

### Both arms, side by side

| Case | Project | Function | Plain prompt | PRSentinel | Project's own test |
|---|---|---|---|---|---|
| bug 43 | youtube-dl | `url_basename` | **caught** - 5 of 24 | **caught** - 5 of 24 | caught |
| bug 3 | youtube-dl | `unescapeHTML` | missed - 0 of 15 | missed - 0 of 19 | caught |
| bug 3 | PySnooper | `get_write_function` | **caught** - 1 of 3 | missed - 0 of 4 | caught |

| | Caught the bug |
|---|---|
| **One plain prompt** | **2 of 3** |
| **PRSentinel** | **1 of 3** |
| The project's own test | **3 of 3** |

Three observations, not a rate. But the ordering is the finding, and it does not
flatter this project:

- **The project's own test caught all three bugs.** That is what a human wrote,
  and it is the bar. PRSentinel is not close to it on three real bugs.
- **One plain prompt beat PRSentinel, 2 of 3 to 1 of 3.** On PySnooper bug 3 the
  plain prompt wrote a test that caught the bug and PRSentinel's four did not;
  on youtube-dl bug 3 both wrote tests that all passed on both versions.
- On youtube-dl bug 43 both arms produced 24 test items and 5 catching tests.
  **That is a coincidence, not a shared file**: the two replies are different
  files of different lengths (2875 and 1727 bytes) and neither was copied from the
  other. The same counts coming out of two different prompts on one case should
  not be read as agreement between the arms.

The one place the two arms genuinely agree is youtube-dl bug 3, where both
missed: the plain prompt wrote 15 tests that all passed on both versions, and
PRSentinel wrote 19 that were 16 `NO_SIGNAL` and 3 that failed on `before.py` too.

### Where the baseline's numbers come from

The baseline script saved its five replies but not a report, so the table above
was re-scored from those saved files with the same `test_runner.evaluate_tests`
the live run used. That is deterministic pytest, not a model call, so it costs
nothing and reproduces exactly. There is no command to show for it here: the
script itself refuses to run twice, on purpose, because a saved reply is the only
record of one live run. `RESULTS.md` records the same numbers and where each one
came from.

### A footnote on the two synthetic rows

The baseline also ran on the two synthetic rounds, and those two rows are **not**
like for like. PRSentinel's side of them was scored on frozen hand-checked tests
saved in `baselines/` in an earlier step, not on a fresh generation, while the
baseline's side is a fresh call on all five cases. The script prints a `tests
from` column for exactly this reason, and the two reports say
`tests_source: reused from baselines`. They are not evidence that PRSentinel's
generator beats one plain call.

`NOTES_COVERUP.md` records why the more obvious baseline, CoverUp, could not be
run on this machine at all, and why it would not have been a fair comparison
even if it had: it is coverage-driven and PRSentinel is change-driven.

### What the baseline result does not say

- **It is not an evaluation in the strict sense.** It was written *after* the
  real-case numbers were known. The real cases were protected from exactly that,
  and the baseline arm was not. A baseline written without seeing the results it
  is compared against is worth more than this one, and this one was not written
  that way. Say so in the paper.
- **Three cases.** As above.
- **Five calls, one per case, is the cheapest possible comparison, not the
  strongest.** A baseline with a second call, or a self-check, or two prompts
  averaged, would be a fairer opponent and would probably score higher.

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
in `generated_tests/<name>/`, and falls back to the frozen copy in
`baselines/<name>/` for any function that has no live file. That fallback is why
this still works on a fresh clone, where `generated_tests/` does not exist.
With this flag the whole run makes no AI calls, so the same tests can be run
again and the results compared.

`baselines/` holds the frozen reference for the results in the paper. It is the
fixed set of tests the numbers were measured against, kept unchanged so they can
be reproduced exactly. `generated_tests/` is the moving part: it holds whatever
the most recent run wrote, and changes every run.

Every report says where its tests came from, on the line under the file names:

```
Tests: generated
Tests: reused from generated_tests
Tests: reused from baselines
Tests: reused from generated_tests and baselines   <- a run that needed both
```

Each function's lines also name the folder that one file came from, so a mixed
run can be read properly:

```
add_item_to_cart  (added)
  test file: test_add_item_to_cart.py
  came from: baselines
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
