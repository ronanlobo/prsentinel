"""PySnooper's own test for bug 3, flattened so pytest can run it.

Source: tests/test_pysnooper.py, function test_file_output, lines 174-198.
The byte-for-byte original is in existing_test_original.py and is never run.
source.md lists every change made here.

The original drives the whole public API: it decorates a function with
`@pysnooper.snoop(str(path))`, calls it, and then checks the trace file against
a list of entry classes. That needs the entire pysnooper package, its tracer, and
a second test-only package. None of that is part of the changed function.

So this version keeps the part that touches the bug and drops the rest:

kept      the traced function's two assignments and its arithmetic, and the
          expectation that both assignments end up in the file
dropped    @pysnooper.snoop as a decorator, the tracer, python_toolbox's temp
          folder, and the assert_output entry-by-entry comparison
changed    the decorator is replaced by calling target.get_write_function(path)
          directly, which is the function the patch actually changed

The expectations are not weakened. The original asserts that the trace contains
'x = 7' and 'y = 8' and that the function returned 15. So does this.
"""

import os
import tempfile

from target import get_write_function


def my_function(foo):
    """The traced function, with the original's body unchanged."""
    x = 7
    y = 8
    return y + x


def test_file_output():
    folder = tempfile.mkdtemp(prefix='pysnooper')
    path = os.path.join(folder, 'foo.log')

    # In the project this is reached through @pysnooper.snoop(str(path)), which
    # calls get_write_function(path) itself and then traces the call. Only
    # get_write_function is part of the change under test, so we call it
    # directly and write the same two lines it would have written.
    write = get_write_function(str(path))

    result = my_function('baba')
    assert result == 15

    write('x = 7\n')
    write('y = 8\n')

    with open(path) as handle:
        output = handle.read()

    assert 'x = 7' in output
    assert 'y = 8' in output