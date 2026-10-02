# How to measure v2 against v1

This is the plan for comparing `llm_full` (v1) with `llm_full_v2` (v2) on the
tuning set. It is written down here to be followed. Nothing has been run yet.

**`heldback_eval` is not part of this plan and must not be run.** The cases in
`examples/classifier_cases_heldback/` are kept back for one reason: so that the
prompt is never tuned against them. Every command below uses the tuning set in
`examples/classifier_cases/` only.

---

## The three runs

Each command is run **on its own**, one per session, in this order. One command
per session is not a preference, it is the point. A run that is interrupted
half way costs less to abandon and restart than to finish.

Before each run, load the keys into the session (this reads them without ever
printing one):

```powershell
foreach ($name in @("GROQ_API_KEY","GEMINI_API_KEY")) {
  $v = [Environment]::GetEnvironmentVariable($name,"User")
  if ($v) { Set-Item -Path "Env:$name" -Value $v }
}
```

### Run 1

```powershell
& ".venv\Scripts\python.exe" -u -m prsentinel.classifier_eval --repeats 1 --only rule,llm_full,llm_full_v2 --no-fallback
```

### Run 2

```powershell
& ".venv\Scripts\python.exe" -u -m prsentinel.classifier_eval --repeats 1 --only rule,llm_full,llm_full_v2 --no-fallback
```

### Run 3

```powershell
& ".venv\Scripts\python.exe" -u -m prsentinel.classifier_eval --repeats 1 --only rule,llm_full,llm_full_v2 --no-fallback
```

### What each flag is for

| Flag | Why it is there |
|---|---|
| `-u` | Without it Python buffers the output and you see nothing for minutes. With it, progress appears as it happens. |
| `--repeats 1` | One run per command, so all three land in three separate sessions. |
| `--only rule,llm_full,llm_full_v2` | Only the two being compared, plus the rule baseline. `llm_full_with_intent` and `llm_code_only` cost calls and tell us nothing about v1 against v2. |
| `--no-fallback` | If Groq runs out for the day the whole run stops and says so, instead of quietly answering the rest from Gemini. A score made from two models is not a score. |

---

## Before trusting a run

Check all three of these. A run that fails any one of them is thrown away and
started again, not patched up.

1. **Groq only.** At the bottom of the report, under
   `=== Where the answers came from ===`, the Groq column must hold 14 for both
   `llm_full` and `llm_full_v2`, and the Gemini column must be `0`.
2. **No warning banner.** The line `SOME ANSWERS CAME FROM GEMINI` must not
   appear anywhere in the output.
3. **No early stop.** The line `THE RUN STOPPED EARLY` must not appear, and the
   run must end with the `llm_full_v2: cases it got wrong` summary.

If the daily limit is hit, the run stops on purpose and prints
`Model calls completed before the stop: N`. There is no accuracy in that output
and none should be written down. Wait for the allowance to reset.

---

## Writing the scores into PROMPT_LOG.md

By hand, after each run, so that a number in that file is always one somebody
actually read off a report.

1. Open `PROMPT_LOG.md` and find the version being measured (`llm_full` under
   v1, `llm_full_v2` under v2).
2. Fill in the line `- **Tuning scores:**` with that run's numbers, and
   `- **Measured during:**` with that run's date.
3. Leave the mean until all three runs are in. Then add the mean of the three.

Example of a finished v2 entry:

```markdown
### v2 - `llm_full_v2`

- **Date measured:** 2026-10-01
- **Tuning scores:** 13/14, 13/14, 12/14
- **Mean:** 12.67/14 = 90%
- **Measured during:** 3 separate single runs on 2026-10-01, Groq only, no
  fallback used.
- **Note:** tuned on the tuning set only.
```

If the three runs disagree, write all three down. Do not average first and
report one number, and do not keep only the best one. A single run of a 14-case
answer key is a sample, and the three runs together are the only reason we have
a number worth writing down at all.

---

## What it should cost

The daily allowance is **200,000 tokens**. Here is what one run spends, worked
out from the actual prompts on this case set.

One run asks 14 cases × 2 AI classifiers = **28 model calls**. The rule
classifier asks nobody, so it costs nothing.

| | Prompt size | Rough tokens (chars ÷ 4) |
|---|---|---|
| `llm_full`, all 14 cases | 32,923 chars | ~8,230 |
| `llm_full_v2`, all 14 cases | 42,639 chars | ~10,660 |
| Replies, 28 of them | ~90 tokens each | ~2,520 |
| **One run** | | **~21,400** |

| | Tokens | Share of the daily limit |
|---|---|---|
| One run | ~21,400 | 11% |
| **All three runs** | **~64,200** | **32%** |
| Left over | ~135,800 | 68% |

That fits comfortably, with room for the retry path. When a reply cannot be read,
`llm_classify` sends it again with a 251-character nudge, which adds about 65
tokens to that call. Even if one call in ten needed a second try, that is under
200 extra tokens per run.

**The reruns cost no tokens.** Each case's test is rerun 12 times by pytest
(`RERUN_TIMES = 12`) to check whether it is flaky, but that is local Python. It
takes wall-clock time, not allowance, which is why a run takes minutes rather
than seconds.

---

## One live run of the repair loop (written down, not run yet)

The runs above measure the classifier. This is different: one live run of the
whole pipeline with the repair loop on, just to see that path work end to end.
**It has not been run.**

```powershell
& ".venv\Scripts\python.exe" -u -m prsentinel.pipeline examples\round2_mutable_default\before.py examples\round2_mutable_default\after.py --repair --no-fallback
```

- It uses **fresh generated tests**. `--reuse-tests` is not given, so the writer
  makes new tests and the run does not depend on anything saved earlier.
