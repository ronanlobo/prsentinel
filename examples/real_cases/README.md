# Real bug cases

Three real bugs from two real projects, in the shape PRSentinel expects. These
sit alongside `../round1_off_by_one` and `../round2_mutable_default`, which were
written by hand for the first two rounds.

The difference matters. The two round folders are illustrations: someone chose a
bug shape and wrote it down. These three are not. Every line of code that came
from a project was cut out of that project's real repository at a real commit,
and the fact that the bug reproduces is checked, not asserted.

## The folders

| Folder | Project | Bug | Function |
|---|---|---|---|
| `real_youtube-dl_bug3/` | youtube-dl | 3 | `unescapeHTML` |
| `real_youtube-dl_bug43/` | youtube-dl | 43 | `url_basename` |
| `real_PySnooper_bug3/` | PySnooper | 3 | `get_write_function` |

## This folder is for evaluation, not for tuning

Everything here is meant to be run once, measured, and reported. Nothing in
PRSentinel may be changed in the light of what these cases produce.

That is the whole point of putting real bugs in the set. If a prompt is
rewritten, a repair rule adjusted or a classifier threshold moved after seeing
these results, the numbers stop meaning what they claim to mean: they stop
measuring PRSentinel and start measuring PRSentinel-plus-whatever-we-learned-
from-the-answers. Any change made after seeing a result from this folder is a
result from a different system, and the honest thing is to say so in the paper
rather than quietly fold it in.

Concretely, for this step:

- no prompt is tuned against these cases
- no classifier rule is changed against these cases
- the 18 mutation operators stay exactly as they were fixed in step 9.5
- the check script is not relaxed to make a case pass

The check script rejecting two of the three cases on its first run is the point.
Those rejections are recorded in each `witness.md` rather than hidden, and the
witness inputs were corrected. What was not done is loosening the check.

## Before and after run backwards from BugsInPy

BugsInPy records the **buggy** commit as "before the fix". PRSentinel assumes
`before.py` is correct and `after.py` is the change a pull request introduces.
So the direction is reversed:

- `before.py` is the **fixed** commit, the correct code
- `after.py` is the **buggy** commit
- `diff.patch` is the project's own `bug_patch.txt` with the `-` and `+` lines
  swapped, so it reads correct to buggy

## What each case folder holds

Seven files, same seven in every folder.

| File | What it is |
|---|---|
| `before.py` | The correct version of the changed function plus whatever it needs. |
| `after.py` | The buggy version. Byte-identical to `before.py` except the changed function. |
| `diff.patch` | The project's real patch, reversed. |
| `existing_test.py` | The project's own test, flattened so pytest can run it. |
| `existing_test_original.py` | That same test, byte for byte, never run. Kept so the flattening can be audited. |
| `source.md` | Where every line came from, and exactly what was changed and why. |
| `witness.md` | An input that behaves differently on the two versions, with the expected output for each. |

## The rules these cases were built under

**No stubbing.** Where the changed function needs another piece of the project,
that piece is copied in verbatim, never faked, never simplified. The one thing
that is not copied is written down in that case's `source.md` and explained.

**At most 3 helpers per case.** A helper is a named function, class or constant
from the project. The counts are 1, 0 and 2. Anything needing 4 or more was to be
skipped and reported.

**Identical in before and after.** Whatever is copied in is byte-identical in
both files. A builder compared the copied region of the two files and stopped if
they differed. Only the docstring and the changed function differ. You can check
this yourself:

```
git diff --no-index examples/real_cases/real_youtube-dl_bug43/before.py ^
                 examples/real_cases/real_youtube-dl_bug43/after.py
```

## Bugs inspected and not used

Three youtube-dl candidates were inspected in the order 43, 13, 15, and the
first that qualified was taken. All three qualified.

| Bug | Function that really changes | Project helpers | Outcome |
|---|---|---|---|
| 43 | `url_basename`, 5 lines | 0 | **Used.** |
| 13 | `urljoin`, 13 lines | 1 | Not needed once 43 worked. |
| 15 | `js_to_json`, 39 lines | 3 | Not needed once 43 worked. |

**No bug was skipped for needing 4 or more helpers.** The rule that a case with
too many dependencies is dropped rather than bent was not exercised, so there is
nothing to report on it.

Two projects were rejected before any of this, and neither reached the helper
count:

- **spaCy bug 8.** `pip install spacy==3.0.1` fails on Python 3.13 with `the
  NumPy Cython headers require Cython 3.0.0 or newer`. The project cannot be
  installed, and the patch adds a constant inside a 175-line `class Errors`
  rather than changing a function.
- **youtube-dl bug 3 as a candidate for the third slot.** It was kept, but as
  case 1 rather than case 3, because bugs 43, 13 and 15 were the candidates
  being compared.

## Licences

| Project | Licence | Usable |
|---|---|---|
| youtube-dl | Public domain (the Unlicense) | Yes |
| PySnooper | MIT, Copyright (c) 2019 Ram Rachum | Yes |

Both are permissive. Nothing in this folder is under a licence that would stop
it being copied and quoted. No case was dropped over its licence.

## Checking them

```
.venv\Scripts\python.exe scripts\check_real_cases.py
```

No AI is involved. The script runs each case's own test through
`prsentinel.test_runner` on both versions, runs each witness on both versions,
and compares what the witnesses printed with what `witness.md` says they print.
A witness that agrees on both versions is a case that does not reproduce here, and
the script rejects it rather than working around it.

## Caveats to state in the paper

These are real bugs from real projects, and they carry real limitations. None of
them should be quietly dropped from the write-up.

**Each case is a simulated pull request, not a real one.** BugsInPy reconstructs a
bug by taking a fixed commit and reverting its fix. So `before.py` and
`after.py` are a real fix and its real inverse, but no developer ever wrote that
pull request, and there is no issue text, no discussion, no branch and no review.
Any result here is a result on reverted fixes, not on the real pull requests that
PRSentinel would meet in practice.

**Training-data contamination cannot be ruled out.** Both projects are public and
popular, and their fixes are in the training data of any model with a 2024 or
later cut-off. A model may have seen the fixed function, the buggy version, the
discussion and the patch. Its generated tests may be better than they have any
right to be, and the effect cannot be measured from inside this project. The
paper should say so rather than leave the reader to assume the cases were unseen.

**The bugs target Python 3.7 and 3.8; these run on Python 3.13.** All 501 BugsInPy
bugs pin a Python between 3.6.9 and 3.8.3. This machine has 3.13.9 only. The
three cases chosen here avoid the problem by being version-independent in
practice: two are plain `re` and one uses only `open`, `sys` and `isinstance`,
and all three witnesses reproduce on 3.13. That is a reason these three were
chosen, and it is also a limitation: it means nothing here tests how PRSentinel
copes with a project that genuinely needs an old interpreter, and nothing here
tests the compatibility shims, which is a real part of that difficulty.

**Two of three cases were rejected by the check on their first run.** The first
witness input chosen for each of the two youtube-dl cases turned out not to
differ between the versions, and the check script caught it. The inputs were
corrected and the rejections are recorded in each `witness.md`. It is worth
reporting as a positive result about the check, and it is also a reminder that
"here is a bug" and "here is an input that shows the bug" are different claims.