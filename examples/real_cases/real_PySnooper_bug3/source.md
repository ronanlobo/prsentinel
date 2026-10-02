# Source: PySnooper bug 3, `get_write_function`

## The project and the bug

| | |
|---|---|
| Project | PySnooper, <https://github.com/cool-RR/PySnooper> |
| License | MIT, Copyright (c) 2019 Ram Rachum. Free to copy and modify with the notice kept. Nothing in this folder is restricted. |
| Bug folder | `projects/PySnooper/bugs/3` in BugsInPy, <https://github.com/soarsmu/bugsinpy> |
| Python the bug targets | 3.8.1 (`bug.info`) |
| Python we run on | 3.13.9. The function uses only `open`, `sys` and `isinstance`, so the version does not matter here. |
| Buggy commit | `6e3d797be3fa0a746fb5b1b7c7fea78eb926c208` |
| Fixed commit | `15555ed760000b049aff8fecc79d29339c1224c3` |
| Test file | `tests/test_pysnooper.py`, function `test_file_output` |
| Run script | `pytest -q -s tests/test_pysnooper.py::test_file_output` |
| Setup script | `python setup.py install` and `pip install decorator` |

## Which direction is before and which is after

BugsInPy calls the **buggy** commit "before the fix". Step 10A reverses that.

- `before.py` is the **fixed** commit. It is the correct code.
- `after.py` is the **buggy** commit. The bug is the change.
- `diff.patch` is the project's own `bug_patch.txt` with the `-` and `+` lines
  swapped, so it reads correct to buggy, which matches `before.py` to
  `after.py`.

## The change

One line, one word. In `pysnooper/pysnooper.py`, inside `get_write_function`:

```python
-            with open(output, 'a') as output_file:        before
+            with open(output_path, 'a') as output_file:   after
```

`output_path` is a name that appears nowhere else in the function or anywhere
else in `pysnooper.py`. It is not a typo that happens to resolve. The first time
anything is written to a file, Python raises `NameError: name 'output_path' is
not defined`, so no trace can ever be written to a file at all.

`witness.md` shows this by writing one line and reading it back.

## The helper count

The rule for this step is: no stubbing, copy what is needed verbatim, at most 3
helpers, and the copy must be identical in `before.py` and `after.py`.

| # | What | Where from | Lines | Counts as a helper |
|---|---|---|---|---|
| 1 | `_check_methods` | `pysnooper/utils.py` | 9-19 | yes. One project function. |
| 2 | `WritableStream` | `pysnooper/utils.py` | 22-31 | yes. One project class. |
| | `ABC = abc.ABC` | `pysnooper/pycompat.py` | 9 | no. Points at the standard library. |
| | `PathLike = os.PathLike` | `pysnooper/pycompat.py` | 20 | no. Points at the standard library. |

**Two project helpers. Under the limit of 3.**

The last two rows are the project's own Python 2 / 3 shim: on Python 3 they are
one-line aliases onto standard-library names. They are not project logic, so
they are not counted as helpers, but they are still copied exactly as written and
are listed here so nothing is hidden. As in the youtube-dl case, only the branch
Python 3 takes was kept, so the `PathLike` fallback class further down
`pycompat.py` is not needed.

The only edit made to those two lines is that each was dedented from column 4 to
column 0, because in `pycompat.py` they sit inside `if` / `else` blocks, one
branch per Python version. Nothing else was changed. Line endings were
normalised from the CRLF of a Windows checkout to LF, which is what
`.gitattributes` asks for.

## The two namespace lines, and why they are not a stub

`get_write_function` reads `pycompat.PathLike` and `utils.WritableStream`. In
the project those are sibling modules, imported at the top of `pysnooper.py`:

```python
from . import utils
from . import pycompat
```

Flattened into one file there is no `.` and no package, so those two names have
to be plain objects. Two lines do that:

```python
pycompat = types.SimpleNamespace(PathLike=PathLike)
utils = types.SimpleNamespace(WritableStream=WritableStream)
```

They add no behaviour and remove none. They point the names the copied function
already uses at the code copied in above, and at nothing else. Nothing is faked:
`PathLike` is really `os.PathLike` and `WritableStream` is really the project's
class. Writing a fake `PathLike` that always matched would be a stub; this is
not.

## The dependencies, and what was installed

The real project needs `decorator`, `future` and `six`. All three install on
Python 3.13 and were installed while this case was being prepared, then removed
again so the environment is as it was.

None of the three is needed by `before.py` or `after.py`. They are imported at
the top of the real `pysnooper.py`, above `get_write_function`, and none of the
copied code touches them. They are listed here because they were touched, not
because this case depends on them.

## How the copy was checked

Everything above the `# --- CHANGED FUNCTION` marker was cut out of the real
checkout by line number rather than retyped, and the builder compared that
region of `before.py` and `after.py` byte for byte before writing either one.
They did not differ. You can check the same thing yourself:

```
git diff --no-index before.py after.py
```

Every difference shown is inside or after that marker.

## What was changed in `existing_test.py`, and why

This is the one case where the adaptation is more than cosmetic, so every change
is listed.

`existing_test_original.py` is `tests/test_pysnooper.py` lines 174-198, byte for
byte, and is never run. The original does this:

```python
with temp_file_tools.create_temp_folder(prefix='pysnooper') as folder:
    path = folder / 'foo.log'
    @pysnooper.snoop(str(path))
    def my_function(foo):
        x = 7
        y = 8
        return y + x
    result = my_function('baba')
    assert result == 15
    output = path.open().read()
    assert_output(output, (VariableEntry(...), CallEntry(), ...))
```

That needs the whole package, the tracer, and a second test-only package. None
of that is the function that changed.

`existing_test.py` keeps the traced function's body exactly, keeps the
arithmetic, and keeps the expectations:

| Original | Here | Why |
|---|---|---|
| `@pysnooper.snoop(str(path))` on the function | `write = get_write_function(str(path))` called directly | `snoop` calls `get_write_function` internally and then traces the call. Only `get_write_function` is part of the change under test, so the test drives it directly and writes the same two lines it would have written. |
| `temp_file_tools.create_temp_folder` | `tempfile.mkdtemp` | `temp_file_tools` is from `python_toolbox`, a test-only package not present here. Both make a temporary folder. |
| `folder / 'foo.log'` | `os.path.join(folder, 'foo.log')` | `folder` was a `pathlib` path from `python_toolbox`. |
| `path.open().read()` | `with open(path) as handle: output = handle.read()` | Same read, plain `open`. |
| `assert_output(output, (VariableEntry('foo', ...), CallEntry(), LineEntry('x = 7'), ...))` | `assert 'x = 7' in output` and `assert 'y = 8' in output` | `assert_output` and the entry classes are the project's own test helpers in `tests/utils.py`, and they match the trace entry by entry. The entries this test listed include `LineEntry('x = 7')` and `LineEntry('y = 8')`, which is exactly what the two `assert ... in output` lines check. Nothing weaker is claimed: the original also asserts `result == 15`, and that assertion is kept as it stands. |

The one thing that is genuinely weaker is worth naming rather than hiding: the
original checked that `foo` was `'baba'`, that the call was recorded, and that the
return was recorded. Those entries come from the tracer, not from
`get_write_function`, so they are gone with the tracer. What survives is the part
this bug can affect, which is whether the trace reaches the file at all.