# Source: youtube-dl bug 3, `unescapeHTML`

## The project and the bug

| | |
|---|---|
| Project | youtube-dl, <https://github.com/ytdl-org/youtube-dl> |
| License | Public domain (the Unlicense). Free to copy and modify. Nothing in this folder is restricted. |
| Bug folder | `projects/youtube-dl/bugs/3` in BugsInPy, <https://github.com/soarsmu/bugsinpy> |
| Python the bug targets | 3.7.0 (`bug.info`) |
| Python we run on | 3.13.9. The regex is plain `re`, so the version does not matter here. |
| Buggy commit | `f5469da9e6e259c1690c7ef54f1da1c19f65036f` |
| Fixed commit | `95f3f7c20a05e7ac490e768b8470b20538ef8581` |
| Test file | `test/test_utils.py`, method `TestUtil.test_unescape_html` |
| Run script | `python -m unittest -q test.test_utils.TestUtil.test_unescape_html` |

## Which direction is before and which is after

BugsInPy calls the **buggy** commit "before the fix". Step 10A reverses that.

- `before.py` is the **fixed** commit. It is the correct code.
- `after.py` is the **buggy** commit. The bug is the change.
- `diff.patch` is the project's own `bug_patch.txt` with the `-` and `+` lines
  swapped, so it reads correct to buggy, which matches `before.py` to
  `after.py`.

This is what PRSentinel already assumes everywhere else: `before.py` is the code
that works and `after.py` is what a pull request would introduce.

## The change

One line, one character class. In `youtube_dl/utils.py`, inside `unescapeHTML`:

```python
-        r'&([^&;]+;)', lambda m: _htmlentity_transform(m.group(1)), s)   before
+        r'&([^;]+;)', lambda m: _htmlentity_transform(m.group(1)), s)    after
```

`before.py` refuses to let `&` appear inside an entity, so `&amp;quot;` is read as
the entity `&amp;` followed by the plain text `quot;`. `after.py` allows it, so
the match swallows `&amp;quot;` whole, finds no entity it knows, and hands the
string straight back.

`witness.md` shows this on `'&amp;quot;'`.

## The helper count

The rule for this step is: no stubbing, copy what is needed verbatim, at most 3
helpers, and the copy must be identical in `before.py` and `after.py`.

| # | What | Where from | Lines | Counts as a helper |
|---|---|---|---|---|
| 1 | `_htmlentity_transform` | `youtube_dl/utils.py` | 562-590 | yes. One project function. |
| | `import html.entities as compat_html_entities` | `youtube_dl/compat.py` | 63 | no. Points at the standard library. |
| | `compat_html_entities_html5 = compat_html_entities.html5` | `youtube_dl/compat.py` | 68 | no. Points at the standard library. |
| | `compat_str = str` | `youtube_dl/compat.py` | 2352 | no. Points at the standard library. |
| | `compat_chr = chr` | `youtube_dl/compat.py` | 2492 | no. Points at the standard library. |

**One project helper. Under the limit of 3.**

The last four rows are the project's own Python 2 / 3 shim: on Python 3 they are
one-line aliases onto standard-library names. They are not project logic, so
they are not counted as helpers, but they are still copied exactly as written and
are listed here so nothing is hidden. On Python 3.13 the `try` branch that
`compat.py` takes at lines 67-68 is the one where `compat_html_entities_html5` is
`html.entities.html5`, not the 2,800-line literal further down the file. That is
why this case is small: the huge data table is never used.

The only edit made to those four lines is that each was dedented from column 4 to
column 0, because in `compat.py` they sit inside `try` / `except ImportError`
blocks, one branch per Python version, and only the branch Python 3 takes was
kept. Nothing else was changed. Line endings were normalised from the CRLF of a
Windows checkout to LF, which is what `.gitattributes` asks for.

## How the copy was checked, and how to check it again

Everything in `before.py` and `after.py` that is not our own docstring and not
the changed function was cut out of the real checkout by line number, not
retyped. A builder script compared the helper region of the two files byte for
byte and stopped if they differed. They did not differ.

You can check the same thing yourself without the builder:

```
git diff --no-index before.py after.py
```

Every difference shown is inside or after the `# --- CHANGED FUNCTION` marker,
which is what "the helpers are identical" means here.

## What was changed in `existing_test.py`, and why

`existing_test_original.py` is `test/test_utils.py` lines 276-284, byte for byte,
and is never run. `existing_test.py` is the same test flattened so pytest can run
it. Three changes, none of them an expectation:

| Original | Here | Why |
|---|---|---|
| `def test_unescape_html(self):` | `def test_unescape_html():` | It was a method on the project's `TestUtil` class. That needs `unittest` and the class; here it is a plain pytest function. |
| `self.assertEqual(a, b)` | `assert a == b` | Same comparison, no `self`. |
| `unescapeHTML` used bare | `from target import unescapeHTML` | `test_runner` copies the module in as `target.py`, so that is the name to import. |

Every input and every expected value is the project's, character for character.
No case was added, removed or edited. In particular the `'&eacute;'` case is the
real `'é'`, not a substitute.

## This project's own test does not catch this bug

All seven assertions in `test_unescape_html` pass on `before.py` and on
`after.py`. So `scripts/check_real_cases.py` reports `NO_SIGNAL` for the test and
that is the honest result.

This is not a mistake in the test. The fix came with no new test case; the seven
that exist were written earlier and none of them uses double-escaped input. It
is a real property of a real bug, and it is worth having in the set: it is what a
project looks like when the fix lands without a regression test. `witness.md`
shows the input that does tell the two apart.