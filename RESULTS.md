# RESULTS

Every number PRSentinel has produced, one table per experiment, with the file it
came from and the caveats that go with it.

**The rule for this file: no number here is typed from memory.** Each table names
the saved file or committed log it was read out of. Where a figure had to be
recomputed rather than copied, the table says so, because a number nobody can
reproduce is not evidence.

Read this file alongside `PROMPT_LOG.md` (how the two classifier prompts were
compared), `SPLIT.md` (why there are two case sets), `RUN_PLAN.md` (how to repeat
a run) and `NOTES_COVERUP.md` (why CoverUp is not the baseline).

---

## 1. The answer-key set (the tuning set)

`examples/classifier_cases/`, where the right answer is known.

**Where this comes from:** `README.md` lines 637-641 for the nine-case figures,
`PROMPT_LOG.md` for the fourteen-case figures. The case split is in `SPLIT.md`.

| Classifier | Nine cases, 2026-09-30 | Fourteen cases, 2026-09-30 and 2026-10-01 |
|---|---|---|
| `rule_classify` (no AI) | **9 / 9** | **not recorded** |
| `llm_full` (v1) | 7 / 9 | **12 / 14**, twice |
| `llm_full_v2` (v2) | not run then | **13 / 14**, twice |
| `llm_code_only` | 6 / 9 | not scored |

The fourteen-case set is 5 `REAL_BUG`, 5 `BAD_TEST` and 4 `FLAKY`, 12 reruns each.
The held-back set is 4 cases: 1 `REAL_BUG`, 1 `BAD_TEST`, 2 `FLAKY`.

**Caveats**

- **This is the set the tool was developed on.** Every prompt, operator and
  threshold in this project was chosen by looking at these cases. The scores are
  a measure of fitting, not of generalisation. The held-back table below is the
  one worth believing.
- **`rule_classify` was never scored on the fourteen-case set.** The 9/9 is from
  the nine cases that existed on 30 September. It is not comparable to the 12/14
  and 13/14 beside it. Do not put them in one column and call it a trend.
- **The plain rule beat the AI on the nine cases**, 9/9 to 7/9, and all four AI
  errors were flaky cases judged `BAD_TEST`.
- **v2's one-case lead is not real.** The case v2 got right and v1 got wrong was
  different in each of the two runs, and with 14 cases one case is 7 points. Only
  two runs were done. `PROMPT_LOG.md` says this at length and is right to.
- **`flaky_random_pick` is wrong in both versions, in both runs.** It is the one
  case neither prompt solves.
- **Contamination inside the set.** The three old flaky cases carry a
  `PRSENTINEL_RUN_INDEX` giveaway. Some AI reasons mention it, so part of what
  these scores measure is the model noticing a name.

---

## 2. The held-back set

`examples/classifier_cases_heldback/`, 4 cases. Scored **once**, by one command,
`python -m prsentinel.heldback_eval`.

**Where this comes from:** `heldback_runs.log`, which holds a single line, and
`PROMPT_LOG.md` under "Held-back result".

```
2026-10-01 06:57:14 UTC  valid  cases=4  rule=2/4  llm_full=3/4  llm_full_v2=2/4
```

| Classifier | Held-back | Tuning set, for contrast |
|---|---|---|
| `rule_classify` (no AI) | 2 / 4 | not recorded |
| `llm_full` (v1) | **3 / 4** | 12 / 14 |
| `llm_full_v2` (v2) | 2 / 4 | 13 / 14 |

**Caveats**

- **This is the only number in the project that was never tuned against.** It was
  run once, on 2026-10-01, 8 of 8 answers from Groq, none from Gemini.
- **v2 lost to v1 here**, 2/4 against 3/4, having won 13/14 against 12/14 on the
  tuning set. With 4 cases each worth 25 points, and answers that vary between
  runs, this is within noise. **Conclusion: v2 shows no reliable improvement over
  v1.** v1 is the default everywhere else in this project.
- **Nothing else was scored here.** `llm_full_with_intent` and `llm_code_only`
  were left out on purpose; the held-back run is not a tuning surface.
- **4 cases is 4 observations.** The log holds one line because there was one run.
  That is the point of the log.
- **The log is not in git.** `heldback_runs.log` is ignored, so it is not part of
  this file's history either.

---

## 3. Mutation testing

Does the generated test suite actually detect deliberate faults? Each changed
function is mutated and the mutants are run against the tests that were generated
for it. Score is `killed / (killed + survived)`; a mutant that imports but fails a
test counts as killed. `identical`, `timed out` and `could not run` mutants are
excluded from the score but counted.

**Where this comes from:** the `mutation` array in each of the five saved reports
under `reports/`.

