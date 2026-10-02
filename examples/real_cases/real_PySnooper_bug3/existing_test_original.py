"""PySnooper's own test for this bug, byte for byte.

Copied from tests/test_pysnooper.py lines 174-198 at the fixed commit
15555ed760000b049aff8fecc79d29339c1224c3. Not one character was changed.

This cannot run on its own. It needs pysnooper, which means the whole package
including its tracer, and it needs python_toolbox, and it checks the trace
against a list of entry classes that also live in the project's test helpers.
None of that is part of the changed function. That is why there is a second
file, existing_test.py, which keeps the shape and the expectations and drops
the package. source.md lists every change.

This file is kept for the record. Nothing runs it.
"""


def test_file_output():

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
        assert_output(
            output,
            (
                VariableEntry('foo', value_regex="u?'baba'"),
                CallEntry(),
                LineEntry('x = 7'),
                VariableEntry('x', '7'),
                LineEntry('y = 8'),
                VariableEntry('y', '8'),
                LineEntry('return y + x'),
                ReturnEntry('return y + x'),
            )
        )
