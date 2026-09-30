"""Tests for the test runner.

Everything here uses tiny hand-written modules and test files. No AI is
called and nothing touches the internet.
"""

import os
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from prsentinel import config
from prsentinel import test_runner as tr


def write(path, text):
    """Write dedented text to a file and give the path back."""
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return str(path)


@pytest.fixture
def work(tmp_path):
    """Make a module and a test file, and hand back their paths."""
    def build(test_code, module_code="def add(a, b):\n    return a + b\n"):
        module = write(tmp_path / "module.py", module_code)
        test = write(tmp_path / "test_generated.py", test_code)
        return module, test
    return build


# ---------------------------------------------------------------------------
# Reading the two results and choosing a label
# ---------------------------------------------------------------------------

def test_label_when_before_passes_and_after_fails():
    """The test noticed the change, so this is the useful case."""
    assert tr.label_for("passed", "failed") == tr.CATCHES_CHANGE


def test_label_when_both_fail():
    """Failing on the correct code means the test itself is wrong."""
    assert tr.label_for("failed", "failed") == tr.TEST_WRONG_ON_BEFORE


def test_label_when_before_fails_and_after_passes():
    """Failed on correct code but passed on changed code, which is odd."""
    assert tr.label_for("failed", "passed") == tr.ODD


def test_label_when_both_pass():
    """If the test cannot tell the versions apart it proves nothing."""
    assert tr.label_for("passed", "passed") == tr.NO_SIGNAL


def test_label_counts_an_error_as_a_failure():
    """A test that cannot run on correct code is still a broken test."""
    assert tr.label_for(tr.TEST_ERROR, tr.TEST_ERROR) == tr.TEST_WRONG_ON_BEFORE
    assert tr.label_for(tr.TEST_ERROR, tr.PASSED) == tr.ODD
    assert tr.label_for(tr.PASSED, tr.TEST_ERROR) == tr.CATCHES_CHANGE


def test_label_treats_a_skipped_test_as_not_failing():
    """A skipped test did not really run, so it is not a failure."""
    assert tr.label_for("passed", tr.SKIPPED) == tr.NO_SIGNAL
    assert tr.label_for(tr.SKIPPED, tr.SKIPPED) == tr.NO_SIGNAL


# ---------------------------------------------------------------------------
# Shortening the failure message
# ---------------------------------------------------------------------------

def test_short_message_keeps_at_most_three_lines():
    """The table stays readable, so we cut the message down."""
    text = "line one\nline two\nline three\nline four\nline five"
    assert tr._short_message(text) == "line one line two line three"


def test_short_message_is_capped_in_length():
    """A huge message must not wreck the table."""
    assert len(tr._short_message("x " * 500)) <= tr.MESSAGE_CHARS


# ---------------------------------------------------------------------------
# The child process must not see our API keys
# ---------------------------------------------------------------------------

def test_child_process_cannot_see_the_api_keys(work, tmp_path):
    """A fake key is set here, and the generated test must not find it."""
    os.environ["GROQ_API_KEY"] = "fake-key-that-must-not-leak"

    module, test = work("""
        import os

        def test_key_is_hidden():
            # If the runner passed the key on, this would find it.
            assert os.environ.get("GROQ_API_KEY") is None
    """)

    result = tr.run_tests(module, test, timeout_seconds=60)
    assert result["status"] == tr.OK, result
    assert list(result["tests"].values()) == [tr.PASSED], result