| Case | Function | Mutants found | Killed | Survived | Score |
|---|---|---|---|---|---|
| `round1_off_by_one` | `get_recent_scores` | 3 | 3 | 0 | **1.0** |
| `round2_mutable_default` | `add_item_to_cart` | 3 | 3 | 0 | **1.0** |
| `real_youtube-dl_bug43` | `url_basename` | 3 | 3 | 0 | **1.0** |
| `real_youtube-dl_bug3` | `unescapeHTML` | 4 | 0 | 0 | not defined |
| `real_PySnooper_bug3` | `get_write_function` | 2 | 0 | 0 | not defined |

**Caveats**

- **The two "not defined" rows are not zeroes.** Both reports say why, in the same
  words: *the tests already fail on the un-mutated code, so there is no green
  starting point to measure from.* A test suite that cannot go green is a worse
  problem than one that survives a mutant, and the mutation score is the wrong
  instrument for it.
- **Five functions, three of them defined.** Three 1.0s out of three measurable
  cases is not a mutation score for this project. Two of the three measurable
  cases are the two synthetic ones.
- **`real_youtube-dl_bug43` is the only real bug with a defined score**, and it is
  the only real bug PRSentinel caught at all. The one row where the tests are both
  green and strong is the one row where they also found something.
- **The cap was 30 per function and was never reached.** Found counts are 2, 3, 3,
  3 and 4. Nothing here is a truncated measurement.
- **Only `before.py` was mutated.** That is the version the tests are supposed to
  pass, which is where "killed" is meaningful.

---

## 4. Repair, end to end

**There is no live repair run in this project.** Every one of the five saved
reports records `repair: false` and an empty `repairs` list. There is no number to
report from a real run, and this section deliberately has no headline.

**Where this comes from:** the `repair` and `repairs` fields in all five reports
under `reports/`.

| Case | `--repair` passed | Repairs recorded |
|---|---|---|
| `round1_off_by_one` | no | 0 |
| `round2_mutable_default` | no | 0 |
| `real_youtube-dl_bug43` | no | 0 |
| `real_youtube-dl_bug3` | no | 0 |
| `real_PySnooper_bug3` | no | 0 |

What exists instead is the test suite:

| Evidence | Number |
|---|---|
| Tests matching `repair` | 58, all passing |
| Whole suite | 789, all passing |

**Caveats**

- **Passing tests are not a measurement of repair quality.** They show the
  mechanism accepts a repair, refuses `--repair` together with `--reuse-tests`,
  and does not weaken a test to make a repair fit. They do not show that a repair
  found a real bug on real code.
- **`--repair` is off by default and was never run live.** If the paper claims
  repair works, it is claiming a test suite, not a result. Run it before claiming
  it, or say plainly that this is unmeasured.

---

## 5. The real bug cases

