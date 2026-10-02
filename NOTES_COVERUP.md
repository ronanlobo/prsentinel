# CoverUp: tried on this machine, and dropped

Written 2026-10-02. This is the record of one attempt, so the decision not to
use CoverUp rests on something measured rather than on a guess about it.

**The short answer: CoverUp installs on this machine and cannot run on it.** The
blocker has nothing to do with Python 3.13 and nothing to do with the model. It
is a Unix-only dependency that pytest loads automatically.

## What CoverUp is

CoverUp 0.6.3, from PyPI. Its own summary is "LLM-powered test coverage
improver". Written by Juan Altmayer Pizzorno and Emery Berger (the PLASMA lab at
UMass Amherst), Apache 2.0, repository `plasma-umass/coverup`. It writes pytest
tests for the parts of your code that existing tests do not reach, aiming at a
coverage target.

## What was tried

A throwaway virtual environment in a temporary folder, made from this machine's
Python 3.13.9, plus a small five-function sample package and a test that covered
one of them. No API key was set for any provider and no model was called. The
folder and the virtual environment were deleted afterwards.

The machine has three interpreters, worth knowing before reading on:
`py -0p` lists 3.14.3 (which is what `python` on PATH resolves to), 3.13.9 at
`D:\Anaconda\python.exe`, and 3.10.

## What happened

| Step | Result |
|---|---|
| `pip install CoverUp==0.6.3` on Python 3.13.9, Windows | **Worked.** Exit 0. 74 packages, all `win_amd64` or `py3-none-any` wheels, nothing compiled. |
| `coverup --version` | `CoverUp v0.6.3 (Python 3.13.9)`, exit 0. |
| `coverup --help` | The full command line renders. |
| `coverup --dry-run` on the sample package | **Failed.** `ModuleNotFoundError: No module named 'fcntl'`. |

## Why it fails

`pytest-isolate`, a required dependency, is Unix-only. Its `plugin.py` reads:

```python
import fcntl    # line 8
import resource # line 10
```

Neither module exists on Windows. There is no conditional import and no platform
check: a search of that package for `win32`, `platform.system` and `sys.platform`
found **zero** matches across all five of its modules.

Two things make this unavoidable rather than configurable:

1. `pytest-isolate` registers a `[pytest11]` entry point, so **pytest loads it in
   every run automatically**. No CoverUp flag can keep it out. `--no-isolate-tests`
   was tried on the off chance that it would, and produced the identical
   traceback.
2. It is an unconditional `Requires-Dist` of CoverUp, alongside `asyncio`,
   `openai`, `tiktoken`, `aiolimiter`, `tqdm`, `slipcover>=1.0.13`,
   `pytest-cleanslate>=1.0.6`, `pytest-repeat` and `litellm>=1.33.1`.

The metadata agrees. CoverUp's classifiers list `Operating System :: MacOS ::
MacOS X` and `Operating System :: POSIX :: Linux`. There is no Windows classifier.

The failure lands on the very first thing CoverUp does, which is measure
coverage with slipcover. It happens before any model is asked, so no setting
avoids it.

## Two things that looked like problems and were not

**The `asyncio` dependency.** CoverUp requires the PyPI package called `asyncio`,
which was for years a backport that shadowed the standard library `asyncio` and
broke modern Python. That is no longer true: the installed 4.0.0 is a
metadata-only stub. Its `RECORD` contains no Python modules at all, only
`.dist-info` entries, and it describes itself as "Deprecated backport of asyncio;
use the stdlib package instead". `import asyncio` resolved to the standard
library. Harmless.

**Running without a key.** CoverUp has a `--dry-run` that prompts no model, and
an `--ollama-api-base` for a model on your own machine, so a fully local run is
possible in principle. Both are real. Neither helps here, because the run dies
before reaching a model. Worth recording anyway: `--dry-run` still refuses to
start unless a key variable is merely *set*, which is a small thing to trip over.

## Why it is dropped

Not fixable from here. Running CoverUp would need WSL, a Linux container, or a
Linux CI runner, and none of those are in scope.

There is a second reason to record, which is about the comparison rather than the
installation. **CoverUp and PRSentinel are not solving the same problem.**
CoverUp is coverage-driven: it raises line coverage of a suite you already have.
PRSentinel is change-driven: it tries to catch one specific regression. Running
CoverUp on the three real cases would not have produced a head-to-head number, it
would have produced a different measurement wearing the same clothes.

So the honest baseline in this project is the single-prompt one in
`scripts/baseline_single_prompt.py`: one plain call, the same model, the same
before and after files, the same scorer.

## One bit of housekeeping

CoverUp writes a log file called `coverup-log` into whatever directory it is run
from. The probe left one in this project's root. It was checked, confirmed to be
the probe's own output and untracked, and deleted.