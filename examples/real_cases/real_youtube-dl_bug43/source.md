# Source: youtube-dl bug 43, `url_basename`

## The project and the bug

| | |
|---|---|
| Project | youtube-dl, <https://github.com/ytdl-org/youtube-dl> |
| License | Public domain (the Unlicense). Free to copy and modify. Nothing in this folder is restricted. |
| Bug folder | `projects/youtube-dl/bugs/43` in BugsInPy, <https://github.com/soarsmu/bugsinpy> |
| Python the bug targets | 3.7.4 (`bug.info`) |
| Python we run on | 3.13.9. The regex is plain `re`, so the version does not matter here. |
| Buggy commit | `cecaaf3f58ad9f544dbb79af1e565d9353fa2b2d` |
| Fixed commit | `d6c7a367e88096bb17e323954002c084477fe908` |
| Test file | `test/test_utils.py`, method `TestUtil.test_url_basename` |
| Run script | `python -m unittest -q test.test_utils.TestUtil.test_url_basename` |

## Which direction is before and which is after

BugsInPy calls the **buggy** commit "before the fix". Step 10A reverses that.

- `before.py` is the **fixed** commit. It is the correct code.
- `after.py` is the **buggy** commit. The bug is the change.
- `diff.patch` is the project's own `bug_patch.txt` with the `-` and `+` lines
  swapped, so it reads correct to buggy, which matches `before.py` to
  `after.py`.

## The change

One line, one character class. In `youtube_dl/utils.py`, inside `url_basename`:

```python
-    m = re.match(r'(?:https?:|)//[^/]+/(?:[^?#]+/)?([^/?#]+)/?(?:[?#]|$)', url)   before
+    m = re.match(r'(?:https?:|)//[^/]+/(?:[^/?#]+/)?([^/?#]+)/?(?:[?#]|$)', url)   after
```

`before.py` allows a `?` inside a path segment, so a URL whose query string
starts part-way through the path still yields its last real segment.
`after.py` forbids it, finds no segment at all, and returns the empty string.

`witness.md` shows this on a URL with a query string in the middle of the path.

## The helper count

| # | What | Where from | Lines | Counts as a helper |
|---|---|---|---|---|
| | none | | | |

**Zero project helpers. Under the limit of 3.**

`url_basename` uses `re` from the standard library and its own parameter, and
nothing else. That is why this bug was the first candidate tried.

## Why this bug and not the other two

Three candidates were inspected in the order 43, 13, 15, and the first one that
qualified was taken.

| Bug | Function that really changes | Project helpers | Outcome |
|---|---|---|---|
| 43 | `url_basename`, 5 lines | 0 (`re` only) | **Chosen.** Smallest possible case, nothing to copy in. |
| 13 | `urljoin`, 13 lines | `compat_urlparse` | Qualified, but not needed once 43 worked. |
| 15 | `js_to_json`, 39 lines | `fix_kv`, `COMMENT_RE`, `SKIP_RE` | Qualified, but not needed once 43 worked. |

No bug was skipped for needing 4 or more helpers. Nothing had to be skipped for
that reason, so `../README.md` records no skips.

## The patch header on this bug names the wrong function

This is worth reading twice, because it is the kind of thing that quietly
produces a wrong answer.

The real `bug_patch.txt` hunk header reads:

```
@@ -1087,7 +1087,7 @@ def remove_start(s, start):
```

It says `remove_start`. The line that actually changes is three lines below it,
inside `url_basename`.

That is normal `diff` behaviour, not a mistake by youtube-dl. A hunk header names
the nearest function that **starts above** the changed line, so when a change
lands in the second function of a hunk the header still points at the first.
Anyone reading a real patch by its header alone extracts the wrong function here,
and would extract the wrong function in 4 of the 410 hunks across the 124
youtube-dl bugs in BugsInPy that change a plain top-level function.

This is one of the reasons PRSentinel recovers the whole changed function from
the AST rather than trusting the header, and the reason
`src/prsentinel/diff_extractor.py` works from `before.py` and `after.py` rather
than from the patch text. Reading `diff.patch` inside the pipeline is out of
scope for this step and was not done.

## How the copy was checked

`before.py` and `after.py` were cut out of the real checkout by line number
(1089-1093) rather than retyped, and the builder compared the helper region of
the two files byte for byte before writing either one. They did not differ.

## What was changed in `existing_test.py`, and why

`existing_test_original.py` is `test/test_utils.py` lines 185-193, byte for byte,
and is never run. `existing_test.py` is the same test flattened so pytest can run
it. Three changes, none of them an expectation:

| Original | Here | Why |
|---|---|---|
| `def test_url_basename(self):` | `def test_url_basename():` | It was a method on the project's `TestUtil` class. That needs `unittest` and the class; here it is a plain pytest function. |
| `self.assertEqual(a, b)` | `assert a == b` | Same comparison, no `self`. |
| `url_basename` used bare | `from target import url_basename` | `test_runner` copies the module in as `target.py`, so that is the name to import. |

Every input and every expected value is the project's, character for character.
No case was added, removed or edited.

## This project's own test does not catch this bug either

All six assertions in `test_url_basename` pass on `before.py` and on `after.py`.
So `scripts/check_real_cases.py` reports `NO_SIGNAL` for the test and that is the
honest result.

Same as bug 3, and for the same reason: the fix landed without a new test case.
Every case the project wrote puts the query string at the **end** of the URL,
which is the case both versions already handled. The bug only shows up when the
query string is in the middle. That gap is the bug.