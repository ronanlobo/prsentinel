# PRSentinel

PRSentinel is an AI tool that looks at a code change (a "diff") in a Python
project, works out which functions changed, and later on generates tests for
that change. It will then look at a failing test and decide whether the failure
is a real bug, a bad test, or a flaky test.

## Where the project is right now

This is **Step 1**. Only these parts are built so far:

- the project skeleton
- `config.py` - the settings, including the API keys read from the environment
- `llm_client.py` - `ask_llm(prompt)`, which tries Groq and falls back to Gemini
- `diff_extractor.py` - finds which functions were added, removed or modified
- tests, plus two small worked examples

Still to build: test generation, running the generated tests, working out if a
failure is a real bug / bad test / flaky test, mutation testing, Docker,
FastAPI, a database and a web interface.

## Folder layout

```
prsentinel/
  src/prsentinel/
    __init__.py
    config.py            <- settings live here, nowhere else
    llm_client.py        <- ask_llm()
    diff_extractor.py    <- which functions changed
  scripts/
    smoke_llm.py         <- checks the real providers (uses the internet)
  tests/
    test_diff_extractor.py
    test_llm_client.py   <- fake providers, never uses the internet
  examples/
    round1_off_by_one/       <- before.py, after.py, diff.patch
    round2_mutable_default/  <- before.py, after.py, diff.patch
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

You should see 27 passing tests. None of them use the internet.

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
