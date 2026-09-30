"""Tests for the diff extractor.

Run them with:  pytest
"""

import json
import sys
from pathlib import Path

from prsentinel import diff_extractor

# The examples folder sits two levels above this file:
#   tests/ -> prsentinel/ -> examples/
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
ROUND1 = EXAMPLES / "round1_off_by_one"
ROUND2 = EXAMPLES / "round2_mutable_default"


def find_change(changes, name):
    """Return the one change with this function name, or None."""
    for change in changes:
        if change["name"] == name:
            return change
    return None


# ---------------------------------------------------------------------------
# Round 1: the off-by-one bug
# ---------------------------------------------------------------------------

def test_round1_get_recent_scores_is_modified():
    """The off-by-one fix must show up as a modified function."""
    changes = diff_extractor.extract_changes_from_files(
        ROUND1 / "before.py", ROUND1 / "after.py"
    )
    change = find_change(changes, "get_recent_scores")
    assert change is not None, "get_recent_scores was not reported at all"
    assert change["change_type"] == "modified"


def test_round1_old_and_new_code_are_the_whole_function():
    """We keep the whole function, not just the one line that changed."""
    changes = diff_extractor.extract_changes_from_files(
        ROUND1 / "before.py", ROUND1 / "after.py"
    )
    change = find_change(changes, "get_recent_scores")

    # before.py is the CORRECT version, after.py holds the off-by-one BUG.
    assert "max(0, len(scores) - window)" in change["old_code"]
    assert "scores[-window - 1:]" in change["new_code"]


def test_round1_untouched_function_is_not_reported():
    """average_score did not change, so it must be left out."""
    changes = diff_extractor.extract_changes_from_files(
        ROUND1 / "before.py", ROUND1 / "after.py"
    )
    assert find_change(changes, "average_score") is None


# ---------------------------------------------------------------------------
# Round 2: the mutable default argument bug
# ---------------------------------------------------------------------------

def test_round2_add_item_to_cart_is_modified():
    """The mutable default fix must show up as a modified function."""
    changes = diff_extractor.extract_changes_from_files(
        ROUND2 / "before.py", ROUND2 / "after.py"
    )
    change = find_change(changes, "add_item_to_cart")
    assert change is not None, "add_item_to_cart was not reported at all"
    assert change["change_type"] == "modified"


def test_round2_signature_change_is_visible_in_old_and_new_code():
    """The signature is the interesting part here: cart=None became cart=[]."""
    changes = diff_extractor.extract_changes_from_files(
        ROUND2 / "before.py", ROUND2 / "after.py"
    )
    change = find_change(changes, "add_item_to_cart")

    # before.py is the CORRECT version, after.py has the mutable-default BUG.
    assert "cart=None" in change["old_code"]
    assert "if cart is None:" in change["old_code"]
    assert "cart=[]" in change["new_code"]
    assert "if cart is None:" not in change["new_code"]


def test_round2_untouched_function_is_not_reported():
    """remove_item_from_cart did not change."""
    changes = diff_extractor.extract_changes_from_files(
        ROUND2 / "before.py", ROUND2 / "after.py"
    )
    assert find_change(changes, "remove_item_from_cart") is None


# ---------------------------------------------------------------------------
# How "modified" is decided: ast.dump() ignores comments and spacing
# ---------------------------------------------------------------------------

def test_comment_only_edit_is_not_a_change():
    """A comment is not part of the syntax tree, so it does not count."""
    before = "def hello():\n    return 1\n"
    after = "def hello():\n    # a brand new comment\n    return 1\n"
    assert diff_extractor.extract_changes(before, after) == []


def test_whitespace_only_edit_is_not_a_change():
    """Blank lines and trailing spaces are not part of the tree either."""
    before = "def hello():\n    return 1\n"
    after = "def hello():\n\n\n    return 1   \n\n"
    assert diff_extractor.extract_changes(before, after) == []


def test_changed_default_argument_is_a_change():
    """A different default value IS part of the tree, so it must be reported."""
    before = "def add(item, cart=None):\n    return cart\n"
    after = "def add(item, cart=[]):\n    return cart\n"
    changes = diff_extractor.extract_changes(before, after)
    assert len(changes) == 1
    assert changes[0]["change_type"] == "modified"


def test_changed_docstring_is_a_change():
    """A docstring is part of the tree, so it must be reported."""
    before = "def hello():\n    \"\"\"old words.\"\"\"\n    return 1\n"
    after = "def hello():\n    \"\"\"new words.\"\"\"\n    return 1\n"
    changes = diff_extractor.extract_changes(before, after)
    assert len(changes) == 1
    assert changes[0]["change_type"] == "modified"


def test_renaming_a_parameter_is_a_change():
    """Changing a parameter name changes the tree."""
    before = "def hello(name):\n    return name\n"
    after = "def hello(label):\n    return label\n"
    changes = diff_extractor.extract_changes(before, after)
    assert changes[0]["change_type"] == "modified"


