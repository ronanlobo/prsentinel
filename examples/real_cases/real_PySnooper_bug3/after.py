"""PySnooper bug 3. This is our "after": the BUGGY version.

The only line that changed from before.py is the argument passed to open()
inside get_write_function: output became output_path. That is the real fix, read
backwards, because BugsInPy records the fix and Step 10A wants "before" to be the
correct code.

output_path is a name that appears nowhere else in the function or the module, so
the first write raises NameError: name 'output_path' is not defined.

Two project helpers are copied in, both from pysnooper/utils.py:
_check_methods (lines 9-19) and WritableStream (lines 22-31). Two one-line
shims come from pysnooper/pycompat.py. source.md has the list, and it also
explains the two namespace lines just below WritableStream.

Every line above the CHANGED FUNCTION marker is byte-identical to before.py.
"""

import abc
import os
import sys
import types

# --- copied verbatim from pysnooper/pycompat.py, lines 9 and 20 ----------
# In pycompat.py each of these sits indented inside an if/else, one branch per
# Python version. Only the branch Python 3 takes is kept, dedented to column 0.

ABC = abc.ABC
PathLike = os.PathLike


# --- copied verbatim from pysnooper/utils.py, lines 9-19 ---------------

def _check_methods(C, *methods):
    mro = C.__mro__
    for method in methods:
        for B in mro:
            if method in B.__dict__:
                if B.__dict__[method] is None:
                    return NotImplemented
                break
        else:
            return NotImplemented
    return True


# --- copied verbatim from pysnooper/utils.py, lines 22-31 --------------

class WritableStream(ABC):
    @abc.abstractmethod
    def write(self, s):
        pass

    @classmethod
    def __subclasshook__(cls, C):
        if cls is WritableStream:
            return _check_methods(C, 'write')
        return NotImplemented

# In the project these two names are sibling modules, so get_write_function
# writes pycompat.PathLike and utils.WritableStream. Flattened into one file
# they have to be plain objects. These two lines point those names at the code
# copied in above, and at nothing else. source.md explains this.
pycompat = types.SimpleNamespace(PathLike=PathLike)
utils = types.SimpleNamespace(WritableStream=WritableStream)




# --- CHANGED FUNCTION: pysnooper/pysnooper.py, lines 19-33 -------------

def get_write_function(output):
    if output is None:
        def write(s):
            stderr = sys.stderr
            stderr.write(s)
    elif isinstance(output, (pycompat.PathLike, str)):
        def write(s):
            with open(output_path, 'a') as output_file:
                output_file.write(s)
    else:
        assert isinstance(output, utils.WritableStream)
        def write(s):
            output.write(s)

    return write