def test_child_environment_has_both_keys_removed():
    """The environment we hand the child must be missing both keys."""
    os.environ["GROQ_API_KEY"] = "fake-groq"
    os.environ["GEMINI_API_KEY"] = "fake-gemini"
    try:
        child = tr._child_environment()
        assert "GROQ_API_KEY" not in child
        assert "GEMINI_API_KEY" not in child
        # Our own process keeps them, only the child's copy is cleaned.
        assert os.environ.get("GROQ_API_KEY") == "fake-groq"
    finally:
        os.environ.pop("GROQ_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)


# ---------------------------------------------------------------------------
# Running a real test file
# ---------------------------------------------------------------------------

def test_one_passing_test(work):
    """A test that is happy on both versions reports NO_SIGNAL."""
    module, test = work("""
        from target import add

        def test_add():
            assert add(1, 2) == 3
    """)
    result = tr.run_tests(module, test, timeout_seconds=60)
    assert result["status"] == tr.OK
    assert list(result["tests"].values()) == [tr.PASSED]
    assert result["failures"] == {}


def test_one_failing_test(work):
    """A test that fails reports FAILED and keeps a short message."""
    module, test = work("""
        from target import add

        def test_add():
            assert add(1, 2) == 99
    """)
    result = tr.run_tests(module, test, timeout_seconds=60)
    assert result["status"] == tr.OK
    assert list(result["tests"].values()) == [tr.FAILED]

    message = list(result["failures"].values())[0]
    assert "99" in message, message


def test_one_passing_and_one_failing_test(work):
    """Each test gets its own result and its own message."""
    module, test = work("""
        from target import add

        def test_good():
            assert add(1, 2) == 3

        def test_bad():
            assert add(1, 2) == 99
    """)
    result = tr.run_tests(module, test, timeout_seconds=60)
    results = sorted(result["tests"].values())
    assert results == [tr.FAILED, tr.PASSED]
    assert len(result["failures"]) == 1


def test_a_test_inside_a_class_is_reported_with_its_class(work):
    """The name keeps the class so two same-named tests stay apart."""
    module, test = work("""
        from target import add

        class TestGroup:
            def test_inside(self):
                assert add(2, 2) == 4
    """)
    result = tr.run_tests(module, test, timeout_seconds=60)
    assert any("TestGroup" in name and "test_inside" in name
               for name in result["tests"]), result["tests"]


def test_import_error_gives_status_error(work):
    """A test importing something that is not there cannot even load."""
    module, test = work("""
        from target import a_function_that_is_not_there

        def test_never_runs():
            assert True
    """)
    result = tr.run_tests(module, test, timeout_seconds=60)
    assert result["status"] == tr.ERROR
    assert result["tests"] == {}
    assert result["error"], "the file-level error message must be kept"


def test_a_missing_file_is_reported_not_crashed(tmp_path):
    """A wrong path should come back as an error, not an exception."""
    result = tr.run_tests(tmp_path / "nope.py", tmp_path / "also_nope.py")
    assert result["status"] == tr.ERROR
    assert "cannot find" in result["error"]


def test_an_infinite_loop_times_out(work):
    """A test that never finishes must be stopped and reported as timeout."""
    module, test = work("""
        def test_forever():
            while True:
                pass
    """)
    result = tr.run_tests(module, test, timeout_seconds=2)
    assert result["status"] == tr.TIMEOUT
    assert "2s" in result["error"], result["error"]


# ---------------------------------------------------------------------------
# evaluate_tests, which runs the same file twice
# ---------------------------------------------------------------------------

def test_evaluate_tests_labels_catches_change(tmp_path):
    """Passes on the old module, fails on the new one."""
    before = write(tmp_path / "before.py", """
        def total(values):
            return sum(values)
    """)
    after = write(tmp_path / "after.py", """
        def total(values):
            return sum(values[:-1])
    """)
    test = write(tmp_path / "test_gen.py", """
        from target import total

        def test_total():
            assert total([1, 2, 3]) == 6
    """)

    results = tr.evaluate_tests(before, after, test)
    assert len(results) == 1
    assert results[0]["before"] == tr.PASSED
    assert results[0]["after"] == tr.FAILED
    assert results[0]["label"] == tr.CATCHES_CHANGE


def test_evaluate_tests_labels_no_signal(tmp_path):
    """Passes on both, so it cannot tell the versions apart."""
    before = write(tmp_path / "before.py", "def f():\n    return 1\n")
    after = write(tmp_path / "after.py", "def f():\n    return 1\n")
    test = write(tmp_path / "test_gen.py", """
        from target import f

        def test_f():
            assert f() == 1
    """)

    results = tr.evaluate_tests(before, after, test)
    assert results[0]["label"] == tr.NO_SIGNAL


def test_evaluate_tests_labels_test_wrong_on_before(tmp_path):
    """Fails on both, so the test is the problem."""
    before = write(tmp_path / "before.py", "def f():\n    return 1\n")
    after = write(tmp_path / "after.py", "def f():\n    return 2\n")
    test = write(tmp_path / "test_gen.py", """
        from target import f

        def test_f():
            assert f() == 999
    """)

    results = tr.evaluate_tests(before, after, test)
    assert results[0]["before"] == tr.FAILED
    assert results[0]["after"] == tr.FAILED
    assert results[0]["label"] == tr.TEST_WRONG_ON_BEFORE


def test_evaluate_tests_labels_odd(tmp_path):
    """Fails on the correct code but passes on the changed code."""
    before = write(tmp_path / "before.py", "def f():\n    return 1\n")
    after = write(tmp_path / "after.py", "def f():\n    return 2\n")
    test = write(tmp_path / "test_gen.py", """
        from target import f

        def test_f():
            assert f() == 2
    """)

    results = tr.evaluate_tests(before, after, test)
    assert results[0]["before"] == tr.FAILED
    assert results[0]["after"] == tr.PASSED
    assert results[0]["label"] == tr.ODD


def test_evaluate_tests_reports_the_whole_file_when_it_cannot_load(tmp_path):
    """No per-test names, so we report one row for the whole file."""
    before = write(tmp_path / "before.py", "def f():\n    return 1\n")
    after = write(tmp_path / "after.py", "def f():\n    return 1\n")
    test = write(tmp_path / "test_gen.py", """
        import a_module_that_is_not_installed

        def test_never_runs():
            assert True
    """)

    results = tr.evaluate_tests(before, after, test)
    assert len(results) == 1
    assert results[0]["name"] == tr.WHOLE_FILE
    assert results[0]["display"] == tr.WHOLE_FILE
    assert results[0]["label"] == tr.TEST_WRONG_ON_BEFORE
    assert results[0]["detail"], "the file-level error must still be shown"


def test_evaluate_tests_keeps_every_test_in_a_long_file(tmp_path):
    """A file with many tests gets one row per test."""
    before = write(tmp_path / "before.py", "def f():\n    return 1\n")
    after = write(tmp_path / "after.py", "def f():\n    return 2\n")
    test = write(tmp_path / "test_gen.py", """
        from target import f

        def test_a():
            assert f() == 1

        def test_b():
            assert f() == 2

        def test_c():
            assert f() == 3
    """)

    results = tr.evaluate_tests(before, after, test)
    assert len(results) == 3
    labels = sorted(row["label"] for row in results)
    # test_a expects 1, so it passes before and fails after  -> CATCHES_CHANGE
    # test_b expects 2, so it fails before and passes after  -> ODD
    # test_c expects 3, so it fails both ways               -> TEST_WRONG_ON_BEFORE
    assert labels == [tr.CATCHES_CHANGE, tr.ODD, tr.TEST_WRONG_ON_BEFORE]


# ---------------------------------------------------------------------------
# Readable names for parametrized tests
# ---------------------------------------------------------------------------

def test_split_param_id_reads_the_brackets():
    """A parametrized name is the function name plus its ID."""
    assert tr.split_param_id("test_thing[abc]") == ("test_thing", "abc")


def test_split_param_id_copes_with_no_brackets():
    """A plain test function has no parameters at all."""
    assert tr.split_param_id("test_thing") == ("test_thing", None)


def test_readable_param_id_marks_an_empty_id():
    """A bare [] would be easy to misread, so it becomes <empty>."""
    assert tr.readable_param_id("") == "<empty>"


def test_readable_param_id_marks_a_blank_id():
    """A whitespace-only ID also becomes something clear."""
    assert tr.readable_param_id("   ") == "<blank>"


def test_readable_param_id_keeps_zero_visible():
    """The number zero is a real ID and must not be treated as empty."""
    assert tr.readable_param_id("0") == "0"


def test_display_names_are_unique(tmp_path):
    """Two blank-looking cases must never end up with the same name."""
    names = ["test_x::test_behaviour[]", "test_x::test_behaviour[0]"]
    display = tr.make_display_names(names)
    assert display[names[0]] == "test_behaviour[<empty>]"
    assert display[names[1]] == "test_behaviour[0]"
    assert len(set(display.values())) == 2


def test_display_names_add_a_counter_when_still_the_same():
    """If two cases would look the same, we number them so rows differ.

    Two methods with the same name in different classes are the realistic way
    this happens, because we drop the class name from the printed row.
    """
    names = ["test_one::TestA::test_thing[same]",
             "test_two::TestB::test_thing[same]"]
    display = tr.make_display_names(names)
    assert display[names[0]] == "test_thing[same]#1"
    assert display[names[1]] == "test_thing[same]#2"
    assert len(set(display.values())) == 2


def test_display_names_keep_a_single_usable_name():
    """A name used only once is left alone, with no counter added."""
    names = ["test_one::test_thing[only]"]
    display = tr.make_display_names(names)
    assert display[names[0]] == "test_thing[only]"


def test_display_names_drop_the_file_prefix():
    """The table does not need the file name on every row."""
    display = tr.make_display_names(["test_my_file::test_thing[a]"])
    assert display["test_my_file::test_thing[a]"] == "test_thing[a]"


def test_parametrized_cases_keep_their_own_labels(tmp_path):
    """Each parameter case is judged on its own, not as one function."""
    before = write(tmp_path / "before.py", """
        def f(value):
            return value
    """)
    after = write(tmp_path / "after.py", """
        def f(value):
            return "changed"
    """)
    test = write(tmp_path / "test_gen.py", """
        import pytest
        from target import f

        @pytest.mark.parametrize("value", ["", 0, "abc"])
        def test_behaviour(value):
            assert f(value) == value
    """)

    results = tr.evaluate_tests(before, after, test)
    # All three cases pass before and fail after, so all three catch the change.
    assert len(results) == 3
    assert [row["label"] for row in results] == [tr.CATCHES_CHANGE] * 3
    # Every display name is different, so no row can be confused with another.
    assert len({row["display"] for row in results}) == 3


def test_blank_and_zero_cases_are_readable_in_the_table(tmp_path):
    """The empty string and 0 cases must print clearly and judge separately."""
    before = write(tmp_path / "before.py", "def f(v):\n    return v\n")
    after = write(tmp_path / "after.py", "def f(v):\n    return v\n")
    test = write(tmp_path / "test_gen.py", """
        import pytest
        from target import f

        @pytest.mark.parametrize("value", ["", 0])
        def test_behaviour(value):
            assert f(value) == value
    """)

    results = tr.evaluate_tests(before, after, test)
    displays = [row["display"] for row in results]
    assert "test_behaviour[<empty>]" in displays
    assert "test_behaviour[0]" in displays
    assert [row["label"] for row in results] == [tr.NO_SIGNAL, tr.NO_SIGNAL]


def test_long_names_are_not_cut_off(capsys):
    """A name too wide for the table is printed whole on its own line."""
    long_name = "test_behaviour[" + "a" * 80 + "]"
    rows = [{"name": "test_f::" + long_name, "display": long_name,
             "before": "passed", "after": "failed",
             "label": tr.CATCHES_CHANGE, "detail": ""}]
    tr.print_results(rows)

    printed = capsys.readouterr().out
    assert long_name in printed, "the whole name must appear, not a cut-off piece"


def test_failure_detail_is_shown_under_the_row(capsys):
    """The failure message goes on its own line so it is easy to read."""
    rows = [{"name": "test_f::test_x[a]", "display": "test_x[a]",
             "before": "passed", "after": "failed",
             "label": tr.CATCHES_CHANGE, "detail": "assert 1 == 2"}]
    tr.print_results(rows)

    printed = capsys.readouterr().out
    assert "assert 1 == 2" in printed
    assert "CATCHES_CHANGE" in printed


# ---------------------------------------------------------------------------
# Cleaning up the failure message, and keeping the long version
# ---------------------------------------------------------------------------

def test_clean_message_removes_the_pytest_advice():
    """Pytest tells you to use -v. That is noise for us, so it goes."""
    noisy = "assert 1 == 2 Use -v to get more diff"
    assert tr.clean_message(noisy) == "assert 1 == 2"


def test_clean_message_works_with_any_capitals():
    """Pytest sometimes writes the advice differently, so we catch both."""
    assert "more diff" not in tr.clean_message("boom use -v to get more diff")


def test_clean_message_keeps_the_real_words():
    """Only the pytest advice is removed, not the actual failure."""
    text = "AssertionError: lists differ: [1, 2] != [2, 1] Use -v to get more diff"
    cleaned = tr.clean_message(text)
    assert "AssertionError" in cleaned
    assert "[1, 2] != [2, 1]" in cleaned


def test_clean_message_does_nothing_to_empty_text():
    """No message means an empty message, not an error."""
    assert tr.clean_message("") == ""


def test_full_message_keeps_more_than_the_short_one():
    """The long version is for reading properly, so it must be longer."""
    long_text = "x" * 800
    assert len(tr.full_message(long_text)) == 800


def test_full_message_stops_at_the_limit():
    """A huge failure message is cut down, with dots showing it was cut."""
    result = tr.full_message("y" * 5000)
    assert len(result) <= tr.FULL_MESSAGE_CHARS
    assert result.endswith("...")


def test_run_tests_keeps_the_short_and_the_full_message(work):
    """One run gives us both versions of the failure message."""
    module, test = work("""
        from target import add

        def test_wrong():
            assert add(1, 2) == 99
    """)

    result = tr.run_tests(module, test)
    name = next(iter(result["tests"]))

    # The short one is small and has no pytest advice in it.
    assert len(result["failures"][name]) <= tr.MESSAGE_CHARS
    assert "more diff" not in result["failures"][name]

    # The full one is allowed to be much longer.
    assert len(result["failures_full"][name]) <= tr.FULL_MESSAGE_CHARS
    assert "more diff" not in result["failures_full"][name]


def test_the_printed_table_still_uses_the_short_message(work, capsys):
    """Only the table is cut down. The data keeps the whole thing."""
    module, test = work("""
        from target import add

        def test_wrong():
            assert add(1, 2) == 99
    """)

    results = tr.evaluate_tests(module, module, test)
    row = results[0]

    assert len(row["detail"]) <= tr.MESSAGE_CHARS
    assert len(row["detail_full"]) > 0

    tr.print_results(results)
    printed = capsys.readouterr().out
    assert "more diff" not in printed


# ---------------------------------------------------------------------------
# The flaky detector
# ---------------------------------------------------------------------------

# A test that only fails on every other rerun. rerun_failures tells it which
# rerun it is on through an environment variable, so this is never random and
# the test suite cannot become flaky itself.
ALTERNATING_TEST = """
    import os

    from target import add

    def test_alternates():
        run_number = int(os.environ.get("PRSENTINEL_RUN_INDEX", "1"))
        if run_number % 2 == 0:
            assert add(1, 2) == 99   # wrong, but only on even reruns
        else:
            assert add(1, 2) == 3
"""


def test_rerun_times_default_is_five():
    """We rerun five times unless the user says otherwise."""
    assert config.RERUN_TIMES == 5


def test_rerun_reports_a_test_that_always_fails(work):
    """A test that never passes is not flaky, it is just broken."""
    module, test = work("""
        from target import add

        def test_never_passes():
            assert add(1, 2) == 99
    """)

    result = tr.rerun_failures(module, test, times=3)
    row = next(iter(result["tests"].values()))

    assert row["verdict"] == tr.ALWAYS_FAILS
    assert row["passes"] == 0
    assert row["fails"] == 3


def test_rerun_reports_a_test_that_always_passes(work):
    """A test that never fails is not flaky either."""
    module, test = work("""
        from target import add

        def test_always_ok():
            assert add(1, 2) == 3
    """)

    result = tr.rerun_failures(module, test, times=3)
    row = next(iter(result["tests"].values()))

    assert row["verdict"] == tr.ALWAYS_PASSES
    assert row["passes"] == 3
    assert row["fails"] == 0


def test_rerun_reports_a_test_that_flips(work):
    """Passing sometimes and failing sometimes is what flaky means."""
    module, test = work(ALTERNATING_TEST)

    result = tr.rerun_failures(module, test, times=4)
    row = next(iter(result["tests"].values()))

    assert row["verdict"] == tr.FLAKY
    assert row["passes"] == 2
    assert row["fails"] == 2


def test_rerun_tells_each_test_apart(work):
    """A mixed file gives one verdict per test, not one for the whole file."""
    module, test = work("""
        import os

        from target import add

        def test_steady():
            assert add(1, 2) == 3

        def test_flips():
            run_number = int(os.environ.get("PRSENTINEL_RUN_INDEX", "1"))
            if run_number % 2 == 0:
                assert add(1, 2) == 99
            else:
                assert add(1, 2) == 3
    """)

    result = tr.rerun_failures(module, test, times=4)
    verdicts = {name.split("::")[-1]: row["verdict"]
                for name, row in result["tests"].items()}

    assert verdicts["test_steady"] == tr.ALWAYS_PASSES
    assert verdicts["test_flips"] == tr.FLAKY


def test_rerun_counts_how_many_times_it_ran(work):
    """The result says how many reruns we asked for."""
    module, test = work("""
        from target import add

        def test_ok():
            assert add(1, 2) == 3
    """)

    assert tr.rerun_failures(module, test, times=2)["times"] == 2


def test_rerun_uses_the_configured_number_when_not_told(work, monkeypatch):
    """Without a number of our own, we use the setting in config.py."""
    module, test = work("""
        import os

        from target import add

        def test_flips():
            run_number = int(os.environ.get("PRSENTINEL_RUN_INDEX", "1"))
            if run_number % 2 == 0:
                assert add(1, 2) == 99
            else:
                assert add(1, 2) == 3
    """)
    monkeypatch.setattr(config, "RERUN_TIMES", 2)

    result = tr.rerun_failures(module, test)
    assert result["times"] == 2
    assert next(iter(result["tests"].values()))["verdict"] == tr.FLAKY


def test_rerun_gives_up_on_a_file_that_will_not_load(tmp_path):
    """A broken file has no tests to judge, and we say it could not load."""
    module = write(tmp_path / "module.py", "def add(a, b):\n    return a + b\n")
    test = write(tmp_path / "test_generated.py", "import nothing_at_all\n")

    result = tr.rerun_failures(module, test, times=2)
    assert result["status"] != tr.OK
    assert result["tests"] == {}
    assert result["error"]


def test_the_run_index_reaches_the_test(work):
    """The rerun number really arrives, so a flaky test can use it."""
    module, test = work("""
        import os

        def test_reads_the_run_number():
            assert os.environ.get("PRSENTINEL_RUN_INDEX") == "3"
    """)

    assert tr.run_tests(module, test, run_index=3)["status"] == tr.OK


def test_a_missing_run_index_still_runs_the_file(work):
    """A normal run has no run number, and that is fine."""
    module, test = work("""
        def test_ok():
            pass
    """)

    assert tr.run_tests(module, test)["status"] == tr.OK


def test_rerun_leaves_no_temporary_folders(work):
    """Every rerun cleans up after itself, just like a single run does."""
    module, test = work("""
        from target import add

        def test_ok():
            assert add(1, 2) == 3
    """)

    before_folders = set(Path(tempfile.gettempdir()).glob("prsentinel_run_*"))
    tr.rerun_failures(module, test, times=2)
    after_folders = set(Path(tempfile.gettempdir()).glob("prsentinel_run_*"))

    assert before_folders == after_folders


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def test_command_line_prints_a_table(tmp_path, capsys, monkeypatch):
    """The terminal entry point works and says what happened."""
    before = write(tmp_path / "before.py", "def f():\n    return 1\n")
    after = write(tmp_path / "after.py", "def f():\n    return 2\n")
    test = write(tmp_path / "test_gen.py", """
        from target import f

        def test_f():
            assert f() == 1
    """)

    monkeypatch.setattr(sys, "argv", ["test_runner", before, after, test])
    assert tr.main() == 0

    printed = capsys.readouterr().out
    assert "test name" in printed
    assert tr.CATCHES_CHANGE in printed
    assert "Summary" in printed


def test_command_line_exits_non_zero_for_a_missing_file(capsys, monkeypatch):
    """A wrong path is a fault in how the runner was called."""
    monkeypatch.setattr(sys, "argv",
                        ["test_runner", "no_such_before.py", "no_such_after.py",
                         "no_such_test.py"])
    assert tr.main() == 1
    assert "Cannot read" in capsys.readouterr().out


def test_command_line_exits_zero_even_when_tests_fail(tmp_path, capsys, monkeypatch):
    """Failing tests are a finding, not a fault in the runner."""
    before = write(tmp_path / "before.py", "def f():\n    return 1\n")
    after = write(tmp_path / "after.py", "def f():\n    return 1\n")
    test = write(tmp_path / "test_gen.py", """
        from target import f

        def test_f():
            assert f() == 999
    """)

    monkeypatch.setattr(sys, "argv", ["test_runner", before, after, test])
    assert tr.main() == 0
    assert tr.TEST_WRONG_ON_BEFORE in capsys.readouterr().out
