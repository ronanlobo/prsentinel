# Witness for PySnooper bug 3

A witness is a few lines of code that behave **differently** on `before.py` and
on `after.py`. If a witness gives the same answer on both, the case is not
reproducing and `scripts/check_real_cases.py` rejects it rather than working
around it.

## What is being shown

`get_write_function(output)` decides how a trace gets written. When the caller
passes a path, the returned `write` function appends to that path. The patch
changed one argument inside that append:

| | code | meaning |
|---|---|---|
| `before.py` (correct) | `open(output, 'a')` | `output` is the path the caller gave |
| `after.py` (buggy) | `open(output_path, 'a')` | `output_path` is a name that appears nowhere else in the module, so the first write raises `NameError` |

This one crashes rather than returning a wrong answer. That is still a difference,
and a loud one. The witness catches the error and prints it, so that both
versions produce output that can be compared.

## The witness

```python
import os
import tempfile

import target

folder = tempfile.mkdtemp(prefix='pysnooper_witness_')
path = os.path.join(folder, 'trace.log')

# In the project this is reached through @pysnooper.snoop(str(path)), which
# calls get_write_function itself and then traces the call. Only
# get_write_function is part of the change under test.
write = target.get_write_function(path)

try:
    write('x = 7\n')
except NameError as error:
    print('raised NameError:', error)
else:
    with open(path) as handle:
        print('wrote:', repr(handle.read()))
```

## What each version prints

`before.py`, the correct version:

```
wrote: 'x = 7\n'
```

`after.py`, the buggy version:

```
raised NameError: name 'output_path' is not defined
```

The name is not a typo that happens to work. `output_path` does not appear
anywhere else in `get_write_function` or anywhere else in `pysnooper.py`, so the
crash is immediate and total: no trace can ever be written to a file, so every
`@pysnooper.snoop('some/path.log')` in the project is broken.

## Was this checked on Python 3.13?

Yes. BugsInPy pins this bug to Python 3.8.1. `scripts/check_real_cases.py`
re-runs the witness on whatever Python is running it and will not call the case
reproduced unless the two outputs actually differ. The output above was taken on
Python 3.13.9. The changed function uses only `open`, `sys` and `isinstance`, so
the Python version does not affect it.

## Note on the dependencies

This is the one case whose real project needs extra packages. `pysnooper`
imports `decorator`, `future` and `six`, and all three install on Python 3.13.
Our `before.py` and `after.py` do **not** import them: only `get_write_function`
and the two helpers it needs are copied in, and none of those touch `decorator`.
`decorator` and `six` were installed while this case was prepared and removed
again afterwards. `source.md` has the details.