- The report must show a `--- Repairs ---` section. With `--repair` given, the
  section is printed even when nothing needed repair, so its absence means the
  run never reached the repair step.
- **Groq only, no fallback.** `--no-fallback` is given, so if Groq runs out for
  the day the whole run stops and says so instead of quietly answering the rest
  from Gemini. Start a fresh session and load only the Groq key (leave
  `GEMINI_API_KEY` unloaded) as well, so there is no second model to mix in:

  ```powershell
  $v = [Environment]::GetEnvironmentVariable("GROQ_API_KEY","User")
  if ($v) { Set-Item -Path "Env:GROQ_API_KEY" -Value $v }
  ```

  Before trusting the output, check that every `[prsentinel] answer came from
  Groq` line is Groq. One `answer came from Gemini` line means two models were
  mixed and the run is thrown away.

This is a separate one-off. It does not touch `examples/classifier_cases/`,
`examples/classifier_cases_heldback/`, `PROMPT_LOG.md`, or `heldback_runs.log`.

---

## The real bug cases (written down, not run yet)

Everything above scores the classifier on cases we wrote ourselves. This runs
the whole pipeline over the three real bugs in `examples/real_cases/`, where the
right answer is known because the project's own history says so.

**It has not been run.** The script exists and its offline tests pass. Nothing
has been tuned since those three cases were chosen, and nothing may be tuned
after this run finishes.

### The command

```powershell
& ".venv\Scripts\python.exe" -u scripts\eval_real_cases.py
```

There are no flags, on purpose. The two settings that make a result mean
anything are fixed inside the script and cannot be left off by accident:

| Setting | Why it is fixed |
|---|---|
| `--no-fallback` | If Groq runs out for the day the whole evaluation stops, prints the cases that finished, prints **no table**, and exits 6. A result made from part Groq and part Gemini is not a result. |
| `--mutation` | Each changed function is also checked against small deliberate faults to see how many the tests catch. Asks no AI. The score lands in the report and in the final table. |

The script never asks for, reads, prints or writes an API key. It runs the same
`run_pipeline` function `python -m prsentinel.pipeline` runs, and it hands that
function one before file and one after file. The generator never sees
`existing_test.py`, `witness.md` or `source.md`; `tests/test_real_cases.py`
checks that three separate ways.

### What it writes

The pipeline saves `reports/<case>.md` and `reports/<case>.json` as usual. The
script then moves both into `reports/real_cases/`. It never overwrites: if a
report is already there it refuses, moves nothing, and exits 2. A second live
run therefore needs the first run's reports moved or deleted first.

Those reports get their own commit, after the numbers have been read. They are
not part of the commit that adds the script.

### What it costs

Each case has one changed function, so each case asks the model once to write
tests. Three cases, three calls, plus a possible extra call when a reply cannot
be read and has to be asked for again. Nothing else asks anything: the plain rule
classifier, the mutation measurement and the project's own test are all local
Python.

### Groq only, no fallback

`--no-fallback` is given, so start a fresh session and load **only** the Groq
key. Leave `GEMINI_API_KEY` unloaded, so there is no second model to mix in:

```powershell
$v = [Environment]::GetEnvironmentVariable("GROQ_API_KEY","User")
if ($v) { Set-Item -Path "Env:GROQ_API_KEY" -Value $v }
```

### Before trusting the real-case run

Check all four. A run that fails any one of them is thrown away, not patched
up, and nothing from it is written down.

1. **Exit code 0.** `$LASTEXITCODE` must be `0`. `6` means a provider ran out
   and there is no table at all; `2` means a report was already there and
   nothing was overwritten; `1` means the script broke.
2. **Groq only.** Each of the three `.md` reports must say `fallback: off` and
   `answers from Gemini: 0`, under the header at the top of the report. The
   console also ends with `answers from Gemini across every case: 0`, with no
   `must be 0` warning next to it.
3. **No warning banner.** The line `AN ANSWER CAME FROM GEMINI` must not appear
   anywhere in the output.
4. **No early stop.** Neither `THE RUN STOPPED EARLY` nor `THE EVALUATION
   STOPPED EARLY` may appear. If either does, the cases that did finish were
   never scored and the table was deliberately not printed.

### Reading the output

Per case, one line:

```
  real_youtube-dl_bug43  funcs 1 (mod 1 add 0 rem 0)  tests 6  CATCHES_CHANGE 3 of which REAL_BUG 2  catches: yes  project test: CATCHES_CHANGE
```

- `funcs` is what `diff_extractor` found, with how many were modified, added or
  removed. A removed function is never given tests.
- `tests` counts pytest test items: one per test function, **plus one per
  parametrized case**. A parametrized test with five cases counts as five. It is
  not a count of files.
- `CATCHES_CHANGE` is how many of those pass on `before.py` and fail on
  `after.py`.
- `REAL_BUG` is how many of *those* were also judged to be pointing at a real
  bug, by the plain rule classifier. It is counted out of the catching tests,
  never out of all tests, so it can never exceed `CATCHES_CHANGE`.
- `catches` is `yes` when `CATCHES_CHANGE` is 1 or more. One test is enough.
- `project test` is the project's own test, run the same way, so the generated
  tests have something to be compared against. It is read after each run
  finishes, never before.

A case that finished but produced no tests prints `STOPPED` and **no numbers**.
A zero would read as "the model looked and found nothing", which is a different
claim from "there was nothing to look at".

The last three lines of a clean run are the headline and the two checks that
go with it:

```
  at least one generated test caught the bug in 3 of 3 cases
  answers from Gemini across every case: 0
  a report for each case is in reports/real_cases/
```

Whatever the first number turns out to be, it is written down as it comes out.
