import sys
import io
import builtins
import pytest

from target import get_write_function


def test_write_none_writes_to_stderr(monkeypatch):
    fake_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    write = get_write_function(None)
    write("error message\n")

    assert fake_stderr.getvalue() == "error message\n"


def test_write_path_appends(tmp_path):
    file_path = tmp_path / "out.txt"

    write = get_write_function(str(file_path))
    write("first line\n")
    write("second line\n")

    content = file_path.read_text()
    assert content == "first line\nsecond line\n"


def test_write_writable_stream(monkeypatch):
    # Make the assert accept StringIO as a valid WritableStream
    import target
    monkeypatch.setattr(target.utils, "WritableStream", (io.StringIO,))

    stream = io.StringIO()
    write = get_write_function(stream)
    write("streamed data")
    write(" more data")

    assert stream.getvalue() == "streamed data more data"