Three real bugs from [BugsInPy](https://github.com/soarsmu/bugsinpy), scored
2026-10-02, Groq (`openai/gpt-oss-120b`) only, `answers from Gemini: 0` in all
three reports.

**Where this comes from:** `reports/real_cases/*.json`, one per case.

| Case | Project | Function | Tests | `CATCHES_CHANGE` | `TEST_WRONG_ON_BEFORE` | `NO_SIGNAL` | `ODD` | Judged | Caught |
|---|---|---|---|---|---|---|---|---|---|
| bug 43 | youtube-dl | `url_basename` | 24 | **5** | 0 | 19 | 0 | 5 `REAL_BUG` | **yes** |
| bug 3 | youtube-dl | `unescapeHTML` | 19 | 0 | 3 | 16 | 0 | 3 `BAD_TEST` | no |
| bug 3 | PySnooper | `get_write_function` | 4 | 0 | 0 | 3 | 1 | none judged | no |
| | | **47** | **5** | **3** | **38** | **1** | | **1 of 3** |

**"Caught the bug"** means the runner's own `CATCHES_CHANGE` label: the test passes
on `before.py` and fails on `after.py`. One test is enough. `tests` counts pytest
test items, one per test function plus one per parametrized case.

**Caveats**

- **One of three.** Three observations is not a rate.
- **The "pull request" is a fix run backwards.** `before.py` is the commit that
  *fixed* the bug and `after.py` is the commit that *had* it. Nobody in either
  project ever wrote this change; it was reconstructed from history.
- **Both projects are public and BugsInPy is public.** The model may have seen
  these fixes in training data. If anything that inflates the result.
- **The bugs target Python 3.7 and 3.8; the run was on 3.13.9.** The check script
  rejected two of the three witness inputs for exactly this reason before any of
  this was measured.
- **Evaluation only.** No prompt, operator or threshold was changed after seeing
  these numbers, and nothing in `src/prsentinel` can read `examples/real_cases`.
  `tests/test_real_cases.py` fails if it so much as names the folder.
- **Where the two misses go wrong is in the reports.** For youtube-dl bug 3, three
  tests failed on `before.py` too and were judged `BAD_TEST`. For PySnooper bug 3,
  one test *fails on the old code and passes on the new one*: it encoded the
  buggy behaviour as the expected behaviour.

---

## 6. The single-prompt baseline

One call to the same model per case. Same `before.py`, same `after.py`, same one
changed function's old and new source. No pipeline, no mutation, no rerun loop, no
judge. Run 2026-10-02, Groq only, **five calls, one per case**. The prompt was
frozen on 2026-10-02 before the run and a test holds its exact text.

**Where this comes from:**

- The five replies: `baselines_single_prompt/<case>/`, saved in git.
- The PRSentinel column: `reports/real_cases/*.json` and
  `reports/round1_off_by_one.json` / `reports/round2_mutable_default.json`.
- **The baseline's own per-case counts are recomputed, not copied.** The script
  saved its replies but no report, and its console table was not written down, so
  the baseline column below was re-scored from the five saved files using the same
  `test_runner.evaluate_tests` the live run used. That is deterministic pytest, not
  a model call, so it reproduces exactly and costs nothing.
- Both columns were scored by the same `read_report_numbers` and the same
  `CATCHES_CHANGE` rule, so the two arms are like for like.

| Case | Group | Baseline tests | Baseline catches | Baseline caught | PRS tests | PRS catches | PRS caught | Project's own test |
|---|---|---|---|---|---|---|---|---|
| `real_youtube-dl_bug43` | real | 24 | **5** | **yes** | 24 | **5** | **yes** | caught |
| `real_youtube-dl_bug3` | real | 15 | 0 | no | 19 | 0 | no | caught |
| `real_PySnooper_bug3` | real | 3 | **1** | **yes** | 4 | 0 | no | caught |
| `round1_off_by_one` | synthetic | 8 | **5** | yes | 11 | **6** | yes | none |
| `round2_mutable_default` | synthetic | 4 | **3** | yes | 11 | **9** | yes | none |

| Group | One plain prompt | PRSentinel | The project's own test |
|---|---|---|---|
| Real cases | **2 of 3** | **1 of 3** | **3 of 3** |
| Synthetic cases | 2 of 2 | 2 of 2 | n/a |

There is no grand total on purpose. Three real cases and two synthetic ones are
two different kinds of measurement, and one number over both invites being read as
a rate.

**Caveats**

- **The project's own test caught all three bugs. That is the bar.** It is what a
  human wrote. PRSentinel at 1 of 3 is not close to it.
- **One plain prompt beat PRSentinel, 2 of 3 to 1 of 3.** On PySnooper bug 3 the
  plain prompt wrote a catching test and PRSentinel's four did not. This is the
  finding in this table and it does not flatter the project.
- **The identical bug 43 row is a coincidence, not agreement.** Both arms produced
  24 test items and 5 catching tests on that case. The two replies are different
  files of different lengths, 2875 and 1727 bytes, and neither is a copy of the
  other. Same counts out of two different prompts on one case is not evidence that
  the arms are equivalent.
- **The two synthetic rows are not like for like.** PRSentinel's side of them was
  scored on frozen hand-checked tests from `baselines/`, saved in an earlier step,
  not on a fresh generation. The baseline's side is a fresh call on all five. They
  are not evidence that PRSentinel's generator beats one plain call.
- **The baseline was written after the real-case numbers were known.** The real
  cases were protected from exactly that and the baseline arm was not. A baseline
  written without seeing the results it is compared against is worth more than
  this one. Say this in the paper rather than leaving it to be noticed.
- **Five calls, one per case, is the cheapest comparison available, not the
  strongest.** A baseline with two prompts averaged, or a self-check, or a repair
  pass, would be a fairer opponent and would probably score higher. This one exists
  to show that the machinery is not paying for itself, not to be the best baseline
  in existence.
- **Five cases.** As above.

---

## CoverUp, and why it is not a baseline here

CoverUp 0.6.3 installs cleanly on this machine and then cannot run on it: its
required dependency `pytest-isolate` imports `fcntl` and `resource` at module
level, and pytest auto-loads that plugin in every run, so no CoverUp flag avoids
it. It would also be the wrong shape of comparison, being coverage-driven where
PRSentinel is change-driven. The full evidence, including the two suspected
problems that turned out to be harmless, is in `NOTES_COVERUP.md`.