# ---------------------------------------------------------------------------
# Added and removed functions, using tiny snippets
# ---------------------------------------------------------------------------

def test_added_function_is_reported_as_added():
    """A function that only exists in the new file is 'added'."""
    before = "def old():\n    return 1\n"
    after = "def old():\n    return 1\n\n\ndef new():\n    return 2\n"
    change = find_change(diff_extractor.extract_changes(before, after), "new")
    assert change["change_type"] == "added"
    assert change["old_code"] == ""
    assert change["old_start_line"] is None
    assert change["new_start_line"] is not None


def test_removed_function_is_reported_as_removed():
    """A function that only exists in the old file is 'removed'."""
    before = "def gone():\n    return 1\n\n\ndef stays():\n    return 2\n"
    after = "def stays():\n    return 2\n"
    change = find_change(diff_extractor.extract_changes(before, after), "gone")
    assert change["change_type"] == "removed"
    assert change["new_code"] == ""
    assert change["new_start_line"] is None


def test_removed_method_inside_a_class_is_reported_as_removed():
    """A deleted class shows up as its methods being removed."""
    before = "class Cart:\n    def __init__(self):\n        self.items = []\n"
    after = "value = 1\n"
    change = find_change(diff_extractor.extract_changes(before, after),
                         "Cart.__init__")
    assert change["change_type"] == "removed"


# ---------------------------------------------------------------------------
# Other things the extractor should handle
# ---------------------------------------------------------------------------

def test_identical_files_report_nothing():
    """If nothing changed, there is nothing to say."""
    code = "def hello():\n    return 'hi'\n"
    assert diff_extractor.extract_changes(code, code) == []


def test_method_names_include_their_class():
    """A method is reported as ClassName.method so names cannot collide."""
    before = "class A:\n    def run(self):\n        return 1\n"
    after = "class A:\n    def run(self):\n        return 2\n"
    changes = diff_extractor.extract_changes(before, after)
    assert [c["name"] for c in changes] == ["A.run"]


def test_nested_function_names_include_the_parent():
    """A function inside a function is reported as outer.inner."""
    before = "def outer():\n    def inner():\n        return 1\n    return inner\n"
    after = "def outer():\n    def inner():\n        return 2\n    return inner\n"
    changes = diff_extractor.extract_changes(before, after)
    names = [c["name"] for c in changes]
    assert "outer.inner" in names


def test_line_numbers_point_at_the_right_place():
    """The reported line numbers should match where the function really is."""
    before = "def first():\n    return 1\n\n\ndef second():\n    return 2\n"
    after = "def first():\n    return 1\n\n\ndef second():\n    return 3\n"
    changes = diff_extractor.extract_changes(before, after)
    change = find_change(changes, "second")
    assert change["old_start_line"] == 5
    assert change["old_end_line"] == 6
    assert change["new_start_line"] == 5
    assert change["new_end_line"] == 6


def test_results_can_be_turned_into_json():
    """The results must survive being saved as JSON."""
    before = "def hello():\n    return 1\n"
    after = "def hello():\n    return 2\n"
    changes = diff_extractor.extract_changes(before, after)
    assert json.loads(json.dumps(changes)) == changes


# ---------------------------------------------------------------------------
# The command line entry point
# ---------------------------------------------------------------------------

def test_command_line_prints_a_summary(capsys, monkeypatch):
    """python -m prsentinel.diff_extractor before.py after.py should work."""
    from prsentinel.diff_extractor import main

    # monkeypatch sets sys.argv and puts it back for us afterwards.
    monkeypatch.setattr(
        sys, "argv",
        ["diff_extractor", str(ROUND1 / "before.py"), str(ROUND1 / "after.py")]
    )
    exit_code = main()
    printed = capsys.readouterr().out

    assert exit_code == 0
    assert "modified" in printed.lower()
    assert "get_recent_scores" in printed


def test_command_line_json_option(capsys, monkeypatch):
    """The --json option should print valid JSON."""
    from prsentinel.diff_extractor import main

    monkeypatch.setattr(
        sys, "argv",
        ["diff_extractor", str(ROUND2 / "before.py"),
         str(ROUND2 / "after.py"), "--json"]
    )
    exit_code = main()
    printed = capsys.readouterr().out
    parsed = json.loads(printed)

    assert exit_code == 0
    assert find_change(parsed, "add_item_to_cart")["change_type"] == "modified"


def test_command_line_reports_a_missing_file(capsys, monkeypatch):
    """A wrong path should fail politely instead of crashing."""
    from prsentinel.diff_extractor import main

    monkeypatch.setattr(
        sys, "argv",
        ["diff_extractor", "does_not_exist.py", "also_missing.py"]
    )
    exit_code = main()

    assert exit_code == 1
    assert "Cannot read" in capsys.readouterr().out
